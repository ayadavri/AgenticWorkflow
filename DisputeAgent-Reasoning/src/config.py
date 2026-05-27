from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Reasoning models (gpt-5, o-series) bill completion tokens for internal reasoning;
# 1000 is too low and yields empty/unparseable structured output.
REASONING_MODEL_MIN_COMPLETION_TOKENS = 8192


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    analysis_model: str = ""
    analysis_model_temperature: float = 0.0
    analysis_model_max_tokens: int = 16384
    analysis_model_api_key_ssm_parameter: str = ""

    judgment_model: str = ""
    judgment_model_max_tokens: int = 16384
    judgment_model_temperature: float = 0.0
    judgment_model_api_key_ssm_parameter: str = ""

    # --- AWS S3 (dispute PDF storage) ---
    aws_region: str = "us-east-1"
    aws_dynamodb_table: str = ""
    aws_dynamodb_endpoint_url: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # --- DynamoDB (dispute row updates after workflow) ---
    dynamo_db_max_retry: int = 5
    connect_timeout: int = 5
    read_timeout: int = 60
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0
    supported_document_extensions: list[str] = Field(default_factory=list)

    # --- Resident Interface (case documents API) ---
    ri_core_base_url: str = ""
    ri_core_api_key: str = ""
    ri_core_http_timeout_s: float = 30.0

    #S3 Bucket for configuration details
    config_s3_bucket: str = "case-dispute-analysis"
    config_s3_prefix: str = "configuration/"
    config_json_files: list[str] = ["originatorDisputeCode1.json", "originatorDisputeCode2.json"]
    source_list: list[str] = ["eoscar"]
    enableAIReview: bool = False
    case_dispute_analysis_s3_bucket: str = "case-dispute-analysis"
    case_dispute_analysis_s3_prefix: str = "input/"
    encryption_key_ssm_parameter: str = "/agents/ENCRYPTION_KEY"
    collection_core_documents_api_ssm_parameter: str = "/agents/COLLECTION_CORE_DOCUMENTS_API_KEY"
    aws_region: str = "us-east-1"
    #Set the value to true to enable the AI confidence check along against the threshold value
    confidence_check_enabled: bool = False
    ai_confidence_level_threshold: int = 0

def _normalize_openai_model(model: str) -> str:
    return (model or "").strip().lower()


def is_openai_reasoning_style_model(model: str) -> bool:
    """
    Models that use ``max_completion_tokens`` and restrict sampling params.

    Includes o-series, gpt-5.x, chatgpt-5, and gpt-4.1 families.
    """
    normalized = _normalize_openai_model(model)
    return normalized.startswith(
        ("o1", "o2", "o3", "o4", "gpt-5", "chatgpt-5", "gpt-4.1")
    )


def effective_max_completion_tokens(model: str, max_tokens: int) -> int:
    """Apply a floor for reasoning models so structured output is not truncated."""
    limit = int(max_tokens)
    if is_openai_reasoning_style_model(model):
        return max(limit, REASONING_MODEL_MIN_COMPLETION_TOKENS)
    return limit


def openai_chat_token_limit_kwargs(model: str, max_tokens: int) -> dict[str, int]:
    """
    Return the token limit parameter supported by the target OpenAI chat model.

    Newer models (o-series, gpt-5, gpt-4.1, etc.) require ``max_completion_tokens``
    instead of ``max_tokens``.
    """
    limit = effective_max_completion_tokens(model, max_tokens)
    if is_openai_reasoning_style_model(model):
        return {"max_completion_tokens": limit}
    return {"max_tokens": limit}


def openai_chat_request_kwargs(
    model: str,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """
    Build optional chat completion kwargs safe for the target model.

    For gpt-5 / o-series models:
    - Uses ``max_completion_tokens`` instead of ``max_tokens``.
    - Omits ``temperature`` unless it is ``1.0`` (API default); values like ``0.0``
      are rejected with ``unsupported_value``.
    """
    kwargs: dict[str, Any] = {}
    if max_tokens is not None:
        kwargs.update(openai_chat_token_limit_kwargs(model, int(max_tokens)))

    if temperature is None:
        return kwargs

    temp = float(temperature)
    if is_openai_reasoning_style_model(model):
        if temp == 1.0:
            kwargs["temperature"] = temp
        # else: omit — model only supports the default (1)
    else:
        kwargs["temperature"] = temp

    return kwargs


def get_settings() -> Settings:
    return Settings()
