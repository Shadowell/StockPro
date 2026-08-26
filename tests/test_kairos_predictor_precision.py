import math
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.kairos_predictor import KairosPredictor


def test_low_price_prediction_floor_is_relative_not_fixed_tick():
    predictor = KairosPredictor()
    pepe_close = 0.0000041254125

    assert predictor._minimum_predicted_price(pepe_close) == pytest.approx(pepe_close * 1e-4)
    assert predictor._minimum_predicted_price(pepe_close) < 0.0001


def test_low_price_prediction_serialization_preserves_precision():
    predictor = KairosPredictor()
    low_price = 0.000004123456789

    serialized = predictor._serialize_price(low_price)

    assert serialized == pytest.approx(low_price)
    assert serialized > 0
    assert serialized < 0.0001


def test_low_price_exogenous_returns_use_real_price_denominator():
    bars = [
        {
            "timestamp": 1_800_000_000_000,
            "open": 0.00000400,
            "high": 0.00000408,
            "low": 0.00000398,
            "close": 0.00000400,
            "volume": 1_000_000.0,
        },
        {
            "timestamp": 1_800_000_060_000,
            "open": 0.00000400,
            "high": 0.00000412,
            "low": 0.00000399,
            "close": 0.00000404,
            "volume": 1_100_000.0,
        },
    ]

    exog = KairosPredictor._build_exogenous_matrix(bars, 8)

    assert exog[1, 0] == pytest.approx(0.01, rel=1e-5)
    assert exog[1, 1] == pytest.approx(math.log(1.01), rel=1e-5)
    assert exog[1, 2] == pytest.approx((0.00000412 - 0.00000399) / 0.00000404, rel=1e-5)
