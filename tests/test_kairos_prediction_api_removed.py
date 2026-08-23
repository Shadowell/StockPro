from pathlib import Path
import sys

from fastapi import FastAPI


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.api.v2.endpoints.market import router  # noqa: E402
from app.services import kairos_predictor as kairos_module  # noqa: E402
from app.services import superpnl_model_inference_service as superpnl_module  # noqa: E402


def test_market_api_no_longer_exposes_kairos_prediction_routes_or_params() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/market")

    paths = app.openapi()["paths"]
    assert "/market/predictions/compare" not in paths

    kline_parameters = paths["/market/klines"]["get"]["parameters"]
    parameter_names = {item["name"] for item in kline_parameters}
    assert "predict" not in parameter_names
    assert "predict_steps" not in parameter_names


def test_market_frontend_no_longer_calls_or_shows_kairos_prediction() -> None:
    market_source = (ROOT / "frontend/src/pages/Market.tsx").read_text(encoding="utf-8")
    client_source = (ROOT / "frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert "getPredictionsCompare" not in client_source
    assert "getKlinesWithPrediction" not in client_source
    assert "/market/predictions/compare" not in client_source
    assert "showPrediction" not in market_source
    assert "AI 预测" not in market_source


def test_superpnl_inference_interface_is_disabled_without_loading_model(monkeypatch) -> None:
    service = superpnl_module.SuperPnLModelInferenceService()

    def fail_if_model_load_is_attempted(*_args, **_kwargs) -> None:
        raise AssertionError("disabled SuperPnL inference must not load a model")

    monkeypatch.setattr(service, "_load_model_package", fail_if_model_load_is_attempted)

    import asyncio

    asyncio.run(service.initialize())
    signals = asyncio.run(service.predict_timestamp(1_800_000_000_000))

    assert service.is_ready is False
    assert service.last_error == superpnl_module.SUPERPNL_INFERENCE_DISABLED_MESSAGE
    assert signals == {}


def test_kairos_inference_is_disabled_without_loading_model(monkeypatch) -> None:
    predictor = kairos_module.KairosPredictor()

    async def fail_if_threaded_model_load_is_attempted(*_args, **_kwargs) -> None:
        raise AssertionError("disabled Kairos inference must not start a model-loading thread")

    monkeypatch.setattr(kairos_module.asyncio, "to_thread", fail_if_threaded_model_load_is_attempted)

    import asyncio

    try:
        asyncio.run(predictor.load_model())
    except RuntimeError as exc:
        assert str(exc) == kairos_module.KAIROS_INFERENCE_DISABLED_MESSAGE
    else:
        raise AssertionError("disabled Kairos inference must fail closed")

    try:
        asyncio.run(predictor.predict_trajectory([]))
    except RuntimeError as exc:
        assert str(exc) == kairos_module.KAIROS_INFERENCE_DISABLED_MESSAGE
    else:
        raise AssertionError("disabled Kairos prediction must fail closed")

    assert predictor.is_loaded is False
    assert predictor._load_error == kairos_module.KAIROS_INFERENCE_DISABLED_MESSAGE
