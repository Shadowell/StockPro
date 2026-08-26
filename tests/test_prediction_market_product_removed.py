from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_w3w_prediction_product_is_not_exposed_by_bitpro():
    api_router = _read("backend/app/api/v2/api.py")
    live_page = _read("frontend/src/pages/liveTrading/index.tsx")
    client = _read("frontend/src/api/client.ts")

    assert "prediction_market" not in api_router
    assert 'prefix="/prediction-markets"' not in api_router
    assert "PredictionMarketPaper" not in live_page
    assert not (ROOT / "frontend/src/pages/liveTrading/LiveRealWorkspace.tsx").exists()
    assert not (ROOT / "frontend/src/pages/liveTrading/PredictionMarketLiveExecution.tsx").exists()
    assert not (ROOT / "frontend/src/pages/liveTrading/PredictionMarketPaper.tsx").exists()
    assert "prediction-markets" not in client
