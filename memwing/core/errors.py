from __future__ import annotations

from enum import StrEnum


class FailureCategory(StrEnum):
    VALIDATION = "validation"
    SCOPE_RESOLUTION = "scope_resolution"
    DOMAIN_RULE = "domain_rule"
    PROVIDER_TRANSIENT = "provider_transient"
    PROVIDER_PERMANENT = "provider_permanent"
    LOCK_OWNERSHIP = "lock_ownership"
    CONFIGURATION = "configuration"
    UNEXPECTED = "unexpected"


class MemWingFailure(RuntimeError):
    def __init__(self, reason_code: str, safe_message: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.safe_message = safe_message


class ValidationFailure(MemWingFailure):
    pass


class ScopeResolutionFailure(MemWingFailure):
    pass


class ProviderTransientFailure(MemWingFailure):
    pass


class ProviderPermanentFailure(MemWingFailure):
    pass


class LockOwnershipFailure(MemWingFailure):
    pass


class ConfigurationFailure(MemWingFailure):
    pass


class DomainRuleViolation(ValueError):
    """Raised when a domain invariant would be violated."""
