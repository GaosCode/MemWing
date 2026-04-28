import ast
from pathlib import Path


FORBIDDEN_LAYER_IMPORTS = ("graphiti", "openclaw", "feishu", "slack")


def test_core_and_application_do_not_import_external_sdk_boundaries() -> None:
    package_root = Path(__file__).resolve().parents[2] / "memwing"
    checked_files = [
        *sorted((package_root / "core").rglob("*.py")),
        *sorted((package_root / "application").rglob("*.py")),
    ]

    violations: list[str] = []
    for path in checked_files:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue

            for name in names:
                if any(forbidden in name.lower() for forbidden in FORBIDDEN_LAYER_IMPORTS):
                    violations.append(f"{path}: {name}")

    assert violations == []
