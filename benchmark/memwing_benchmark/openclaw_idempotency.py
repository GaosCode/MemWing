from __future__ import annotations

from hashlib import sha1


def make_idempotency_key(*, run_id: str, backend: str, case_id: str, item_id: str) -> str:
    raw = f"{run_id}:{backend}:{case_id}:{item_id}"
    digest = sha1(raw.encode("utf-8")).hexdigest()[:10]
    trace = _safe_key_part(f"{case_id}-{item_id}")
    key = f"mwb-{trace}-{digest}"
    if len(key) <= 50:
        return key
    prefix_budget = 50 - len("mwb--") - len(digest)
    return f"mwb-{trace[:prefix_budget].rstrip('-')}-{digest}"

def _safe_key_part(value: str) -> str:
    out = []
    previous_dash = False
    for char in value.lower():
        safe = char if char.isalnum() else "-"
        if safe == "-":
            if previous_dash:
                continue
            previous_dash = True
        else:
            previous_dash = False
        out.append(safe)
    return "".join(out).strip("-") or "item"
