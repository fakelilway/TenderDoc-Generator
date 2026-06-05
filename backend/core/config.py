from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


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
        "https://api.deepseek.com/v1", alias="DEEPSEEK_BASE_URL"
    )
    deepseek_model: str = Field("deepseek-chat", alias="DEEPSEEK_MODEL")
    qianwen_api_key: str = Field("", alias="QIANWEN_API_KEY")
    openai_api_key: str = Field("", alias="OPENAI_API_KEY")
    openrouter_api_key: str = Field("", alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        "https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )
    openrouter_model: str = Field("deepseek/deepseek-chat", alias="OPENROUTER_MODEL")
    parser_llm_timeout_seconds: float = Field(
        45.0, alias="PARSER_LLM_TIMEOUT_SECONDS"
    )

    embedding_model: str = Field("BAAI/bge-large-zh-v1.5", alias="EMBEDDING_MODEL")
    embedding_device: str = Field("cpu", alias="EMBEDDING_DEVICE")
    embedding_dimension: int = Field(1024, alias="EMBEDDING_DIMENSION")
    rerank_model: str = Field("BAAI/bge-reranker-base", alias="RERANK_MODEL")

    company_name: str = Field("安徽正奇建设有限公司", alias="COMPANY_NAME")
    enable_llm_generation: bool = Field(False, alias="ENABLE_LLM_GENERATION")
    bid_template_path: str = Field(
        "templates/bid_templates/road_first_envelope_template.json",
        alias="BID_TEMPLATE_PATH",
    )

    debug: bool = Field(True, alias="DEBUG")
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    jwt_secret: str = Field("your-secret-key", alias="JWT_SECRET")
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


settings = get_settings()
