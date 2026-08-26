"""OKX Orbit auto-post workflow for truthful live contract position sharing."""
from __future__ import annotations

import asyncio
import json
import math
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.db.local_db import db_instance as db
from app.services import live_account_service
from app.services.agent.llm_client import describe_qwen_exception, get_qwen_client, has_agent_api_key, validate_llm_model_name
from app.services.trading_service import trading_service


CONFIG_KEY = "okx_orbit_auto_post_config"
STATE_KEY = "okx_orbit_auto_post_state"
LOGIN_STATUS_CACHE_TTL_SEC = 20.0
CANDIDATE_PREVIEW_CACHE_TTL_SEC = 15.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _positive_float(value: Any) -> Optional[float]:
    out = _float(value)
    return out if out > 0 else None


def _symbol_base(symbol: str) -> str:
    raw = str(symbol or "").strip()
    if "/" in raw:
        return raw.split("/", 1)[0].upper()
    if "-" in raw:
        return raw.split("-", 1)[0].upper()
    return raw.replace("USDT", "").upper() or raw.upper()


def _publisher_subprocess_env() -> Dict[str, str]:
    env = dict(os.environ)
    if env.get("BITPRO_ORBIT_USE_SYSTEM_PROXY") == "1":
        return env
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    return env


def _side_label(side: str) -> str:
    return "做空" if str(side or "").lower() == "short" else "做多"


def _normalize_side(position: Dict[str, Any]) -> str:
    side = str(position.get("side") or position.get("posSide") or position.get("pos_side") or "").lower()
    if side in {"long", "short"}:
        return side
    size = _float(position.get("contracts") or position.get("amount") or position.get("size"))
    return "short" if size < 0 else "long"


def _position_size(position: Dict[str, Any]) -> float:
    return abs(_float(position.get("contracts") or position.get("amount") or position.get("size") or position.get("base_amount")))


def _position_margin(position: Dict[str, Any], notional: float, leverage: float) -> float:
    for key in ("margin", "initial_margin", "initialMargin", "collateral", "imr"):
        margin = _positive_float(position.get(key))
        if margin:
            return margin
    if notional > 0 and leverage > 0:
        return notional / leverage
    return 0.0


class BrowserOrbitPublisher:
    """Publish via an optional server-local browser command.

    OKX Orbit does not expose a documented public posting API. This publisher
    therefore shells out to a Playwright helper when available and returns an
    explicit login/configuration error when the helper cannot run.
    """

    def __init__(self, command: Optional[str] = None, timeout_sec: int = 90) -> None:
        self.command = command or os.getenv("BITPRO_ORBIT_POST_COMMAND") or self._default_command()
        self.timeout_sec = max(15, int(timeout_sec))

    @staticmethod
    def _default_command() -> str:
        root = Path(__file__).resolve().parents[3]
        script = root / "scripts" / "okx_orbit_publisher.js"
        return f"node {script}"

    async def status(self) -> Dict[str, Any]:
        return await self._run({"action": "status"})

    async def publish(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self._run({"action": "publish", **payload})

    async def _run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        command = str(self.command or "").strip()
        if not command:
            return {"status": "not_configured", "available": False, "error": "OKX Orbit 发布命令未配置"}

        def call() -> Dict[str, Any]:
            proc = subprocess.run(
                command,
                input=json.dumps(payload, ensure_ascii=False),
                text=True,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_publisher_subprocess_env(),
                timeout=self.timeout_sec,
            )
            stdout = (proc.stdout or "").strip()
            if proc.returncode != 0:
                return {
                    "status": "failed",
                    "available": False,
                    "error": (proc.stderr or stdout or f"发布命令退出 {proc.returncode}").strip()[:1200],
                }
            try:
                data = json.loads(stdout or "{}")
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass
            return {"status": "failed", "available": False, "error": f"发布命令返回非 JSON: {stdout[:500]}"}

        try:
            return await asyncio.to_thread(call)
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "available": False, "error": "OKX Orbit 发布命令超时"}
        except Exception as exc:
            return {"status": "failed", "available": False, "error": str(exc)}


class OrbitAutoPostService:
    def __init__(
        self,
        *,
        database: Any = db,
        account_service: Any = live_account_service,
        trading_service: Any = trading_service,
        publisher: Optional[Any] = None,
        now_fn: Callable[[], datetime] = _utcnow,
        llm_enabled_fn: Callable[[], bool] = has_agent_api_key,
    ) -> None:
        self.db = database
        self.account_service = account_service
        self.trading_service = trading_service
        self.publisher = publisher or BrowserOrbitPublisher()
        self.now_fn = now_fn
        self.llm_enabled_fn = llm_enabled_fn
        self._lock = asyncio.Lock()
        self._login_status_cache: Optional[tuple[float, Dict[str, Any]]] = None
        self._candidate_preview_cache: Optional[tuple[float, List[Dict[str, Any]]]] = None

    def default_config(self) -> Dict[str, Any]:
        return {
            "enabled": False,
            "account_id": "default",
            "interval_minutes": 10,
            "min_margin_roi_pct": 5.0,
            "max_posts_per_run": 1,
            "cooldown_hours": 24,
            "max_posts_per_day": 12,
            "llm_model": "",
            "copy_style": "吸引跟单但不夸大，不承诺收益，突出真实仓位、方向、收益率和风险控制。",
            "publish_mode": "orbit_web",
            "truthful_only": True,
            "running": False,
            "last_started_at": None,
            "last_finished_at": None,
            "last_posted_at": None,
            "last_error": None,
            "last_skip_reason": None,
        }

    def get_config(self) -> Dict[str, Any]:
        raw = self.db.get_app_setting(CONFIG_KEY, "{}") or "{}"
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            loaded = {}
        return self._normalize_config(loaded if isinstance(loaded, dict) else {})

    def _normalize_config(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        cfg = {**self.default_config(), **(payload if isinstance(payload, dict) else {})}
        cfg["enabled"] = bool(cfg.get("enabled"))
        cfg["interval_minutes"] = max(1, min(int(_float(cfg.get("interval_minutes"), 10)), 1440))
        cfg["min_margin_roi_pct"] = max(0.1, min(_float(cfg.get("min_margin_roi_pct"), 5.0), 10000.0))
        cfg["max_posts_per_run"] = max(1, min(int(_float(cfg.get("max_posts_per_run"), 1)), 5))
        cfg["cooldown_hours"] = max(0.0, min(_float(cfg.get("cooldown_hours"), 24.0), 720.0))
        cfg["max_posts_per_day"] = max(1, min(int(_float(cfg.get("max_posts_per_day"), 12)), 100))
        cfg["account_id"] = str(cfg.get("account_id") or "default")
        cfg["llm_model"] = str(cfg.get("llm_model") or "").strip()
        cfg["copy_style"] = str(cfg.get("copy_style") or self.default_config()["copy_style"]).strip()
        cfg["publish_mode"] = "orbit_web"
        cfg["truthful_only"] = True
        return cfg

    def update_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self.get_config()
        for key in (
            "enabled",
            "account_id",
            "interval_minutes",
            "min_margin_roi_pct",
            "max_posts_per_run",
            "cooldown_hours",
            "max_posts_per_day",
            "copy_style",
            "llm_model",
        ):
            if key in updates and updates.get(key) is not None:
                cfg[key] = updates.get(key)
        if cfg.get("llm_model"):
            cfg["llm_model"] = validate_llm_model_name(str(cfg["llm_model"]))
        normalized = self._normalize_config(cfg)
        self.db.set_app_setting(CONFIG_KEY, json.dumps(normalized, ensure_ascii=False))
        self._login_status_cache = None
        self._candidate_preview_cache = None
        return normalized

    def _load_state(self) -> Dict[str, Any]:
        raw = self.db.get_app_setting(STATE_KEY, "{}") or "{}"
        try:
            state = json.loads(raw)
        except json.JSONDecodeError:
            state = {}
        if not isinstance(state, dict):
            state = {}
        state.setdefault("posts", [])
        state.setdefault("last_seen", {})
        return state

    def _save_state(self, state: Dict[str, Any]) -> None:
        posts = list(state.get("posts") or [])[-200:]
        state["posts"] = posts
        self.db.set_app_setting(STATE_KEY, json.dumps(state, ensure_ascii=False))

    def list_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        return list(reversed((self._load_state().get("posts") or [])[-max(1, min(int(limit), 200)):]))

    async def login_status(self) -> Dict[str, Any]:
        cached = self._login_status_cache
        if cached and time.monotonic() - cached[0] <= LOGIN_STATUS_CACHE_TTL_SEC:
            return {**cached[1], "cached": True}

        status = await self.publisher.status()
        payload = {
            "publish_mode": "orbit_web",
            "available": bool(status.get("available", status.get("status") not in {"failed", "not_configured", "timeout"})),
            "logged_in": bool(status.get("logged_in")),
            "status": status.get("status") or "unknown",
            "url": status.get("url"),
            "error": status.get("error"),
        }
        self._login_status_cache = (time.monotonic(), dict(payload))
        return payload

    async def preview_candidates(self, *, force_refresh: bool = False) -> List[Dict[str, Any]]:
        cached = self._candidate_preview_cache
        if (
            not force_refresh
            and cached
            and time.monotonic() - cached[0] <= CANDIDATE_PREVIEW_CACHE_TTL_SEC
        ):
            return [dict(item) for item in cached[1]]

        cfg = self.get_config()
        state = self._load_state()
        positions = await self._fetch_positions(cfg)
        candidates = [self._position_to_candidate(pos, cfg, state) for pos in positions]
        candidates = [item for item in candidates if item is not None]
        candidates.sort(key=lambda item: _float(item.get("margin_roi_pct")), reverse=True)
        self._candidate_preview_cache = (time.monotonic(), [dict(item) for item in candidates])
        return candidates

    async def run_due(self) -> Dict[str, Any]:
        cfg = self.get_config()
        if not cfg.get("enabled"):
            return {"started": False, "skipped": "disabled"}
        last_finished = _parse_dt(cfg.get("last_finished_at"))
        if last_finished and self.now_fn() - last_finished < timedelta(minutes=int(cfg["interval_minutes"])):
            return {"started": False, "skipped": "not_due"}
        return await self.run_once(force=False)

    async def run_once(self, *, force: bool = False) -> Dict[str, Any]:
        if self._lock.locked():
            return {"started": False, "running": True, "skipped": "already_running"}
        async with self._lock:
            cfg = self.get_config()
            if not force and not cfg.get("enabled"):
                return {"started": False, "skipped": "disabled"}
            self._set_runtime(running=True, last_started_at=_iso(self.now_fn()), last_error=None, last_skip_reason=None)
            try:
                candidates = await self.preview_candidates(force_refresh=True)
                eligible = [item for item in candidates if item.get("eligible")]
                eligible = eligible[: int(cfg.get("max_posts_per_run") or 1)]
                if not eligible:
                    self._set_runtime(running=False, last_finished_at=_iso(self.now_fn()), last_skip_reason="no_eligible_candidates")
                    return {
                        "started": True,
                        "posted_count": 0,
                        "skipped": "no_eligible_candidates",
                        "candidates": candidates,
                    }
                posted: List[Dict[str, Any]] = []
                for candidate in eligible:
                    posted.append(await self.publish_candidate(candidate, cfg=cfg))
                finished = _iso(self.now_fn())
                self._set_runtime(
                    running=False,
                    last_finished_at=finished,
                    last_posted_at=posted[-1].get("created_at") if posted else None,
                    last_error=None,
                    last_skip_reason=None,
                )
                return {
                    "started": True,
                    "posted_count": len(posted),
                    "posted": posted,
                    "candidates": candidates,
                }
            except Exception as exc:
                self._set_runtime(running=False, last_finished_at=_iso(self.now_fn()), last_error=str(exc), last_skip_reason=None)
                raise

    async def publish_candidate(self, candidate: Dict[str, Any], *, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        config = cfg or self.get_config()
        content = await self._build_copy(candidate, config)
        publish_result = await self.publisher.publish({"content": content, "candidate": candidate})
        record = {
            "id": f"orbit-{int(self.now_fn().timestamp() * 1000)}-{candidate.get('dedupe_key')}",
            "candidate": candidate,
            "content": content,
            "status": publish_result.get("status") or "unknown",
            "url": publish_result.get("url"),
            "error": publish_result.get("error"),
            "created_at": _iso(self.now_fn()),
            "publish_result": publish_result,
        }
        state = self._load_state()
        state.setdefault("posts", []).append(record)
        if str(record.get("status") or "").lower() in {"published", "submitted", "sent", "ok"}:
            state.setdefault("last_seen", {})[str(candidate.get("dedupe_key"))] = record["created_at"]
        self._save_state(state)
        self._candidate_preview_cache = None
        return record

    async def _fetch_positions(self, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        account_id = str(cfg.get("account_id") or "default")
        account = self.account_service.get_account(account_id) if hasattr(self.account_service, "get_account") else None
        if account is not None and (not account.get("enabled") or not account.get("configured")):
            return []
        exchange_alias = self.account_service.exchange_alias_for_account(account_id)
        return list(await self.trading_service.get_positions(exchange_alias, None) or [])

    def _position_to_candidate(self, position: Dict[str, Any], cfg: Dict[str, Any], state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        symbol = str(position.get("symbol") or position.get("instId") or "").strip()
        if not symbol or ("USDT" not in symbol.upper() or (":USDT" not in symbol.upper() and "-SWAP" not in symbol.upper())):
            return None
        side = _normalize_side(position)
        size = _position_size(position)
        if size <= 0:
            return None
        entry = _positive_float(position.get("entry_price") or position.get("entryPrice") or position.get("avgPx")) or 0.0
        mark = _positive_float(position.get("mark_price") or position.get("markPrice") or position.get("markPx") or position.get("last")) or entry
        pnl = _float(position.get("unrealized_pnl") or position.get("unrealizedPnl") or position.get("upl"))
        leverage = _positive_float(position.get("leverage") or position.get("lever")) or 1.0
        notional = _positive_float(position.get("notional_usdt") or position.get("notional") or position.get("notionalUsd"))
        if notional is None:
            notional = abs(size * (mark or entry))
        margin = _position_margin(position, notional, leverage)
        roi = (pnl / margin * 100.0) if margin > 0 else 0.0
        account_id = str(cfg.get("account_id") or "default")
        dedupe_key = f"{account_id}:{symbol}:{side}:{round(entry, 8)}"
        last_posted = _parse_dt((state.get("last_seen") or {}).get(dedupe_key))
        cooldown_hours = _float(cfg.get("cooldown_hours"), 24.0)
        blocked_reason = ""
        if roi < _float(cfg.get("min_margin_roi_pct"), 5.0):
            return None
        elif last_posted and cooldown_hours > 0 and self.now_fn() - last_posted < timedelta(hours=cooldown_hours):
            blocked_reason = "cooldown"

        return {
            "id": dedupe_key,
            "dedupe_key": dedupe_key,
            "account_id": account_id,
            "symbol": symbol,
            "base": _symbol_base(symbol),
            "side": side,
            "side_label": _side_label(side),
            "leverage": round(leverage, 4),
            "size": round(size, 10),
            "entry_price": round(entry, 10),
            "mark_price": round(mark, 10),
            "unrealized_pnl": round(pnl, 6),
            "margin": round(margin, 6),
            "notional_usdt": round(notional, 6),
            "margin_roi_pct": round(roi, 6),
            "threshold_pct": _float(cfg.get("min_margin_roi_pct"), 5.0),
            "eligible": not blocked_reason,
            "blocked_reason": blocked_reason,
            "source": "okx_live_position",
        }

    async def _build_copy(self, candidate: Dict[str, Any], cfg: Dict[str, Any]) -> str:
        fallback = self._fallback_copy(candidate)
        model = str(cfg.get("llm_model") or "").strip() or None
        if not self.llm_enabled_fn():
            return fallback
        messages = [
            {
                "role": "system",
                "content": (
                    "你是合规的 OKX 星球交易动态文案助手。只基于给定真实持仓数据写中文短帖；"
                    "可以吸引关注和跟单兴趣，但禁止承诺收益、夸大胜率、伪造数据、诱导满仓或无风险表达。"
                    "必须包含风险提示“不是投资建议”。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "style": cfg.get("copy_style"),
                        "position": candidate,
                        "requirements": [
                            "80 到 180 字",
                            "包含交易对、方向、杠杆、保证金收益率、浮盈",
                            "结尾提醒跟单需控制仓位和止损",
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        try:
            text = await get_qwen_client(model).chat(messages, temperature=0.8, max_tokens=360)
            normalized = str(text or "").strip()
            if "投资建议" not in normalized:
                normalized = f"{normalized}\n\n不是投资建议，跟单注意仓位和止损。"
            return normalized[:800]
        except Exception as exc:
            return f"{fallback}\n\nAI文案生成失败，已使用真实数据模板：{describe_qwen_exception(exc)}"

    @staticmethod
    def _fallback_copy(candidate: Dict[str, Any]) -> str:
        symbol = candidate.get("symbol") or "--"
        side = candidate.get("side_label") or _side_label(str(candidate.get("side") or "long"))
        roi = _float(candidate.get("margin_roi_pct"))
        pnl = _float(candidate.get("unrealized_pnl"))
        leverage = _float(candidate.get("leverage"))
        entry = _float(candidate.get("entry_price"))
        mark = _float(candidate.get("mark_price"))
        base = candidate.get("base") or _symbol_base(str(symbol))
        return (
            f"${base} 合约单达到自动分享阈值：{symbol} {side} {leverage:g}x，"
            f"保证金收益率 {roi:+.2f}%，浮盈 {pnl:+.2f} USDT。"
            f"入场 {entry:g}，当前 {mark:g}。这条来自 BitPro 读取的 OKX 实盘持仓，"
            "不构成投资建议，跟单注意仓位和止损。"
        )

    def _set_runtime(self, **updates: Any) -> None:
        cfg = self.get_config()
        cfg.update(updates)
        self.db.set_app_setting(CONFIG_KEY, json.dumps(cfg, ensure_ascii=False))


orbit_auto_post_service = OrbitAutoPostService()
