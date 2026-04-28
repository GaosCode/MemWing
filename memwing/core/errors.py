from __future__ import annotations


class DomainRuleViolation(ValueError):
    """Raised when a domain invariant would be violated."""
