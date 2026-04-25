from memwing_benchmark.errors import BenchmarkError


class MemWingAdapter:
    """Explicit placeholder for the future experiment backend."""

    def run_case(self) -> None:
        raise BenchmarkError("MemWing adapter is not implemented in v1")
