from app.domain.paper.repository import PaperRepository


def test_market_watch_helpers_canonicalize_realtime_codes() -> None:
    assert PaperRepository._canonical_symbol("SZ_000001") == "000001.SZ"
    assert PaperRepository._storage_symbol("600519.SH") == "SH_600519"
    assert PaperRepository._canonical_symbol("600519.SH") == "600519.SH"
