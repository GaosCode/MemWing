from __future__ import annotations

import argparse

from memwing.runtime_runner import _child_specs


def test_runtime_runner_starts_api_and_pipeline_by_default() -> None:
    specs = _child_specs(
        argparse.Namespace(
            host="127.0.0.1",
            port=8000,
            reload=False,
            allow_degraded_pipeline=False,
        )
    )

    assert tuple(spec.name for spec in specs) == ("memwing-api", "memwing-pipeline")
    assert specs[0].argv[2] == "memwing.api_runner"
    assert specs[1].argv[2] == "memwing.pipeline_runner"


def test_runtime_runner_degraded_pipeline_starts_api_only() -> None:
    specs = _child_specs(
        argparse.Namespace(
            host="127.0.0.1",
            port=8000,
            reload=False,
            allow_degraded_pipeline=True,
        )
    )

    assert tuple(spec.name for spec in specs) == ("memwing-api",)


def test_runtime_runner_api_only_flag_starts_api_only() -> None:
    specs = _child_specs(
        argparse.Namespace(
            host="127.0.0.1",
            port=8000,
            reload=False,
            api_only=True,
            allow_degraded_pipeline=False,
        )
    )

    assert tuple(spec.name for spec in specs) == ("memwing-api",)
