from __future__ import annotations

import ast
from pathlib import Path


GRAPHITI_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "memwing"
    / "infrastructure"
    / "graph"
    / "graphiti_core"
    / "graphiti.py"
)


def test_vendored_graphiti_constructor_does_not_create_default_provider_clients() -> None:
    tree = ast.parse(GRAPHITI_SOURCE.read_text(encoding="utf-8"), filename=str(GRAPHITI_SOURCE))
    constructor = _graphiti_constructor(tree)

    forbidden_calls: list[str] = []
    for node in ast.walk(constructor):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"OpenAIClient", "OpenAIEmbedder", "OpenAIRerankerClient"}:
                forbidden_calls.append(node.func.id)

    assert forbidden_calls == []


def test_graphiti_types_do_not_leak_outside_graph_infrastructure() -> None:
    package_root = Path(__file__).resolve().parents[2] / "memwing"
    checked_roots = [
        package_root / "core",
        package_root / "application",
        package_root / "api",
        package_root / "workers",
    ]

    violations: list[str] = []
    for root in checked_roots:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    if "graphiti_core" in name:
                        violations.append(f"{path}: {name}")

    assert violations == []


def _graphiti_constructor(tree: ast.Module) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Graphiti":
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == "__init__":
                    return child
    raise AssertionError("Graphiti.__init__ not found")
