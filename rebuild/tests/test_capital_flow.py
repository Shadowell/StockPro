from app.domain.orderflow.capital_flow import CapitalFlowService, normalize_hsgt_row, normalize_moneyflow_row


def test_normalize_hsgt_skips_nan_and_converts_wan_to_cny():
    assert normalize_hsgt_row({"trade_date": "20260821", "north_money": float("nan")}) is None
    row = normalize_hsgt_row({
        "trade_date": "20260821",
        "north_money": 351740.65,
        "south_money": 54787.49,
        "hgt": 160045.33,
        "sgt": 191695.32,
    })
    assert row is not None
    assert row["trade_date"] == "2026-08-21"
    assert row["north_money_cny"] == 3_517_406_500.0
    assert row["source"] == "tushare.moneyflow_hsgt"


def test_normalize_moneyflow_uses_main_force_amounts():
    row = normalize_moneyflow_row({
        "trade_date": "20260821",
        "buy_lg_amount": 115631.64,
        "buy_elg_amount": 102874.23,
        "sell_lg_amount": 131726.85,
        "sell_elg_amount": 144684.63,
        "net_mf_amount": -93474.78,
    }, "600519.SH")
    assert row is not None
    assert row["net_amount_cny"] == -934_747_800.0
    assert row["main_in_cny"] == 2_185_058_700.0


def test_capital_flow_service_uses_injected_client():
    class FakeFrame:
        def __init__(self, rows):
            self._rows = rows

        def to_dict(self, orient="records"):
            return self._rows

    class FakeClient:
        def moneyflow_hsgt(self, start_date, end_date):
            return FakeFrame([{"trade_date": "20260821", "north_money": 10, "hgt": 4, "sgt": 6, "south_money": 1}])

        def moneyflow(self, ts_code, start_date, end_date):
            return FakeFrame([{"trade_date": "20260821", "net_mf_amount": -3, "buy_lg_amount": 1, "buy_elg_amount": 2, "sell_lg_amount": 3, "sell_elg_amount": 4}])

    payload = CapitalFlowService(client_factory=FakeClient).summary("600519.SH", days=10)
    assert payload["status"] == "ready"
    assert payload["latest"]["north_money_cny"] == 100_000.0
    assert payload["stock_flow"][0]["symbol"] == "600519.SH"
    assert payload["writes_performed"] is False
