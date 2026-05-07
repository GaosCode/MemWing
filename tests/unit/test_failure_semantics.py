import asyncio

from memwing.application.failure_semantics import classify_failure
from memwing.core.errors import (
    ConfigurationFailure,
    DomainRuleViolation,
    FailureCategory,
    ProviderPermanentFailure,
    ScopeResolutionFailure,
)
from memwing.infrastructure.platforms.feishu_openapi import FeishuOpenApiError
from memwing.infrastructure.llm.errors import LLMOutputSchemaError, LLMProviderError


def test_failure_semantics_classifies_provider_timeout_as_retryable_transient() -> None:
    failure = classify_failure(asyncio.TimeoutError(), audit_stage="graph_write.ingest")

    assert failure.category is FailureCategory.PROVIDER_TRANSIENT
    assert failure.reason_code == "provider_timeout"
    assert failure.retryable is True
    assert failure.dead_letter is False
    assert failure.audit_stage == "graph_write.ingest"
    assert failure.http_status == 503


def test_failure_semantics_classifies_known_permanent_failures_without_raw_leakage() -> None:
    failure = classify_failure(
        ProviderPermanentFailure(
            reason_code="model_output_invalid",
            safe_message="Provider returned invalid structured output.",
        ),
        audit_stage="long_term_filter.parse",
    )

    assert failure.category is FailureCategory.PROVIDER_PERMANENT
    assert failure.reason_code == "model_output_invalid"
    assert failure.safe_message == "Provider returned invalid structured output."
    assert failure.retryable is False
    assert failure.dead_letter is True
    assert failure.http_status == 502


def test_llm_adapter_errors_are_classified_before_crossing_application_boundaries() -> None:
    provider = classify_failure(
        LLMProviderError("provider raw timeout text"),
        audit_stage="llm.complete",
    )
    bad_json = classify_failure(
        LLMOutputSchemaError("raw model json must not leak"),
        audit_stage="llm.parse",
    )

    assert provider.category is FailureCategory.PROVIDER_TRANSIENT
    assert provider.reason_code == "llm_provider_error"
    assert provider.retryable is True
    assert "provider raw timeout text" not in provider.safe_message
    assert bad_json.category is FailureCategory.PROVIDER_PERMANENT
    assert bad_json.reason_code == "llm_output_schema_invalid"
    assert bad_json.dead_letter is True
    assert "raw model json" not in bad_json.safe_message


def test_feishu_openapi_error_preserves_provider_diagnostics() -> None:
    failure = classify_failure(
        FeishuOpenApiError("Feishu send interactive message failed: code 999; msg=no permission; log_id=log_001"),
        audit_stage="outbox.handler",
    )

    assert failure.category is FailureCategory.PROVIDER_TRANSIENT
    assert failure.reason_code == "feishu_openapi_error"
    assert failure.safe_message == (
        "Feishu send interactive message failed: code 999; msg=no permission; log_id=log_001"
    )


def test_failure_semantics_maps_scope_domain_configuration_and_unexpected() -> None:
    cases = (
        (
            ScopeResolutionFailure("scope_not_found", "Memory scope is not available."),
            FailureCategory.SCOPE_RESOLUTION,
            "scope_not_found",
            404,
            False,
            True,
        ),
        (
            DomainRuleViolation("invalid lifecycle transition"),
            FailureCategory.DOMAIN_RULE,
            "domain_rule_violation",
            409,
            False,
            True,
        ),
        (
            ConfigurationFailure("provider_config_missing", "Provider is not configured."),
            FailureCategory.CONFIGURATION,
            "provider_config_missing",
            500,
            False,
            True,
        ),
        (
            RuntimeError("raw source event content must not leak"),
            FailureCategory.UNEXPECTED,
            "unexpected_failure",
            500,
            False,
            True,
        ),
    )

    for exc, category, reason_code, http_status, retryable, dead_letter in cases:
        failure = classify_failure(exc, audit_stage="recall.current")

        assert failure.category is category
        assert failure.reason_code == reason_code
        assert failure.http_status == http_status
        assert failure.retryable is retryable
        assert failure.dead_letter is dead_letter
        assert "raw source event content" not in failure.safe_message
