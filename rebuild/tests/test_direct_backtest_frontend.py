from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_bitpro_backtest_workbench_uses_a_share_history_semantics():
    page = (ROOT / "frontend/src/pages/Backtest.tsx").read_text(encoding="utf-8")
    support = (ROOT / "frontend/src/pages/backtest/backtestSupport.tsx").read_text(encoding="utf-8")

    assert "const canCreateBacktest = isAdmin" in page
    assert "const canBatchBacktest = false" in page
    assert "backtestApi.getConfiguration()" in page
    assert "dataset_snapshot_id: sealedConfiguration.datasetSnapshotId" in page
    assert "pool_snapshot_id: sealedConfiguration.poolSnapshotId" in page
    assert "BACKTEST_BENCHMARK_SYMBOL = '000300.SH'" in support
    assert "{ value: 'stock', label: '股票' }" in support
    assert "初始资金 (CNY)" in page
    assert "买入佣金 (bps，最低 5 元)" in page
    assert "卖出印花税" in page
    assert "BTC/USDT 同区间" not in page
