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

    minio_root_user: str = Field(..., alias="MINIO_ROOT_USER")
    minio_root_password: str = Field(..., alias="MINIO_ROOT_PASSWORD")
    minio_api_url: str = Field(..., alias="MINIO_API_URL")
    minio_console_url: str = Field(..., alias="MINIO_CONSOLE_URL")
    minio_bucket: str = Field(..., alias="MINIO_BUCKET")
    # 浏览器实际访问 MinIO 的地址(用于生成"下载/预览"预签名链接)。
    # 局域网/容器部署时:后端在容器内用 minio_api_url(如 http://minio:9000)连接,
    # 但发给别人浏览器的下载链接必须指向服务器局域网 IP(如 http://192.168.1.50:9000),
    # 否则别台电脑的 localhost 指向它自己→下载失败。留空则回退用 minio_api_url。
    minio_public_url: str = Field("", alias="MINIO_PUBLIC_URL")

    deepseek_api_key: str = Field("", alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(
        "https://api.deepseek.com", alias="DEEPSEEK_BASE_URL"
    )
    deepseek_model: str = Field("deepseek-v4-pro", alias="DEEPSEEK_MODEL")
    volcano_api_key: str = Field("", alias="VOLCANO_API_KEY")
    volcano_base_url: str = Field(
        "https://ark.cn-beijing.volces.com/api/coding/v3", alias="VOLCANO_BASE_URL"
    )
    volcano_model: str = Field("glm-5.2", alias="VOLCANO_MODEL")
    # Kimi(月之暗面 Moonshot,OpenAI兼容)。2026-07-16 用户拍板:主力从 DeepSeek 换 Kimi K3
    kimi_api_key: str = Field("", alias="KIMI_API_KEY")
    kimi_base_url: str = Field("https://api.moonshot.cn/v1", alias="KIMI_BASE_URL")
    kimi_model: str = Field("kimi-k3", alias="KIMI_MODEL")
    openai_api_key: str = Field("", alias="OPENAI_API_KEY")
    openrouter_api_key: str = Field("", alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        "https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )
    openrouter_model: str = Field("deepseek/deepseek-v4-pro", alias="OPENROUTER_MODEL")
    parser_llm_timeout_seconds: float = Field(180.0, alias="PARSER_LLM_TIMEOUT_SECONDS")
    bid_llm_provider: str = Field("auto", alias="BID_LLM_PROVIDER")
    # 生成跑在后台线程里，不会阻塞 API；超时给足，质量优先。
    # 6000 tokens 装不下三卷标书，且 60s 等不到非流式长输出返回——
    # 生成失败时直接报错，由用户修正配置/输入后重试。
    bid_long_context_timeout_seconds: float = Field(
        1200.0, alias="BID_LONG_CONTEXT_TIMEOUT_SECONDS"
    )
    bid_long_context_max_tokens: int = Field(
        100000, alias="BID_LONG_CONTEXT_MAX_TOKENS"
    )
    # 技术卷各节正文 LLM 调用相互独立,用有界并发把 25 节从串行约 25 分钟降到
    # 约 5-6 分钟。上限保守取值以免触发 DeepSeek 限流;瞬时 429 由 llm_client 重试兜底。
    bid_writer_concurrency: int = Field(5, alias="BID_WRITER_CONCURRENCY")
    # 交卷前"招标覆盖校验"(评分点逐条响应/废标项实质规避)+ 定向补写的总开关。
    # 默认开;若某次因成本/时延或误判需临时停掉,设 ENABLE_COVERAGE_AUDIT=false 即整套跳过。
    enable_coverage_audit: bool = Field(True, alias="ENABLE_COVERAGE_AUDIT")
    # 废标项未规避是否"硬拦出标"(critical)。当前 False=告警模式(只提示不拦),因废标项里混有
    # "初步评审不通过/报价超限价"等规则类条款,任何标书都不会专门写段响应→会对每份标误拦锁死。
    # 待 P1 把废标项分类(实质响应类 vs 规则/约束类)后再设 True 切回硬拦,届时只拦真该拦的。
    coverage_audit_block_invalid: bool = Field(
        False, alias="COVERAGE_AUDIT_BLOCK_INVALID"
    )
    # 云端 PDF→可编辑Word(格式章复制最上层)。off=用现有 pdf2docx;foxit=用福昕国内云
    # (真·可编辑+保真),失败自动下沉 pdf2docx→整页图。转的是公开招标格式章。
    cloud_pdf_convert: str = Field("off", alias="CLOUD_PDF_CONVERT")
    foxit_cloud_client_id: str = Field("", alias="FOXIT_CLOUD_CLIENT_ID")
    foxit_cloud_secret: str = Field("", alias="FOXIT_CLOUD_SECRET")
    # Parser 只输出结构化 JSON,不需要很大的输出预算。严格供应商(如 OpenRouter)会校验
    # 输入token + max_tokens ≤ 模型上下文上限,超了直接 400(DeepSeek 宽容会自动裁剪、不报错)。
    # 故 parser 的 max_tokens 按输入长度动态算:min(下方期望, 上下文上限 - 估算输入 - 余量)。
    # 模型上下文不同时(如 OpenRouter 某模型 163840)可调 PARSER_CONTEXT_LIMIT_TOKENS。
    parser_max_output_tokens: int = Field(
        32000, alias="PARSER_MAX_OUTPUT_TOKENS"
    )
    parser_context_limit_tokens: int = Field(
        131072, alias="PARSER_CONTEXT_LIMIT_TOKENS"
    )

    embedding_model: str = Field("BAAI/bge-large-zh-v1.5", alias="EMBEDDING_MODEL")
    embedding_device: str = Field("cpu", alias="EMBEDDING_DEVICE")
    embedding_dimension: int = Field(1024, alias="EMBEDDING_DIMENSION")
    rerank_model: str = Field("BAAI/bge-reranker-base", alias="RERANK_MODEL")

    company_name: str = Field("安徽正奇建设有限公司", alias="COMPANY_NAME")

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
    if current.jwt_secret and current.jwt_secret != DEFAULT_JWT_SECRET:
        return
    if not current.debug:
        raise RuntimeError(
            "JWT_SECRET is empty or still the insecure built-in default. "
            "Set a strong, random JWT_SECRET before running with DEBUG=false."
        )
    logger.warning(
        "SECURITY WARNING: JWT_SECRET is the insecure built-in default; "
        "tokens can be forged by anyone who reads the source. "
        "Set JWT_SECRET before deploying."
    )


settings = get_settings()
