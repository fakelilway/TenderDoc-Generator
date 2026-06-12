import logging
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]

DEFAULT_JWT_SECRET = "your-secret-key"

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = Field(..., alias="DATABASE_URL")
    postgres_host: str = Field(..., alias="POSTGRES_HOST")
    postgres_port: int = Field(..., alias="POSTGRES_PORT")
    postgres_db: str = Field(..., alias="POSTGRES_DB")
    postgres_user: str = Field(..., alias="POSTGRES_USER")
    postgres_password: str = Field(..., alias="POSTGRES_PASSWORD")

    redis_url: str = Field(..., alias="REDIS_URL")
    redis_host: str = Field(..., alias="REDIS_HOST")
    redis_port: int = Field(..., alias="REDIS_PORT")
    redis_password: str = Field("", alias="REDIS_PASSWORD")

    minio_root_user: str = Field(..., alias="MINIO_ROOT_USER")
    minio_root_password: str = Field(..., alias="MINIO_ROOT_PASSWORD")
    minio_api_url: str = Field(..., alias="MINIO_API_URL")
    minio_console_url: str = Field(..., alias="MINIO_CONSOLE_URL")
    minio_bucket: str = Field(..., alias="MINIO_BUCKET")

    deepseek_api_key: str = Field("", alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(
        "https://api.deepseek.com", alias="DEEPSEEK_BASE_URL"
    )
    deepseek_model: str = Field("deepseek-v4-pro", alias="DEEPSEEK_MODEL")
    qianwen_api_key: str = Field("", alias="QIANWEN_API_KEY")
    openai_api_key: str = Field("", alias="OPENAI_API_KEY")
    openrouter_api_key: str = Field("", alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        "https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )
    openrouter_model: str = Field("deepseek/deepseek-v4-pro", alias="OPENROUTER_MODEL")
    parser_llm_timeout_seconds: float = Field(180.0, alias="PARSER_LLM_TIMEOUT_SECONDS")
    bid_llm_provider: str = Field("auto", alias="BID_LLM_PROVIDER")
    bid_generation_mode: str = Field("long_context", alias="BID_GENERATION_MODE")
    # 长上下文生成跑在后台线程里，不会阻塞 API；超时给足，质量优先。
    # 6000 tokens 装不下三卷标书，且 60s 等不到非流式长输出返回——
    # 生成失败时直接报错，由用户修正配置/输入后重试。
    bid_long_context_timeout_seconds: float = Field(
        300.0, alias="BID_LONG_CONTEXT_TIMEOUT_SECONDS"
    )
    bid_long_context_max_tokens: int = Field(100000, alias="BID_LONG_CONTEXT_MAX_TOKENS")

    embedding_model: str = Field("BAAI/bge-large-zh-v1.5", alias="EMBEDDING_MODEL")
    embedding_device: str = Field("cpu", alias="EMBEDDING_DEVICE")
    embedding_dimension: int = Field(1024, alias="EMBEDDING_DIMENSION")
    rerank_model: str = Field("BAAI/bge-reranker-base", alias="RERANK_MODEL")

    company_name: str = Field("安徽正奇建设有限公司", alias="COMPANY_NAME")
    enable_llm_generation: bool = Field(True, alias="ENABLE_LLM_GENERATION")
    bid_template_path: str = Field("", alias="BID_TEMPLATE_PATH")

    debug: bool = Field(False, alias="DEBUG")
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    jwt_secret: str = Field(DEFAULT_JWT_SECRET, alias="JWT_SECRET")
    jwt_algorithm: str = Field("HS256", alias="JWT_ALGORITHM")
    jwt_expires_minutes: int = Field(720, alias="JWT_EXPIRES_MINUTES")
    default_admin_username: str = Field("admin", alias="DEFAULT_ADMIN_USERNAME")
    default_admin_password: str = Field("tenderdoc", alias="DEFAULT_ADMIN_PASSWORD")
    default_admin_display_name: str = Field("管理员", alias="DEFAULT_ADMIN_DISPLAY_NAME")
    temp_dir: str = Field("./temp", alias="TEMP_DIR")
    max_file_size: int = Field(50, alias="MAX_FILE_SIZE")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_security_settings(current: Settings) -> None:
    """Refuse to run with the default JWT secret outside debug mode.

    Call at application startup: raises ``RuntimeError`` when the JWT secret
    is still the hardcoded default and debug is off; logs a prominent warning
    when debug is on.
    """
    if current.jwt_secret != DEFAULT_JWT_SECRET:
        return
    if not current.debug:
        raise RuntimeError(
            "JWT_SECRET is still set to the insecure built-in default. "
            "Set a strong, random JWT_SECRET before running with DEBUG=false."
        )
    logger.warning(
        "SECURITY WARNING: JWT_SECRET is the insecure built-in default; "
        "tokens can be forged by anyone who reads the source. "
        "Set JWT_SECRET before deploying."
    )


settings = get_settings()
