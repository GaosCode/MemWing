import ast
from pathlib import Path

import pytest

from memwing_benchmark.adapters.memwing import MemWingAdapter
from memwing_benchmark.errors import BenchmarkError


def test_memwing_adapter_requires_http_base_url() -> None:
    from memwing_benchmark.config import MemWingConfig

    with pytest.raises(BenchmarkError, match="memwing.base_url is required"):
        MemWingAdapter(MemWingConfig(base_url=""))


def test_memwing_adapter_does_not_import_application_infrastructure_or_workers() -> None:
    source = Path("memwing_benchmark/adapters/memwing.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    forbidden_prefixes = (
        "memwing.application",
        "memwing.infrastructure",
        "memwing.workers",
    )
    imports: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)

    assert not [
        imported
        for imported in imports
        if any(imported.startswith(prefix) for prefix in forbidden_prefixes)
    ]
