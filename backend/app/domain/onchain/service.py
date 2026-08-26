from __future__ import annotations

import asyncio
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ONCHAIN_CACHE_PATH = PROJECT_ROOT / "data" / "cache" / "onchain_summary.json"

DEFI_LLAMA_ENDPOINTS = {
    "chains": "https://api.llama.fi/v2/chains",
    "protocols": "https://api.llama.fi/protocols",
    "fees": "https://api.llama.fi/overview/fees",
    "stablecoins": "https://stablecoins.llama.fi/stablecoins",
    "yield_pools": "https://yields.llama.fi/pools",
}


class OnchainSnapshotProvider(Protocol):
    async def fetch_chains(self) -> Any:
        ...

    async def fetch_protocols(self) -> Any:
        ...

    async def fetch_fees(self) -> Any:
        ...

    async def fetch_stablecoins(self) -> Any:
        ...

    async def fetch_yield_pools(self) -> Any:
        ...


class DeFiLlamaOnchainProvider:
    def __init__(self, timeout_sec: float = 10.0):
        self.timeout_sec = float(timeout_sec)

    async def _get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        async with httpx.AsyncClient(timeout=self.timeout_sec, trust_env=False) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    async def fetch_chains(self) -> Any:
        return await self._get(DEFI_LLAMA_ENDPOINTS["chains"])

    async def fetch_protocols(self) -> Any:
        return await self._get(DEFI_LLAMA_ENDPOINTS["protocols"])

    async def fetch_fees(self) -> Any:
        return await self._get(DEFI_LLAMA_ENDPOINTS["fees"])

    async def fetch_stablecoins(self) -> Any:
        return await self._get(DEFI_LLAMA_ENDPOINTS["stablecoins"], {"includePrices": "true"})

    async def fetch_yield_pools(self) -> Any:
        return await self._get(DEFI_LLAMA_ENDPOINTS["yield_pools"])


class OnchainDomainService:
    def __init__(
        self,
        provider: Optional[OnchainSnapshotProvider] = None,
        *,
        cache_ttl_sec: float = 300.0,
        persistent_cache_path: Optional[str | Path] = None,
        persistent_cache_ttl_sec: float = 1800.0,
        stable_pool_min_tvl_usd: float = 1_000_000.0,
        stable_pool_max_apy: float = 80.0,
    ):
        self.provider = provider or DeFiLlamaOnchainProvider()
        self.cache_ttl_sec = max(0.0, float(cache_ttl_sec))
        self.persistent_cache_path = Path(persistent_cache_path) if persistent_cache_path else None
        self.persistent_cache_ttl_sec = max(0.0, float(persistent_cache_ttl_sec))
        self.stable_pool_min_tvl_usd = float(stable_pool_min_tvl_usd)
        self.stable_pool_max_apy = float(stable_pool_max_apy)
        self._cache_until = 0.0
        self._cache_payload: Optional[Dict[str, Any]] = None

    async def summary(self) -> Dict[str, Any]:
        now = time.monotonic()
        if self._cache_payload is not None and self.cache_ttl_sec > 0 and now < self._cache_until:
            return self._cache_payload

        wall_now = time.time()
        persistent_payload = self._read_persistent_cache(wall_now)
        if persistent_payload is not None:
            if self.cache_ttl_sec > 0:
                self._cache_payload = persistent_payload
                self._cache_until = now + self.cache_ttl_sec
            return persistent_payload

        endpoint_calls = {
            "chains": self.provider.fetch_chains(),
            "protocols": self.provider.fetch_protocols(),
            "fees": self.provider.fetch_fees(),
            "stablecoins": self.provider.fetch_stablecoins(),
            "yield_pools": self.provider.fetch_yield_pools(),
        }
        results = await asyncio.gather(
            *(self._capture_endpoint(name, call) for name, call in endpoint_calls.items())
        )
        raw_by_name: Dict[str, Any] = {}
        source_status: Dict[str, str] = {}
        warnings: List[str] = []
        for name, payload, status, warning in results:
            raw_by_name[name] = payload
            source_status[name] = status
            if warning:
                warnings.append(warning)

        chains = self._normalize_chains(raw_by_name.get("chains"))
        protocols = self._normalize_protocols(raw_by_name.get("protocols"))
        fees = self._normalize_fees(raw_by_name.get("fees"))
        stablecoins = self._normalize_stablecoins(raw_by_name.get("stablecoins"))
        stablecoin_chains = self._normalize_stablecoin_chains(raw_by_name.get("stablecoins"))
        yield_pools = self._normalize_yield_pools(raw_by_name.get("yield_pools"))

        has_data = any([chains, protocols, fees, stablecoins, stablecoin_chains, yield_pools])
        status = "ready"
        empty_reason = ""
        if not has_data:
            status = "waiting_for_data"
            empty_reason = "等待 DeFiLlama 返回真实链上数据"
        elif warnings:
            status = "partial"

        payload = {
            **self._base_summary(status=status, source_status=source_status, warnings=warnings, empty_reason=empty_reason),
            "kpis": self._build_kpis(chains, protocols, fees, stablecoins, yield_pools),
            "chains": chains,
            "protocols": protocols,
            "fees": fees,
            "stablecoins": stablecoins,
            "stablecoin_chains": stablecoin_chains,
            "yield_pools": yield_pools,
        }
        if self.cache_ttl_sec > 0:
            self._cache_payload = payload
            self._cache_until = now + self.cache_ttl_sec
        self._write_persistent_cache(payload, wall_now)
        return payload

    def _read_persistent_cache(self, now: float) -> Optional[Dict[str, Any]]:
        if self.persistent_cache_path is None or self.persistent_cache_ttl_sec <= 0:
            return None
        try:
            record = json.loads(self.persistent_cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(record, dict):
            return None
        created_at = finite_float(record.get("created_at"))
        payload = record.get("payload")
        if created_at is None or not isinstance(payload, dict):
            return None
        if now - created_at > self.persistent_cache_ttl_sec:
            return None
        return payload

    def _write_persistent_cache(self, payload: Dict[str, Any], now: float) -> None:
        if self.persistent_cache_path is None or self.persistent_cache_ttl_sec <= 0:
            return
        if not self._summary_has_rows(payload):
            return
        try:
            self.persistent_cache_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.persistent_cache_path.with_suffix(f"{self.persistent_cache_path.suffix}.tmp")
            temp_path.write_text(
                json.dumps({"created_at": now, "payload": payload}, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            temp_path.replace(self.persistent_cache_path)
        except OSError:
            return

    @staticmethod
    def _summary_has_rows(payload: Dict[str, Any]) -> bool:
        return any(
            bool(payload.get(key))
            for key in ("chains", "protocols", "fees", "stablecoins", "stablecoin_chains", "yield_pools")
        )

    async def _capture_endpoint(self, name: str, call: Any) -> Tuple[str, Any, str, Optional[str]]:
        try:
            payload = await call
        except Exception as exc:
            return name, None, "error", f"DeFiLlama {name} 读取失败: {exc}"
        if not self._payload_has_rows(payload):
            return name, payload, "empty", None
        return name, payload, "ready", None

    def _base_summary(
        self,
        *,
        status: str,
        source_status: Optional[Dict[str, str]] = None,
        warnings: Optional[List[str]] = None,
        empty_reason: str = "",
    ) -> Dict[str, Any]:
        return {
            "status": status,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "source": {
                "provider": "DeFiLlama",
                "auth_required": False,
                "endpoints": DEFI_LLAMA_ENDPOINTS,
            },
            "source_status": source_status or {name: "empty" for name in DEFI_LLAMA_ENDPOINTS},
            "kpis": self._empty_kpis(),
            "chains": [],
            "protocols": [],
            "fees": [],
            "stablecoins": [],
            "stablecoin_chains": [],
            "yield_pools": [],
            "warnings": warnings or [],
            "empty_reason": empty_reason,
        }

    @staticmethod
    def _empty_kpis() -> Dict[str, Any]:
        return {
            "total_tvl_usd": 0.0,
            "total_stablecoins_usd": 0.0,
            "protocol_count": 0,
            "chain_count": 0,
            "fee_24h_usd": 0.0,
            "stable_yield_pool_count": 0,
            "top_chain": None,
            "top_protocol": None,
            "top_fee_protocol": None,
        }

    def _build_kpis(
        self,
        chains: List[Dict[str, Any]],
        protocols: List[Dict[str, Any]],
        fees: List[Dict[str, Any]],
        stablecoins: List[Dict[str, Any]],
        yield_pools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "total_tvl_usd": round(sum(row.get("tvl_usd") or 0.0 for row in chains), 2),
            "total_stablecoins_usd": round(sum(row.get("supply_usd") or 0.0 for row in stablecoins), 2),
            "protocol_count": len(protocols),
            "chain_count": len(chains),
            "fee_24h_usd": round(sum(row.get("total_24h_usd") or 0.0 for row in fees), 2),
            "stable_yield_pool_count": len(yield_pools),
            "top_chain": chains[0] if chains else None,
            "top_protocol": protocols[0] if protocols else None,
            "top_fee_protocol": fees[0] if fees else None,
        }

    @classmethod
    def _normalize_chains(cls, payload: Any) -> List[Dict[str, Any]]:
        rows = payload if isinstance(payload, list) else []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            tvl = finite_float(row.get("tvl")) or 0.0
            name = text_value(row.get("name"))
            if not name or tvl <= 0:
                continue
            out.append(
                {
                    "name": name,
                    "tvl_usd": round(tvl, 2),
                    "token_symbol": text_value(row.get("tokenSymbol")),
                    "chain_id": row.get("chainId"),
                }
            )
        out.sort(key=lambda item: item["tvl_usd"], reverse=True)
        return out[:20]

    @classmethod
    def _normalize_protocols(cls, payload: Any) -> List[Dict[str, Any]]:
        rows = payload if isinstance(payload, list) else []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            tvl = finite_float(row.get("tvl")) or 0.0
            name = text_value(row.get("name"))
            if not name or tvl <= 0:
                continue
            chains = [text_value(value) for value in row.get("chains") or [] if text_value(value)]
            if not chains and text_value(row.get("chain")):
                chains = [text_value(row.get("chain"))]
            out.append(
                {
                    "name": name,
                    "slug": text_value(row.get("slug")),
                    "category": text_value(row.get("category")),
                    "chain": text_value(row.get("chain")),
                    "chains": chains[:8],
                    "tvl_usd": round(tvl, 2),
                    "change_1d": finite_float(row.get("change_1d")),
                    "change_7d": finite_float(row.get("change_7d")),
                    "mcap_usd": finite_float(row.get("mcap")),
                }
            )
        out.sort(key=lambda item: item["tvl_usd"], reverse=True)
        return out[:20]

    @classmethod
    def _normalize_fees(cls, payload: Any) -> List[Dict[str, Any]]:
        rows: Any = []
        if isinstance(payload, dict):
            rows = payload.get("protocols") or payload.get("data") or []
        out: List[Dict[str, Any]] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            total_24h = finite_float(row.get("total24h")) or 0.0
            total_7d = finite_float(row.get("total7d")) or 0.0
            name = text_value(row.get("displayName") or row.get("name"))
            if not name or (total_24h <= 0 and total_7d <= 0):
                continue
            chains = [text_value(value) for value in row.get("chains") or [] if text_value(value)]
            out.append(
                {
                    "name": name,
                    "slug": text_value(row.get("slug")),
                    "category": text_value(row.get("category")),
                    "chains": chains[:8],
                    "total_24h_usd": round(total_24h, 2),
                    "total_7d_usd": round(total_7d, 2),
                    "change_1d": finite_float(row.get("change_1d")),
                }
            )
        out.sort(key=lambda item: item["total_24h_usd"], reverse=True)
        return out[:20]

    @classmethod
    def _normalize_stablecoins(cls, payload: Any) -> List[Dict[str, Any]]:
        rows: Any = payload.get("peggedAssets") if isinstance(payload, dict) else []
        out: List[Dict[str, Any]] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            circulating = row.get("circulating") if isinstance(row.get("circulating"), dict) else {}
            supply = sum_finite_values(circulating)
            symbol = text_value(row.get("symbol"))
            name = text_value(row.get("name"))
            if not symbol or supply <= 0:
                continue
            chain_count = 0
            if isinstance(row.get("chains"), list):
                chain_count = len(row.get("chains") or [])
            elif isinstance(row.get("chainCirculating"), dict):
                chain_count = len(row.get("chainCirculating") or {})
            out.append(
                {
                    "symbol": symbol,
                    "name": name or symbol,
                    "peg_type": text_value(row.get("pegType")),
                    "supply_usd": round(supply, 2),
                    "price": finite_float(row.get("price")),
                    "chain_count": chain_count,
                }
            )
        out.sort(key=lambda item: item["supply_usd"], reverse=True)
        return out[:20]

    @classmethod
    def _normalize_stablecoin_chains(cls, payload: Any) -> List[Dict[str, Any]]:
        rows: Any = payload.get("chains") if isinstance(payload, dict) else []
        out: List[Dict[str, Any]] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            supply = 0.0
            totals = row.get("totalCirculatingUSD")
            if isinstance(totals, dict):
                supply = sum_finite_values(totals)
            name = text_value(row.get("name"))
            if not name or supply <= 0:
                continue
            out.append({"name": name, "supply_usd": round(supply, 2)})
        out.sort(key=lambda item: item["supply_usd"], reverse=True)
        return out[:20]

    def _normalize_yield_pools(self, payload: Any) -> List[Dict[str, Any]]:
        rows: Any = payload.get("data") if isinstance(payload, dict) else []
        out: List[Dict[str, Any]] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or row.get("stablecoin") is not True or row.get("outlier") is True:
                continue
            tvl = finite_float(row.get("tvlUsd")) or 0.0
            apy = finite_float(row.get("apy"))
            if apy is None or tvl < self.stable_pool_min_tvl_usd or apy < 0 or apy > self.stable_pool_max_apy:
                continue
            out.append(
                {
                    "project": text_value(row.get("project")),
                    "chain": text_value(row.get("chain")),
                    "symbol": text_value(row.get("symbol")),
                    "tvl_usd": round(tvl, 2),
                    "apy": round(apy, 4),
                    "apy_mean_30d": finite_float(row.get("apyMean30d")),
                    "stablecoin": True,
                    "il_risk": text_value(row.get("ilRisk")),
                    "exposure": text_value(row.get("exposure")),
                    "pool": text_value(row.get("pool")),
                    "pool_meta": row.get("poolMeta"),
                }
            )
        out.sort(key=lambda item: (item["apy"], item["tvl_usd"]), reverse=True)
        return out[:20]

    @staticmethod
    def _payload_has_rows(payload: Any) -> bool:
        if isinstance(payload, list):
            return len(payload) > 0
        if isinstance(payload, dict):
            for value in payload.values():
                if isinstance(value, list) and value:
                    return True
        return False


def finite_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def sum_finite_values(record: Dict[str, Any]) -> float:
    total = 0.0
    for value in record.values():
        number = finite_float(value)
        if number is not None:
            total += number
    return total


def text_value(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value)


onchain_domain_service = OnchainDomainService(persistent_cache_path=DEFAULT_ONCHAIN_CACHE_PATH)
