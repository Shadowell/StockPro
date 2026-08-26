import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class FakeOnchainProvider:
    async def fetch_chains(self):
        return [
            {"name": "Ethereum", "tvl": 10_000_000, "tokenSymbol": "ETH", "chainId": 1},
            {"name": "Solana", "tvl": 5_000_000, "tokenSymbol": "SOL", "chainId": 101},
        ]

    async def fetch_protocols(self):
        return [
            {
                "name": "Aave",
                "slug": "aave",
                "category": "Lending",
                "chain": "Multi-Chain",
                "chains": ["Ethereum", "Base"],
                "tvl": 7_000_000,
                "change_1d": 1.2,
                "change_7d": -2.4,
                "mcap": 900_000_000,
            },
            {
                "name": "Curve",
                "slug": "curve-finance",
                "category": "Dexs",
                "chain": "Ethereum",
                "chains": ["Ethereum"],
                "tvl": 3_000_000,
                "change_1d": -0.3,
                "change_7d": 0.6,
                "mcap": 400_000_000,
            },
        ]

    async def fetch_fees(self):
        return {
            "protocols": [
                {
                    "name": "Uniswap",
                    "slug": "uniswap",
                    "category": "Dexs",
                    "chains": ["Ethereum", "Base"],
                    "total24h": 1_000_000,
                    "total7d": 7_500_000,
                    "change_1d": 3.5,
                },
                {
                    "name": "Aave",
                    "slug": "aave",
                    "category": "Lending",
                    "chains": ["Ethereum"],
                    "total24h": 500_000,
                    "total7d": 3_200_000,
                    "change_1d": -1.1,
                },
            ]
        }

    async def fetch_stablecoins(self):
        return {
            "peggedAssets": [
                {
                    "name": "USD Coin",
                    "symbol": "USDC",
                    "pegType": "peggedUSD",
                    "price": 1.0,
                    "circulating": {"peggedUSD": 2_000_000},
                    "chains": ["Ethereum", "Base"],
                },
                {
                    "name": "Dai",
                    "symbol": "DAI",
                    "pegType": "peggedUSD",
                    "price": 0.999,
                    "circulating": {"peggedUSD": 1_000_000},
                    "chains": ["Ethereum"],
                },
            ],
            "chains": [
                {"name": "Ethereum", "totalCirculatingUSD": {"peggedUSD": 2_500_000}},
                {"name": "Base", "totalCirculatingUSD": {"peggedUSD": 500_000}},
            ],
        }

    async def fetch_yield_pools(self):
        return {
            "data": [
                {
                    "project": "aave-v3",
                    "chain": "Base",
                    "symbol": "USDC",
                    "tvlUsd": 2_000_000,
                    "apy": 4.2,
                    "apyMean30d": 4.0,
                    "stablecoin": True,
                    "ilRisk": "no",
                    "exposure": "single",
                    "pool": "pool-a",
                },
                {
                    "project": "tiny-pool",
                    "chain": "Ethereum",
                    "symbol": "USDT",
                    "tvlUsd": 25_000,
                    "apy": 18.0,
                    "stablecoin": True,
                    "ilRisk": "no",
                    "exposure": "single",
                    "pool": "pool-b",
                },
                {
                    "project": "volatile-farm",
                    "chain": "Solana",
                    "symbol": "SOL-USDC",
                    "tvlUsd": 4_000_000,
                    "apy": 22.0,
                    "stablecoin": False,
                    "ilRisk": "yes",
                    "exposure": "multi",
                    "pool": "pool-c",
                },
            ]
        }


class BrokenOnchainProvider:
    async def fetch_chains(self):
        raise RuntimeError("chains offline")

    async def fetch_protocols(self):
        raise RuntimeError("protocols offline")

    async def fetch_fees(self):
        raise RuntimeError("fees offline")

    async def fetch_stablecoins(self):
        raise RuntimeError("stablecoins offline")

    async def fetch_yield_pools(self):
        raise RuntimeError("yields offline")


def test_onchain_summary_reuses_persistent_cache_across_service_instances(tmp_path):
    async def run():
        from app.domain.onchain.service import OnchainDomainService

        cache_path = tmp_path / "onchain-summary.json"
        first_service = OnchainDomainService(
            provider=FakeOnchainProvider(),
            cache_ttl_sec=0,
            persistent_cache_path=cache_path,
            persistent_cache_ttl_sec=3600,
        )
        first_summary = await first_service.summary()

        second_service = OnchainDomainService(
            provider=BrokenOnchainProvider(),
            cache_ttl_sec=0,
            persistent_cache_path=cache_path,
            persistent_cache_ttl_sec=3600,
        )
        second_summary = await second_service.summary()
        return first_summary, second_summary

    first_summary, second_summary = asyncio.run(run())

    assert second_summary["status"] == "ready"
    assert second_summary["kpis"] == first_summary["kpis"]
    assert second_summary["chains"] == first_summary["chains"]
    assert second_summary["protocols"] == first_summary["protocols"]
    assert second_summary["warnings"] == first_summary["warnings"]


def test_onchain_summary_aggregates_defillama_research_data():
    async def run():
        from app.domain.onchain.service import OnchainDomainService

        service = OnchainDomainService(provider=FakeOnchainProvider(), cache_ttl_sec=0)
        return await service.summary()

    summary = asyncio.run(run())

    assert summary["status"] == "ready"
    assert summary["source"]["provider"] == "DeFiLlama"
    assert summary["source"]["auth_required"] is False
    assert summary["source_status"]["chains"] == "ready"
    assert summary["source_status"]["protocols"] == "ready"
    assert summary["source_status"]["fees"] == "ready"
    assert summary["source_status"]["stablecoins"] == "ready"
    assert summary["source_status"]["yield_pools"] == "ready"
    assert summary["warnings"] == []

    assert summary["kpis"]["total_tvl_usd"] == 15_000_000
    assert summary["kpis"]["total_stablecoins_usd"] == 3_000_000
    assert summary["kpis"]["protocol_count"] == 2
    assert summary["kpis"]["chain_count"] == 2
    assert summary["kpis"]["fee_24h_usd"] == 1_500_000
    assert summary["kpis"]["stable_yield_pool_count"] == 1
    assert summary["kpis"]["top_chain"]["name"] == "Ethereum"
    assert summary["kpis"]["top_protocol"]["name"] == "Aave"
    assert summary["kpis"]["top_fee_protocol"]["name"] == "Uniswap"

    assert [row["name"] for row in summary["chains"]] == ["Ethereum", "Solana"]
    assert [row["name"] for row in summary["protocols"]] == ["Aave", "Curve"]
    assert [row["name"] for row in summary["fees"]] == ["Uniswap", "Aave"]
    assert [row["symbol"] for row in summary["stablecoins"]] == ["USDC", "DAI"]
    assert [row["name"] for row in summary["stablecoin_chains"]] == ["Ethereum", "Base"]
    assert summary["yield_pools"] == [
        {
            "project": "aave-v3",
            "chain": "Base",
            "symbol": "USDC",
            "tvl_usd": 2_000_000.0,
            "apy": 4.2,
            "apy_mean_30d": 4.0,
            "stablecoin": True,
            "il_risk": "no",
            "exposure": "single",
            "pool": "pool-a",
            "pool_meta": None,
        }
    ]


def test_onchain_summary_returns_explicit_waiting_state_when_defillama_unavailable():
    async def run():
        from app.domain.onchain.service import OnchainDomainService

        service = OnchainDomainService(provider=BrokenOnchainProvider(), cache_ttl_sec=0)
        return await service.summary()

    summary = asyncio.run(run())

    assert summary["status"] == "waiting_for_data"
    assert summary["chains"] == []
    assert summary["protocols"] == []
    assert summary["fees"] == []
    assert summary["stablecoins"] == []
    assert summary["stablecoin_chains"] == []
    assert summary["yield_pools"] == []
    assert summary["empty_reason"] == "等待 DeFiLlama 返回真实链上数据"
    assert len(summary["warnings"]) == 5
    assert all("DeFiLlama" in warning for warning in summary["warnings"])
    assert all(status == "error" for status in summary["source_status"].values())
