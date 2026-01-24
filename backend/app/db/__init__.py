from app.core.config import settings
from app.db.local_db import db_instance

# 根据配置决定使用哪种数据库
if settings.DB_MODE == "local":
    # 使用本地SQLite数据库
    local_db = db_instance
else:
    # 使用Supabase（保留原有逻辑）
    from supabase import create_client, Client
    
    def get_supabase_client() -> Client:
        url: str = settings.SUPABASE_URL
        key: str = settings.SUPABASE_SERVICE_KEY if settings.SUPABASE_SERVICE_KEY else settings.SUPABASE_KEY
        return create_client(url, key)
    
    supabase: Client = get_supabase_client()

# 提供统一的数据库访问接口
def get_database():
    if settings.DB_MODE == "local":
        return local_db
    else:
        return supabase
