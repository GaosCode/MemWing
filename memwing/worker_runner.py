from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence

from memwing.api.env import load_app_env
from memwing.infrastructure.agents.openclaw_adapter_factory import create_worker_runner_from_env
from memwing.workers.runner import PipelineWorkerLane


def main(argv: Sequence[str] | None = None, *, prog: str = "memwing-worker") -> None:
    load_app_env()
    args = _parser(prog=prog).parse_args(argv)
    asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> None:
    handle = await create_worker_runner_from_env(worker_id=args.worker_id)
    try:
        if args.once:
            result = await handle.runner.run_once(
                outbox_limit=args.outbox_limit,
                graph_limit=args.graph_limit,
                lane=PipelineWorkerLane(args.lane),
            )
            print(
                json.dumps(
                    {
                        "outbox": {
                            "claimed": result.outbox.claimed,
                            "succeeded": result.outbox.succeeded,
                            "retried": result.outbox.retried,
                            "dead_lettered": result.outbox.dead_lettered,
                            "evidence_indexed_source_events": (
                                result.outbox.evidence_indexed_source_events
                            ),
                        },
                        "graph": {
                            "claimed": result.graph.claimed,
                            "succeeded": result.graph.succeeded,
                            "retried": result.graph.retried,
                            "dead_lettered": result.graph.dead_lettered,
                        },
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return
        await handle.runner.run_forever(
            interval_seconds=args.interval_seconds,
            idle_interval_seconds=args.idle_interval_seconds,
            outbox_limit=args.outbox_limit,
            graph_limit=args.graph_limit,
            lane=PipelineWorkerLane(args.lane),
        )
    finally:
        await handle.close()


def _parser(*, prog: str = "memwing-worker") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument("--once", action="store_true", help="Run one worker iteration and exit.")
    parser.add_argument(
        "--lane",
        choices=[lane.value for lane in PipelineWorkerLane],
        default=PipelineWorkerLane.ALL.value,
    )
    parser.add_argument("--worker-id", default="memwing_worker")
    parser.add_argument("--outbox-limit", type=int, default=20)
    parser.add_argument("--graph-limit", type=int, default=20)
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--idle-interval-seconds", type=float, default=5.0)
    return parser


if __name__ == "__main__":
    main()
