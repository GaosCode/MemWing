from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from memwing.api.env import load_app_env


@dataclass(frozen=True, slots=True)
class ChildSpec:
    name: str
    argv: tuple[str, ...]


def main(argv: Sequence[str] | None = None) -> None:
    load_app_env()
    args = _parser().parse_args(argv)
    raise SystemExit(asyncio.run(_run(args)))


async def _run(args: argparse.Namespace) -> int:
    specs = _child_specs(args)
    children: dict[str, asyncio.subprocess.Process] = {}
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop_event.set)
        except NotImplementedError:
            pass

    try:
        for spec in specs:
            children[spec.name] = await asyncio.create_subprocess_exec(*spec.argv)

        early_exit = await _wait_for_early_exit(children, args.startup_grace_seconds)
        if early_exit is not None:
            return early_exit

        wait_task = asyncio.create_task(_wait_for_any_exit(children))
        stop_task = asyncio.create_task(stop_event.wait())
        done, pending = await asyncio.wait(
            {wait_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if stop_task in done:
            await _terminate_children(children)
            return 0
        exit_code = wait_task.result()
        await _terminate_children(children)
        return exit_code
    except Exception:
        await _terminate_children(children)
        raise


def _child_specs(args: argparse.Namespace) -> tuple[ChildSpec, ...]:
    api = ChildSpec(
        name="memwing-api",
        argv=(
            sys.executable,
            "-m",
            "memwing.api_runner",
            "--host",
            args.host,
            "--port",
            str(args.port),
        )
        + (("--reload",) if args.reload else ()),
    )
    if getattr(args, "api_only", False) or args.allow_degraded_pipeline:
        return (api,)
    pipeline = ChildSpec(
        name="memwing-pipeline",
        argv=(sys.executable, "-m", "memwing.pipeline_runner"),
    )
    return (api, pipeline)


async def _wait_for_early_exit(
    children: dict[str, asyncio.subprocess.Process],
    startup_grace_seconds: float,
) -> int | None:
    if startup_grace_seconds <= 0:
        return None
    wait_task = asyncio.create_task(_wait_for_any_exit(children))
    try:
        return await asyncio.wait_for(wait_task, timeout=startup_grace_seconds)
    except TimeoutError:
        wait_task.cancel()
        return None


async def _wait_for_any_exit(children: dict[str, asyncio.subprocess.Process]) -> int:
    tasks = {
        asyncio.create_task(process.wait()): name
        for name, process in children.items()
    }
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    task = next(iter(done))
    return task.result() or 1


async def _terminate_children(children: dict[str, asyncio.subprocess.Process]) -> None:
    for process in children.values():
        if process.returncode is None:
            process.terminate()
    if children:
        await asyncio.gather(
            *(process.wait() for process in children.values()),
            return_exceptions=True,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memwing-runtime")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--api-only", action="store_true")
    parser.add_argument("--allow-degraded-pipeline", action="store_true")
    parser.add_argument("--startup-grace-seconds", type=float, default=1.0)
    return parser


if __name__ == "__main__":
    main()
