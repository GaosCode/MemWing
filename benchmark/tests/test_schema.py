from pathlib import Path

from memwing_benchmark.schema import load_cases


def test_loads_cases_json_and_filters_case_id() -> None:
    cases = load_cases(Path("datasets"), case_id="bs001")

    assert len(cases) == 1
    case = cases[0]
    assert case.case_id == "bs001"
    assert case.category == "basic_sanity"
    assert len(case.seed_messages) == 13
    assert case.seed_messages[0].source is None
    assert [probe.probe_id for probe in case.probes] == ["bs001_p1", "bs001_p2"]
    assert case.probes[0].gold_evidence_ids == ["bs001_s1"]


def test_loads_all_current_v1_cases() -> None:
    cases = load_cases(Path("datasets"))

    assert len(cases) == 10
    assert len({case.case_id for case in cases}) == 10
    assert sum(len(case.probes) for case in cases) == 18
    assert {case.category for case in cases} == {
        "basic_sanity",
        "fact_update",
        "long_term_preseed",
        "temporal_conflict",
    }
    assert all(case.seed_messages for case in cases)
    assert sum(len(case.seed_messages) for case in cases) == 124


def test_dataset_directory_ignores_reference_cases_json() -> None:
    cases = load_cases(Path("datasets"))

    assert [case.case_id for case in cases].count("bs001") == 1


def test_loads_single_case_json_object() -> None:
    cases = load_cases(Path("datasets/bs001.json"))

    assert len(cases) == 1
    assert cases[0].case_id == "bs001"


def test_dataset_probes_match_reference_and_resolve_evidence() -> None:
    for case in load_cases(Path("datasets")):
        seed_by_id = {message.id: message.content for message in case.seed_messages}
        for probe in case.probes:
            evidence_ids = [*probe.gold_evidence_ids, *probe.old_evidence_ids]
            assert evidence_ids
            for evidence_id in evidence_ids:
                assert seed_by_id[evidence_id].strip()


def test_expected_memory_items_cover_probe_gold_evidence() -> None:
    for case in load_cases(Path("datasets")):
        preseed_evidence_ids = {
            evidence_id
            for item in case.expected_memory_items
            for evidence_id in item.gold_evidence_ids
        }
        for probe in case.probes:
            assert set(probe.gold_evidence_ids) <= preseed_evidence_ids


def test_preseed_files_exist_for_all_cases_and_include_full_seed_messages() -> None:
    for case in load_cases(Path("datasets")):
        preseed_path = Path("datasets/preseed") / f"{case.case_id}.md"
        assert preseed_path.exists()
        preseed_text = preseed_path.read_text(encoding="utf-8")
        for message in case.seed_messages:
            assert message.content in preseed_text
            assert message.id not in preseed_text
