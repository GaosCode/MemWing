from __future__ import annotations

import asyncio
from dataclasses import dataclass

from memwing.core.errors import (
    ConfigurationFailure,
    DomainRuleViolation,
    FailureCategory,
    LockOwnershipFailure,
    MemWingFailure,
    ProviderPermanentFailure,
    ProviderTransientFailure,
    ScopeResolutionFailure,
    ValidationFailure,
)


@dataclass(frozen=True, slots=True)
class FailureClassification:
    category: FailureCategory
    reason_code: str
    safe_message: str
    retryable: bool
    dead_letter: bool
    audit_stage: str
    http_status: int


def classify_failure(exc: BaseException, *, audit_stage: str) -> FailureClassification:
    if isinstance(exc, asyncio.TimeoutError):
        return FailureClassification(
            category=FailureCategory.PROVIDER_TRANSIENT,
            reason_code="provider_timeout",
            safe_message="Provider request timed out.",
            retryable=True,
            dead_letter=False,
            audit_stage=audit_stage,
            http_status=503,
        )
    if isinstance(exc, ProviderTransientFailure):
        return _known_failure(
            category=FailureCategory.PROVIDER_TRANSIENT,
            exc=exc,
            retryable=True,
            dead_letter=False,
            audit_stage=audit_stage,
            http_status=503,
        )
    if isinstance(exc, ProviderPermanentFailure):
        return _known_failure(
            category=FailureCategory.PROVIDER_PERMANENT,
            exc=exc,
            retryable=False,
            dead_letter=True,
            audit_stage=audit_stage,
            http_status=502,
        )
    if isinstance(exc, ScopeResolutionFailure):
        return _known_failure(
            category=FailureCategory.SCOPE_RESOLUTION,
            exc=exc,
            retryable=False,
            dead_letter=True,
            audit_stage=audit_stage,
            http_status=404,
        )
    if isinstance(exc, LockOwnershipFailure) or exc.__class__.__name__.endswith("LockOwnershipError"):
        return FailureClassification(
            category=FailureCategory.LOCK_OWNERSHIP,
            reason_code="lock_ownership_lost",
            safe_message="The job lock is no longer owned by this worker.",
            retryable=False,
            dead_letter=False,
            audit_stage=audit_stage,
            http_status=409,
        )
    if isinstance(exc, ConfigurationFailure):
        return _known_failure(
            category=FailureCategory.CONFIGURATION,
            exc=exc,
            retryable=False,
            dead_letter=True,
            audit_stage=audit_stage,
            http_status=500,
        )
    if isinstance(exc, ValidationFailure):
        return _known_failure(
            category=FailureCategory.VALIDATION,
            exc=exc,
            retryable=False,
            dead_letter=True,
            audit_stage=audit_stage,
            http_status=400,
        )
    if isinstance(exc, DomainRuleViolation):
        return FailureClassification(
            category=FailureCategory.DOMAIN_RULE,
            reason_code="domain_rule_violation",
            safe_message="The requested operation violates a domain rule.",
            retryable=False,
            dead_letter=True,
            audit_stage=audit_stage,
            http_status=409,
        )
    return FailureClassification(
        category=FailureCategory.UNEXPECTED,
        reason_code="unexpected_failure",
        safe_message="The operation failed unexpectedly.",
        retryable=False,
        dead_letter=True,
        audit_stage=audit_stage,
        http_status=500,
    )


def _known_failure(
    *,
    category: FailureCategory,
    exc: MemWingFailure,
    retryable: bool,
    dead_letter: bool,
    audit_stage: str,
    http_status: int,
) -> FailureClassification:
    return FailureClassification(
        category=category,
        reason_code=exc.reason_code,
        safe_message=exc.safe_message,
        retryable=retryable,
        dead_letter=dead_letter,
        audit_stage=audit_stage,
        http_status=http_status,
    )
