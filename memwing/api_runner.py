from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

import uvicorn

from memwing.api.env import load_app_env


def main(argv: Sequence[str] | None = None) -> None:
    load_app_env()
    args = _parser().parse_args(argv)
    uvicorn.run(
        "memwing.api.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memwing-api")
    parser.add_argument("--host", default=os.environ.get("MEMWING_API_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MEMWING_API_PORT", "8000")))
    parser.add_argument("--reload", action="store_true")
    return parser


if __name__ == "__main__":
    main()
