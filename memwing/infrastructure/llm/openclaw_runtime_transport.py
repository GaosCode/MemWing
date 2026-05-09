from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import os
import signal
import sys
import tempfile
from typing import Protocol

from memwing.infrastructure.llm.errors import LLMProviderError


@dataclass(frozen=True, slots=True)
class OpenClawCommandResult:
    returncode: int
    stdout: str
    stderr: str


class OpenClawRuntimeTransport(Protocol):
    async def run(
        self,
        *,
        command: Sequence[str],
        cwd: str | None,
        env: Mapping[str, str] | None,
        timeout_seconds: float,
    ) -> OpenClawCommandResult:
        ...


class SubprocessOpenClawRuntimeTransport:
    async def run(
        self,
        *,
        command: Sequence[str],
        cwd: str | None,
        env: Mapping[str, str] | None,
        timeout_seconds: float,
    ) -> OpenClawCommandResult:
        process_env = None if env is None else {**os.environ, **env}
        debug_log(f"OpenClaw subprocess start: cmd={command[0]} cwd={cwd} timeout={timeout_seconds}s")

        def _run_sync() -> tuple[int, bytes, bytes]:
            import subprocess as _subprocess

            # Use a temp file for stdout to avoid pipe hang on macOS Python 3.13
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
                stdout_path = tmp.name
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
                stderr_path = tmp.name

            try:
                with open(stdout_path, "wb") as out_fh, open(stderr_path, "wb") as err_fh:
                    proc = _subprocess.Popen(
                        tuple(command),
                        cwd=cwd,
                        env=process_env,
                        stdin=_subprocess.DEVNULL,
                        stdout=out_fh,
                        stderr=err_fh,
                        start_new_session=True,
                    )
                    debug_log(f"OpenClaw pid={proc.pid} waiting (max {timeout_seconds:.0f}s)...")
                    try:
                        proc.wait(timeout=timeout_seconds)
                    except _subprocess.TimeoutExpired:
                        debug_log(f"OpenClaw pid={proc.pid} TIMEOUT, killing...")
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except (ProcessLookupError, OSError):
                            proc.kill()
                        proc.wait()
                        raise LLMProviderError("OpenClaw runtime model run timed out")

                with open(stdout_path, "rb") as in_fh:
                    stdout_bytes = in_fh.read()
                with open(stderr_path, "rb") as in_fh:
                    stderr_bytes = in_fh.read()
            finally:
                try:
                    os.unlink(stdout_path)
                except OSError:
                    pass
                try:
                    os.unlink(stderr_path)
                except OSError:
                    pass

            debug_log(
                f"OpenClaw pid={proc.pid} done rc={proc.returncode} "
                f"out_len={len(stdout_bytes)} err_len={len(stderr_bytes)}"
            )
            return proc.returncode, stdout_bytes, stderr_bytes

        try:
            returncode, stdout_bytes, stderr_bytes = await asyncio.to_thread(_run_sync)
        except LLMProviderError:
            raise
        except OSError as exc:
            debug_log(f"OpenClaw OSError: {exc}")
            raise LLMProviderError("OpenClaw runtime command failed to start") from exc

        return OpenClawCommandResult(
            returncode=returncode,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
        )


_DEBUG_OPENCLAW = os.environ.get("MEMWING_DEBUG_OPENCLAW") == "1"


def debug_log(msg: str) -> None:
    if not _DEBUG_OPENCLAW:
        return
    print(f"[openclaw-runtime] {msg}", file=sys.stderr, flush=True)
