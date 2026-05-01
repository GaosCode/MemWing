from memwing.core.errors import ProviderPermanentFailure, ProviderTransientFailure


class LLMAdapterError(RuntimeError):
    pass


class LLMProviderError(ProviderTransientFailure, LLMAdapterError):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(
            reason_code="llm_provider_error",
            safe_message="LLM provider request failed.",
        )

    def __str__(self) -> str:
        return self.message


class LLMOutputSchemaError(ProviderPermanentFailure, LLMAdapterError):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(
            reason_code="llm_output_schema_invalid",
            safe_message="LLM output did not match the required schema.",
        )

    def __str__(self) -> str:
        return self.message
