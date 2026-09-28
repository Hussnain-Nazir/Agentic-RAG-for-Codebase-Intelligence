from app.config import Settings, get_settings
from app.llm.openai_compatible import OpenAICompatibleProvider


def get_model_a(settings: Settings | None = None) -> OpenAICompatibleProvider:
    resolved = settings or get_settings()
    if (
        not resolved.model_a_name
        or not resolved.model_a_base_url
        or not resolved.model_a_api_key
    ):
        raise ValueError("Model A configuration is incomplete")
    return OpenAICompatibleProvider(
        name=resolved.model_a_name,
        base_url=resolved.model_a_base_url,
        api_key=resolved.model_a_api_key,
        timeout_s=resolved.model_a_timeout,
    )


def get_model_b(settings: Settings | None = None) -> OpenAICompatibleProvider:
    resolved = settings or get_settings()
    if (
        not resolved.model_b_name
        or not resolved.model_b_base_url
        or not resolved.model_b_api_key
    ):
        raise ValueError("Model B configuration is incomplete")
    return OpenAICompatibleProvider(
        name=resolved.model_b_name,
        base_url=resolved.model_b_base_url,
        api_key=resolved.model_b_api_key,
        timeout_s=resolved.model_b_timeout,
    )
