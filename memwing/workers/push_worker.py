from __future__ import annotations

from dataclasses import dataclass

from memwing.application.push_service import PushService
from memwing.core.scope import EffectiveScope


@dataclass(frozen=True, slots=True)
class PushWorkerResult:
    forgetting_review_count: int
    decision_card_count: int
    trace_id: str


class PushWorker:
    def __init__(self, push_service: PushService, *, generation_limit: int = 50) -> None:
        self._push_service = push_service
        self._generation_limit = generation_limit

    async def generate_candidates(
        self,
        *,
        scope: EffectiveScope,
        trace_id: str,
    ) -> PushWorkerResult:
        forgetting_review = await self._push_service.generate_forgetting_review(
            scope=scope,
            limit=self._generation_limit,
            trace_id=trace_id,
        )
        decision_cards = await self._push_service.generate_decision_cards(
            scope=scope,
            limit=self._generation_limit,
            trace_id=trace_id,
        )
        return PushWorkerResult(
            forgetting_review_count=forgetting_review.generated_count,
            decision_card_count=decision_cards.generated_count,
            trace_id=trace_id,
        )
