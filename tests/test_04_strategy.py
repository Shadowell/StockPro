"""
模块4: 策略 & 回测 & 资金费率 测试
"""
import pytest


class TestStrategy:
    """策略模块"""

    @pytest.mark.strategy
    def test_strategy_list(self, client):
        """获取策略列表"""
        r = client.get("/strategy/list")
        assert r.status_code == 200
        data = r.json()
        # 可能是 list 或 dict
        strategies = data if isinstance(data, list) else data.get("strategies", [])
        assert isinstance(strategies, list), "策略列表应为数组"

    @pytest.mark.strategy
    def test_strategy_structure(self, client):
        """策略数据结构完整"""
        r = client.get("/strategy/list")
        data = r.json()
        strategies = data if isinstance(data, list) else data.get("strategies", [])
        if len(strategies) > 0:
            s = strategies[0]
            assert "id" in s, "策略缺少 id"
            assert "name" in s, "策略缺少 name"
            assert "status" in s, "策略缺少 status"


class TestBacktest:
    """回测模块"""

    @pytest.mark.backtest
    def test_backtest_strategies(self, client):
        """获取可用回测策略列表"""
        r = client.get("/backtest/strategies")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict), "回测策略应返回字典"
        assert len(data) >= 3, f"回测策略过少: {len(data)}"

    @pytest.mark.backtest
    def test_backtest_has_core_strategies(self, client):
        """核心回测策略存在"""
        r = client.get("/backtest/strategies")
        data = r.json()
        # 检查关键策略是否存在（key 可能被 camelCase 中间件转换）
        keys = list(data.keys())
        key_lower = [k.lower() for k in keys]
        assert any("hold" in k for k in key_lower), "缺少 Buy&Hold 策略"
        assert any("ma" in k for k in key_lower), "缺少均线策略"
        assert any("bollinger" in k or "bb" in k for k in key_lower), "缺少布林带策略"


class TestFunding:
    """资金费率模块"""

    @pytest.mark.funding
    def test_funding_summary(self, client):
        """获取资金费率汇总"""
        r = client.get("/funding/summary")
        assert r.status_code == 200
        data = r.json()
        assert "exchanges" in data, "缺少 exchanges 字段"
        assert "topOpportunities" in data or "top_opportunities" in data, "缺少套利机会字段"

    @pytest.mark.funding
    def test_funding_summary_exchanges(self, client):
        """资金费率汇总包含已配置的交易所"""
        from conftest import EXCHANGES
        r = client.get("/funding/summary")
        data = r.json()
        exchanges = data.get("exchanges", {})
        # 已配置的交易所应出现在汇总中（数据可以为空）
        for ex in EXCHANGES:
            assert ex in exchanges, f"资金费率汇总缺少 {ex}"
        assert "bybit" not in exchanges, "资金费率汇总不应包含 Bybit"

    @pytest.mark.funding
    def test_funding_opportunities(self, client):
        """获取套利机会"""
        from conftest import EXCHANGES
        r = client.get("/funding/opportunities", params={
            "exchange": EXCHANGES[0], "min_rate": 0.0001, "limit": 5
        })
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list), "套利机会应返回数组"
