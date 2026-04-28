import asyncio

from memwing.infrastructure.platforms.feishu_connector import FeishuConnector
from tests.unit.feishu_connector_test_support import FakePushSender, build_push_candidate


def test_send_candidate_uses_push_sender_boundary() -> None:
    sender = FakePushSender()
    connector = FeishuConnector(project_memory_space_id="project_001", push_sender=sender)
    candidate = build_push_candidate()

    result = asyncio.run(connector.send_candidate(candidate))

    assert result.delivered is True
    assert result.provider_message_id == "sent_001"
    assert sender.sent == [("oc_group_001", "Review this candidate.", "trace_001")]


def test_send_candidate_without_push_sender_reports_not_delivered() -> None:
    connector = FeishuConnector(project_memory_space_id="project_001")
    candidate = build_push_candidate()

    result = asyncio.run(connector.send_candidate(candidate))

    assert result.delivered is False
    assert result.provider_message_id is None
    assert result.candidate_id == "push_001"
    assert result.trace_id == "trace_001"
