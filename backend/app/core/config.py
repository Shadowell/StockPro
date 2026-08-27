"""
BitPro 配置管理
"""
from typing import Annotated, List, Optional
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from pydantic import field_validator
import json
from pathlib import Path


class Settings(BaseSettings):
    """应用配置"""
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[2] / ".env"),
        case_sensitive=True,
        extra="ignore",
    )

    # API 配置
    PROJECT_NAME: str = "StockPro"

    # CORS 配置
    BACKEND_CORS_ORIGINS: Annotated[List[str], NoDecode] = ["http://localhost:4444", "http://127.0.0.1:4444"]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v):
        if isinstance(v, str):
            if v.startswith("["):
                return json.loads(v)
            return [i.strip() for i in v.split(",")]
        return v

    # 数据库配置
    DB_PATH: Optional[str] = None
    DATABASE_URL: str

    @field_validator("DATABASE_URL")
    @classmethod
    def postgres_only(cls, value: str) -> str:
        if not value.startswith(("postgresql://", "postgresql+psycopg://")):
            raise ValueError("StockPro requires PostgreSQL")
        return value

    # 日志配置
    LOG_LEVEL: str = "INFO"

    # A 股证券主数据与每日行情同步
    TUSHARE_TOKEN: Optional[str] = None
    A_SHARE_DAILY_SYNC_ENABLED: bool = False
    A_SHARE_DAILY_SYNC_HOUR: int = 18
    A_SHARE_DAILY_SYNC_MINUTE: int = 10
    A_SHARE_DAILY_SYNC_TIMEZONE: str = "Asia/Shanghai"
    AKSHARE_TIMEOUT: int = 30
    CONCEPT_MEMBERSHIP_SYNC_ENABLED: bool = True

    # 交易所配置 - OKX
    OKX_API_KEY: Optional[str] = None
    OKX_API_SECRET: Optional[str] = None
    OKX_PASSPHRASE: Optional[str] = None
    OKX_TESTNET: bool = True

    # 交易所配置 - Binance USD-M（首版用于跨所套利研究与账户展示）
    BINANCE_API_KEY: Optional[str] = None
    BINANCE_API_SECRET: Optional[str] = None
    BINANCE_TESTNET: bool = False

    # AI Agent 配置
    DASHSCOPE_API_KEY: Optional[str] = None
    QWEN_API_KEY: Optional[str] = None
    XAI_API_KEY: Optional[str] = None
    AI_AGENT_MODEL: str = "qwen3.6-plus"
    QWEN_MODEL: str = "qwen3.6-plus"
    QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    AI_AGENT_ENABLE_THINKING: bool = False
    AI_AGENT_THINKING_BUDGET: int = 512
    AI_AGENT_REQUEST_TIMEOUT: int = 180
    AGENT_MAX_ITERATIONS: int = 10
    AGENT_CODE_TIMEOUT: int = 120
    HERMES_AGENT_ENABLED: bool = False
    HERMES_AGENT_COMMAND: str = "hermes"
    HERMES_AGENT_TIMEOUT: int = 240

    # 飞书 Webhook 推送
    FEISHU_WEBHOOK_URL: Optional[str] = None
    ENABLE_FEISHU_NOTIFY: bool = False
    FEISHU_APP_ID: Optional[str] = None
    FEISHU_APP_SECRET: Optional[str] = None
    FEISHU_PROFIT_CARD_IMAGE_ENABLED: bool = True

    # 登录与临时邀请码访问控制
    BITPRO_AUTH_ENABLED: bool = False
    BITPRO_ADMIN_USERNAME: Optional[str] = None
    BITPRO_ADMIN_PASSWORD_HASH: Optional[str] = None
    BITPRO_AUTH_COOKIE_NAME: str = "bitpro_session"
    BITPRO_AUTH_COOKIE_SECURE: bool = False
    BITPRO_ADMIN_SESSION_HOURS: int = 24 * 365 * 10
    BITPRO_AUTH_TOKEN_SECRET: Optional[str] = None
    STOCKPRO_MCP_API_TOKEN: Optional[str] = None
    STOCKPRO_MCP_AUTH_HEADER: str = "X-StockPro-MCP-Token"
    BITPRO_MCP_API_TOKEN: Optional[str] = None
    BITPRO_MCP_AUTH_HEADER: str = "X-BitPro-MCP-Token"
    BITPRO_REMOTE_MCP_ENABLED: bool = False
    BITPRO_REMOTE_MCP_PATH: str = "/api/mcp"
    BITPRO_REMOTE_MCP_REQUIRE_TOKEN: bool = True

    # HyperTrade 研究机构服务（仅由 BitPro 服务端读取，绝不下发给浏览器）
    HYPERTRADE_API_BASE: Optional[str] = None
    # 完整 Cookie header，例如 `hypertrade_session=...`；不得写入数据库、日志或 API 响应。
    HYPERTRADE_ADMIN_SESSION_COOKIE: Optional[str] = None
    HYPERTRADE_REQUEST_TIMEOUT_SEC: float = 20.0
    # ARC 控制台：服务令牌 + 审批签名。空 BASE_URL 时页面显示未配置，不得 500。
    HYPERTRADE_BASE_URL: Optional[str] = None
    HYPERTRADE_SERVICE_TOKEN: Optional[str] = None
    HYPERTRADE_APPROVAL_SIGNING_SECRET: Optional[str] = None

    # Redis 配置 (可选)
    REDIS_URL: Optional[str] = None

    # 数据同步间隔 (秒)
    SYNC_INTERVAL_TICKER: int = 10
    SYNC_INTERVAL_FUNDING: int = 60
    SYNC_INTERVAL_KLINE: int = 300

# 全局配置实例
settings = Settings()
