class LLMAdapterError(RuntimeError):
    pass


class LLMProviderError(LLMAdapterError):
    pass


class LLMOutputSchemaError(LLMAdapterError):
    pass
