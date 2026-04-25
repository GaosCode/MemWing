from memwing_benchmark.adapters.memwing import MemWingAdapter
from memwing_benchmark.errors import BenchmarkError


def test_memwing_adapter_is_explicit_v1_placeholder() -> None:
    adapter = MemWingAdapter()

    try:
        adapter.run_case()
    except BenchmarkError as exc:
        assert "not implemented in v1" in str(exc)
    else:
        raise AssertionError("MemWing adapter must not silently run in v1")
