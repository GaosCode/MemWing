from __future__ import annotations

from collections.abc import Sequence

from memwing.worker_runner import main as worker_main


def main(argv: Sequence[str] | None = None) -> None:
    worker_main(argv, prog="memwing-pipeline")


if __name__ == "__main__":
    main()
