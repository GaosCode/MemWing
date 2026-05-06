from __future__ import annotations

import re


_QUERY_STOP_TERMS = frozenset(
    (
        "什么",
        "时候",
        "是谁",
        "现在",
        "当前",
        "最终",
        "项目",
        "改造",
        "看板",
    )
)


def search_relevance_score(query: str, text: str) -> float:
    normalized_query = _normalize_relevance_text(query)
    normalized_text = _normalize_relevance_text(text)
    if not normalized_query or not normalized_text:
        return 0

    score = _lexical_overlap_score(normalized_query, normalized_text)
    if normalized_query in normalized_text:
        score += 0.3
    score += _intent_relevance_score(normalized_query, normalized_text)
    score += _temporal_relevance_adjustment(normalized_query, normalized_text)
    score = _apply_required_intent_caps(normalized_query, normalized_text, score)
    return max(0.0, min(score, 1.4))


def search_relevance_matches(query: str, text: str, *, min_score: float = 0.18) -> bool:
    if not query.strip():
        return True
    return search_relevance_score(query, text) >= min_score


def _lexical_overlap_score(normalized_query: str, normalized_text: str) -> float:
    query_terms = _query_terms(normalized_query)
    if not query_terms:
        return 0
    total_weight = sum(_term_weight(term) for term in query_terms)
    if total_weight <= 0:
        return 0
    matched_weight = sum(
        _term_weight(term)
        for term in query_terms
        if term in normalized_text
    )
    return min((matched_weight / total_weight) * 0.55, 0.55)


def _intent_relevance_score(normalized_query: str, normalized_text: str) -> float:
    score = 0.0
    for intent in _query_intents(normalized_query):
        if intent == "deadline" and _text_has_deadline_signal(normalized_text):
            score += 0.45
        elif intent == "owner" and _text_has_any(normalized_text, ("负责人", "负责", "接手")):
            score += 0.35
        elif intent == "acceptance_owner" and _text_has_any(
            normalized_text,
            ("验收人", "验收负责人", "验收负责"),
        ):
            score += 0.35
        elif intent == "scope" and _text_has_any(
            normalized_text,
            ("交付范围", "范围", "包含", "不包含", "只包含"),
        ):
            score += 0.3
    return min(score, 0.7)


def _temporal_relevance_adjustment(normalized_query: str, normalized_text: str) -> float:
    score = 0.0
    current_query = _query_needs_current_context(normalized_query)
    historical_query = _query_needs_historical_context(normalized_query)
    if current_query and _text_has_any(
        normalized_text,
        (
            "当前",
            "现在",
            "最新",
            "最终",
            "截止",
            "确定为",
            "调整为",
            "变更为",
            "不再",
            "只保留",
            "只包含",
        ),
    ):
        score += 0.25
    if current_query and not historical_query and _text_has_any(
        normalized_text,
        ("初始计划", "暂定", "当时决定", "第一次评审", "还在等"),
    ):
        score -= 0.35
    if historical_query and _text_has_any(
        normalized_text,
        ("曾经", "讨论过", "当时", "中间讨论", "第一次评审"),
    ):
        score += 0.25
    return score


def _apply_required_intent_caps(
    normalized_query: str,
    normalized_text: str,
    score: float,
) -> float:
    intents = _query_intents(normalized_query)
    if "deadline" in intents and not _text_has_deadline_signal(normalized_text):
        score = min(score, 0.12)
    if "owner" in intents and not _text_has_any(normalized_text, ("负责人", "负责", "接手")):
        score = min(score, 0.12)
    if "acceptance_owner" in intents and not _text_has_any(
        normalized_text,
        ("验收人", "验收负责人", "验收负责"),
    ):
        score = min(score, 0.12)
    return score


def _query_intents(normalized_query: str) -> tuple[str, ...]:
    intents: list[str] = []
    if _text_has_any(
        normalized_query,
        ("截止时间", "最终验收截止", "截止", "什么时候", "时间", "日期", "几点"),
    ):
        intents.append("deadline")
    if _text_has_any(normalized_query, ("负责人", "谁负责", "负责谁", "现在的负责人")):
        intents.append("owner")
    if _text_has_any(normalized_query, ("验收人", "谁验收", "验收负责人")):
        intents.append("acceptance_owner")
    if _text_has_any(normalized_query, ("交付范围", "范围", "包含什么", "包括什么")):
        intents.append("scope")
    return tuple(dict.fromkeys(intents))


def _text_has_deadline_signal(normalized_text: str) -> bool:
    return (
        _text_has_any(normalized_text, ("截止", "截止时间", "时间", "日期"))
        or bool(re.search(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}", normalized_text))
        or bool(re.search(r"\d{1,2}:\d{2}", normalized_text))
    )


def _query_needs_current_context(normalized_query: str) -> bool:
    return _text_has_any(
        normalized_query,
        ("当前", "现在", "最新", "有效", "还有效", "还包括", "还负责", "正式推进", "最终"),
    )


def _query_needs_historical_context(normalized_query: str) -> bool:
    return _text_has_any(normalized_query, ("曾经", "讨论过", "历史", "当时"))


def _query_terms(normalized_query: str) -> tuple[str, ...]:
    terms: set[str] = set(re.findall(r"[a-z0-9]+", normalized_query))
    cjk_text = re.sub(r"[^一-鿿]+", "", normalized_query)
    for size in (2, 3, 4, 5, 6):
        for index in range(0, max(len(cjk_text) - size + 1, 0)):
            term = cjk_text[index : index + size]
            if term not in _QUERY_STOP_TERMS:
                terms.add(term)
    return tuple(sorted(terms, key=lambda term: (-len(term), term)))


def _term_weight(term: str) -> float:
    if term in _QUERY_STOP_TERMS:
        return 0
    if term in ("负责人", "验收人", "截止", "截止时间", "时间", "交付范围"):
        return 3.0
    return min(len(term), 8)


def _text_has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _normalize_relevance_text(value: str) -> str:
    return re.sub(r"\s+", "", value.casefold())
