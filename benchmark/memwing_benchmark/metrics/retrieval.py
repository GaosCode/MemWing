from __future__ import annotations

import re
from typing import Literal


EvidenceMatch = Literal["all", "any"]

BRACKET_EVIDENCE_RE = re.compile(r"\[(?:MSG|MEM):([A-Za-z0-9_-]+)\]")
CHINESE_EVIDENCE_RE = re.compile(r"证据编号[:：]\s*([A-Za-z0-9_-]+)")


def unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def extract_evidence_ids(text: str) -> list[str]:
    matches = BRACKET_EVIDENCE_RE.findall(text)
    matches.extend(CHINESE_EVIDENCE_RE.findall(text))
    return unique_preserve_order(matches)


def evidence_correct(
    gold_evidence_ids: list[str], retrieved_evidence_ids: list[str], *, match: EvidenceMatch = "all"
) -> bool | None:
    if not gold_evidence_ids:
        return None
    gold = set(gold_evidence_ids)
    retrieved = set(retrieved_evidence_ids)
    if match == "any":
        return bool(gold & retrieved)
    return gold.issubset(retrieved)


def recall_at_k(
    gold_evidence_ids: list[str],
    retrieved_evidence_ids: list[str],
    k: int,
    *,
    match: EvidenceMatch = "all",
) -> bool | None:
    if not gold_evidence_ids:
        return None
    return evidence_correct(gold_evidence_ids, retrieved_evidence_ids[:k], match=match)
