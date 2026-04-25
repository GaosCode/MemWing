from pathlib import Path

from memwing_benchmark.schema import load_cases


def test_loads_cases_json_and_filters_case_id() -> None:
    cases = load_cases(Path("cases.json"), case_id="bs001")

    assert len(cases) == 1
    case = cases[0]
    assert case.case_id == "bs001"
    assert case.category == "basic_sanity"
    assert len(case.seed_messages) == 3
    assert len(case.preseed_memories) == 0
    assert [probe.probe_id for probe in case.probes] == ["bs001_p1", "bs001_p2"]
    assert case.probes[0].gold_evidence_ids == ["bs001_s1"]


def test_loads_all_current_v1_cases() -> None:
    cases = load_cases(Path("cases.json"))

    assert len(cases) == 10
    assert sum(len(case.probes) for case in cases) == 18
    assert {case.category for case in cases} == {
        "basic_sanity",
        "fact_update",
        "long_term_preseed",
        "temporal_conflict",
    }
    assert any(case.preseed_memories for case in cases)
