from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def block_between(source: str, start: str, end: str) -> str:
    start_idx = source.index(start)
    end_idx = source.index(end, start_idx)
    return source[start_idx:end_idx]


def test_sync_assets_uses_metadata_stats_cache_instead_of_file_store_scan() -> None:
    endpoint = read_text("backend/app/api/v2/endpoints/sync.py")
    service = read_text("backend/app/domain/sync/service.py")

    endpoint_block = block_between(endpoint, '@router.get("/assets")', '@router.post("/start")')
    service_block = block_between(service, "    def assets(self)", "    def is_running(self)")

    assert "sync_domain_service.assets()" in endpoint_block
    assert "kline_store.get_stats" not in endpoint_block
    assert "db.get_all_sync_metadata" not in endpoint_block
    assert "self.table_stats()" in service_block
    assert "kline_store.get_stats" not in service_block
    assert "first_timestamp" in service_block
    assert "last_timestamp" in service_block


def test_orbit_login_status_uses_short_ttl_cache() -> None:
    service = read_text("backend/app/services/orbit_auto_post_service.py")
    login_block = block_between(service, "    async def login_status(self)", "    async def preview_candidates")

    assert "LOGIN_STATUS_CACHE_TTL_SEC = 20.0" in service
    assert "self._login_status_cache" in service
    assert "time.monotonic()" in login_block
    assert "await self.publisher.status()" in login_block
    assert '"cached": True' in login_block
