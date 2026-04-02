import json
from typing import List, Union
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Stock Analysis App"
    
    # CORS
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and v.startswith("["):
            return json.loads(v)
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    SUPABASE_SERVICE_KEY: str = ""

    # AI
    QWEN_API_KEY: str = ""
    QWEN_STOCK_MODEL: str = "qwen-plus"
    
    # Akshare
    AKSHARE_TIMEOUT: int = 30

    # Runtime feature toggles
    ENABLE_SCHEDULER: bool = True
    ENABLE_REALTIME_SYNC: bool = True
    ENABLE_STRATEGY_EXECUTION: bool = True
    ENABLE_EXTERNAL_MARKET_FETCH: bool = True

    # Operation allowlist
    ENFORCE_OPERATION_ALLOWLIST: bool = False
    OPERATION_ALLOWLIST: List[str] = []

    @field_validator("OPERATION_ALLOWLIST", mode="before")
    def assemble_operation_allowlist(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and v.startswith("["):
            return json.loads(v)
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)
    
    # Database mode: 'supabase' or 'local'
    DB_MODE: str = "local"  # 默认使用本地数据库
    LOCAL_DB_PATH: Union[str, None] = None  # 本地数据库路径，如果为None则使用默认路径
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        enable_decoding=False,
        extra="ignore"
    )

settings = Settings()
