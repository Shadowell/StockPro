from unittest.mock import patch

import pandas as pd

from app.api.endpoints import data as data_endpoint
from app.db import db_instance


def test_market_cache_stock_spot_falls_back_to_sina_when_eastmoney_fails():
    sina_frame = pd.DataFrame([
        {"代码": "bj920000", "名称": "安徽凤凰", "最新价": 11.85, "涨跌幅": 1.979, "成交量": 503089, "成交额": 5900445}
    ])

    with (
        patch.object(data_endpoint.ak, "stock_zh_a_spot_em", side_effect=RuntimeError("eastmoney blocked")),
        patch.object(data_endpoint.ak, "stock_zh_a_spot", return_value=sina_frame) as sina,
    ):
        frame = data_endpoint._stock_spot_frame_for_cache()

    assert frame is sina_frame
    sina.assert_called_once()


def test_stock_code_normalization_keeps_prefixed_beijing_market_codes():
    assert data_endpoint._normalize_code("bj920000") == "BJ_920000"
    assert data_endpoint._normalize_code("sh600000") == "SH_600000"
    assert data_endpoint._normalize_code("sz000001") == "SZ_000001"
    assert db_instance._normalize_stock_code("bj920000") == "BJ_920000"
    assert db_instance._normalize_stock_code("920000") == "BJ_920000"
