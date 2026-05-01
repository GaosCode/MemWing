import json
from pathlib import Path

from memwing.api.control import MemoryListResponse


FIXTURE_PATH = Path("shared_contracts/memory_list.fixture.json")


def test_memory_list_fixture_matches_backend_response_contract() -> None:
    payload = json.loads(FIXTURE_PATH.read_text())
    response = MemoryListResponse.from_json(payload)

    assert response.trace_id == "trace_memory_list_fixture"
    assert response.items[0].id == "mem-q813"
    assert response.items[0].display_type == "preference"
    assert response.items[0].status == "active"
    assert response.items[0].decay_score == 0.84
    assert response.items[0].retention_reason == "score_above_recall_threshold"
    assert response.items[1].curve_state == "below_threshold"
    assert response.items[2].graph_backend_raw_retained is True
