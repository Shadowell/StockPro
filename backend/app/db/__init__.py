from app.core.config import settings
from app.db.local_db import db_instance


def get_database():
    if settings.DB_MODE.lower() in {"postgres", "local"}:
        return db_instance

    from supabase import create_client

    url: str = settings.SUPABASE_URL
    key: str = settings.SUPABASE_SERVICE_KEY if settings.SUPABASE_SERVICE_KEY else settings.SUPABASE_KEY
    return create_client(url, key)
