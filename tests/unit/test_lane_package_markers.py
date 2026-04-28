from pathlib import Path


def test_lane_boundary_directories_have_package_markers() -> None:
    root = Path(__file__).resolve().parents[2] / "memwing"
    package_dirs = (
        "api",
        "application",
        "core",
        "infrastructure",
        "infrastructure/agents",
        "infrastructure/db",
        "infrastructure/evidence",
        "infrastructure/graph",
        "infrastructure/llm",
        "infrastructure/platforms",
        "integrations",
        "integrations/openclaw",
        "ports",
        "workers",
    )

    missing_markers = [
        path for path in package_dirs if not (root / path / "__init__.py").is_file()
    ]

    assert missing_markers == []
