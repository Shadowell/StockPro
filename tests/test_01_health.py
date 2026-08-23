"""
模块1: 健康检查 & 交易所连接测试
"""
import pytest


class TestHealth:
    """健康检查"""

    @pytest.mark.health
    def test_api_health(self, client):
        """API服务是否正常运行"""
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data

    @pytest.mark.health
    def test_exchanges_connected(self, client):
        """已配置的交易所是否连接正常"""
        from conftest import EXCHANGES
        r = client.get("/health/exchanges")
        assert r.status_code == 200
        data = r.json()
        exchanges = data.get("exchanges", {})
        for ex in EXCHANGES:
            assert ex in exchanges, f"缺少 {ex} 交易所"
            assert exchanges[ex] == "connected", f"{ex} 状态异常: {exchanges[ex]}"

    @pytest.mark.health
    def test_no_bybit(self, client):
        """确认已移除 Bybit"""
        r = client.get("/health/exchanges")
        data = r.json()
        exchanges = data.get("exchanges", {})
        assert "bybit" not in exchanges, "Bybit 应该已被移除"
