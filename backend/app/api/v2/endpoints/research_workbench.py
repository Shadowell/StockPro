"""BitPro's controlled server-side proxy for the HyperTrade research workbench.

The browser never receives HyperTrade credentials and this module deliberately
does not expose live trading, order, transfer, or direct paper-control routes.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.contracts import ok
from app.db.local_db import db_instance as db

router = APIRouter()

_SENSITIVE_TEXT = re.compile(r"(?i)(cookie|token|secret|password|authorization)\s*[:=]\s*[^,;\s]+")
_OBJECT_ID_KEYS = ("id", "mandate_id", "job_id", "promotion_id", "card_id")
_ALLOWED_REVIEW_ACTIONS = {"request_paper_review", "request_pause_review", "retire_candidate_review"}


class ProxyFailure(Exception):
    def __init__(self, status_code: int, code: str, detail: str) -> None:
        self.status_code = status_code
        self.code = code
        self.detail = detail
        super().__init__(detail)


class WriteRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=160)


class MandateCreateRequest(WriteRequest):
    name: str = Field(min_length=1, max_length=160)
    market_type: Literal["spot", "swap"] = "swap"
    symbols: list[str] = Field(min_length=1)
    timeframes: list[str] = Field(min_length=1)
    strategy_categories: list[str] = Field(min_length=1)
    budget: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
    paper_promotion_mode: Literal["manual_approval"] = "manual_approval"
    live_mode: Literal["disabled"] = "disabled"


class StrategySpecDraftRequest(WriteRequest):
    prompt: str = Field(min_length=3, max_length=4000)


class ResearchJobCreateRequest(WriteRequest):
    prompt: str = Field(min_length=3, max_length=4000)
    source_run_id: str = Field(default="", max_length=160)


class ResearchJobCancelRequest(WriteRequest):
    pass


class PaperPromotionRequest(WriteRequest):
    evidence_id: str = Field(min_length=1, max_length=160)
    job_id: str = Field(min_length=1, max_length=160)


class PaperApprovalRequest(WriteRequest):
    pass


def _require_admin(request: Request) -> str:
    auth = getattr(request.state, "auth", None) or {}
    if auth.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员登录才能访问策略研发工作台")
    return str(auth.get("session_id") or "bitpro:local-admin")


def _safe_text(value: Any, *, limit: int = 500) -> str:
    text = str(value or "").strip()
    text = _SENSITIVE_TEXT.sub(r"\\1=[已脱敏]", text)
    return text[:limit]


def _header_text(value: str) -> str:
    """Return an ASCII-safe representation for an HTTP header value.

    HTTP header values accepted by httpx must be ASCII. Reasons stay in their
    original Chinese form in the BitPro audit trail, while the upstream header
    carries their UTF-8 percent-encoded form with an explicit encoding marker.
    """
    return quote(str(value), safe="")


def _object_id(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in _OBJECT_ID_KEYS:
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    for key in ("mandate", "job", "promotion", "card"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            found = _object_id(nested)
            if found:
                return found
    return ""


def _items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("items", [])
    return [item for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []


def _review_items(payload: Any) -> list[dict[str, Any]]:
    """Never surface executable lifecycle actions from an upstream review queue."""
    return [row for row in _items(payload) if str(row.get("action") or "") in _ALLOWED_REVIEW_ACTIONS]


class HyperTradeProxy:
    def _config(self) -> tuple[str, str]:
        base = str(settings.HYPERTRADE_API_BASE or "").strip().rstrip("/")
        cookie = str(settings.HYPERTRADE_ADMIN_SESSION_COOKIE or "").strip()
        if not base:
            raise ProxyFailure(503, "HYPERTRADE_UNAVAILABLE", "HyperTrade 服务地址未由服务器环境配置")
        if not cookie:
            raise ProxyFailure(503, "HYPERTRADE_UNAVAILABLE", "HyperTrade 管理员会话未由服务器环境配置")
        return base, cookie

    async def request(
        self,
        method: str,
        path: str,
        *,
        operator_id: str,
        action: str,
        reason: str = "",
        idempotency_key: str = "",
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> Any:
        request_id = uuid.uuid4().hex
        try:
            base, cookie = self._config()
        except ProxyFailure as exc:
            self._audit(
                request_id=request_id, operator_id=operator_id, action=action, path=path,
                reason=reason, idempotency_key=idempotency_key, status_code=exc.status_code,
                success=False, error_code=exc.code,
            )
            raise

        headers = {
            "Accept": "application/json",
            "Cookie": cookie,
            "X-Request-ID": request_id,
            "X-BitPro-Operator": _header_text(operator_id),
        }
        if reason:
            headers["X-BitPro-Reason"] = _header_text(reason)
            headers["X-BitPro-Reason-Encoding"] = "utf-8-percent-encoded"
        if idempotency_key:
            headers["Idempotency-Key"] = _header_text(idempotency_key)
        try:
            async with httpx.AsyncClient(timeout=max(1.0, float(settings.HYPERTRADE_REQUEST_TIMEOUT_SEC))) as client:
                response = await client.request(
                    method=method,
                    url=f"{base}{path}",
                    headers=headers,
                    json=payload,
                    params=query,
                )
        except httpx.TimeoutException as exc:
            self._audit(request_id=request_id, operator_id=operator_id, action=action, path=path, reason=reason, idempotency_key=idempotency_key, status_code=504, success=False, error_code="HYPERTRADE_TIMEOUT")
            raise ProxyFailure(504, "HYPERTRADE_TIMEOUT", "HyperTrade 请求超时") from exc
        except httpx.HTTPError as exc:
            self._audit(request_id=request_id, operator_id=operator_id, action=action, path=path, reason=reason, idempotency_key=idempotency_key, status_code=502, success=False, error_code="HYPERTRADE_UNAVAILABLE")
            raise ProxyFailure(502, "HYPERTRADE_UNAVAILABLE", "HyperTrade 服务不可用") from exc
        except UnicodeError as exc:
            self._audit(request_id=request_id, operator_id=operator_id, action=action, path=path, reason=reason, idempotency_key=idempotency_key, status_code=502, success=False, error_code="HYPERTRADE_PROXY_ENCODING_ERROR")
            raise ProxyFailure(502, "HYPERTRADE_PROXY_ENCODING_ERROR", "HyperTrade 代理请求编码失败") from exc

        try:
            body: Any = response.json()
        except ValueError:
            body = {"detail": _safe_text(response.text)}
        if response.status_code >= 400:
            detail = _safe_text(body.get("detail") if isinstance(body, dict) else body)
            code = "HYPERTRADE_REJECTED" if response.status_code in {400, 409, 422} else "HYPERTRADE_UPSTREAM_ERROR"
            self._audit(request_id=request_id, operator_id=operator_id, action=action, path=path, reason=reason, idempotency_key=idempotency_key, status_code=response.status_code, success=False, error_code=code)
            raise ProxyFailure(response.status_code, code, detail or "HyperTrade 拒绝了该请求")

        self._audit(
            request_id=request_id, operator_id=operator_id, action=action, path=path,
            reason=reason, idempotency_key=idempotency_key, returned_object_id=_object_id(body),
            status_code=response.status_code, success=True,
        )
        return body

    @staticmethod
    def _audit(**kwargs: Any) -> None:
        try:
            db.record_research_workbench_audit(
                request_id=str(kwargs["request_id"]),
                operator_id=str(kwargs["operator_id"]),
                action=str(kwargs["action"]),
                upstream_path=str(kwargs["path"]),
                reason=str(kwargs.get("reason") or ""),
                idempotency_key=str(kwargs.get("idempotency_key") or ""),
                returned_object_id=str(kwargs.get("returned_object_id") or ""),
                status_code=kwargs.get("status_code"),
                success=bool(kwargs.get("success", True)),
                error_code=str(kwargs.get("error_code") or ""),
            )
        except Exception:
            # A local audit storage error must not reveal credentials or replace the upstream result.
            return


proxy = HyperTradeProxy()


async def _call(
    method: str,
    path: str,
    request: Request,
    *,
    action: str,
    reason: str = "",
    idempotency_key: str = "",
    payload: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
) -> Any:
    operator_id = _require_admin(request)
    try:
        return await proxy.request(
            method, path, operator_id=operator_id, action=action, reason=reason,
            idempotency_key=idempotency_key, payload=payload, query=query,
        )
    except ProxyFailure as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.detail}) from exc


async def _summary_payload(request: Request) -> dict[str, Any]:
    operator_id = _require_admin(request)
    calls = {
        "mandates": ("/api/research/mandates", "list_mandates"),
        "jobs": ("/api/research/jobs", "list_jobs"),
        "promotions": ("/api/research/paper-promotions", "list_paper_promotions"),
        "reviews": ("/api/research/paper-review-requests", "list_paper_reviews"),
        "cards": ("/api/research/strategy-cards", "list_strategy_cards"),
        "portfolio": ("/api/world-model/portfolio", "get_portfolio_review"),
    }
    try:
        responses = await asyncio.gather(*[
            proxy.request("GET", path, operator_id=operator_id, action=action)
            for path, action in calls.values()
        ])
    except ProxyFailure as exc:
        return {
            "connection": {"status": "unavailable", "error": exc.detail, "error_code": exc.code},
            "last_synced_at": None,
            "metrics": {"active_mandates": 0, "running_jobs": 0, "passing_candidates": 0, "pending_paper_approvals": 0, "paper_observing": 0, "review_requests": 0},
            "mandates": [], "jobs": [], "paper_promotions": [], "paper_review_requests": [], "strategy_cards": [],
        }
    data = dict(zip(calls.keys(), responses, strict=True))
    mandates = _items(data["mandates"])
    jobs = _items(data["jobs"])
    promotions = _items(data["promotions"])
    reviews = _review_items(data["reviews"])
    cards = _items(data["cards"])
    return {
        "connection": {"status": "connected", "error": "", "error_code": ""},
        "last_synced_at": datetime.now(timezone.utc).isoformat(),
        "metrics": {
            "active_mandates": sum(row.get("status") == "active" for row in mandates),
            "running_jobs": sum(row.get("status") in {"queued", "planning", "running", "validating"} for row in jobs),
            "passing_candidates": sum(row.get("validation_status") == "passed" for row in cards),
            "pending_paper_approvals": sum(row.get("status") == "pending_paper_approval" for row in promotions),
            "paper_observing": sum(row.get("status") == "paper_observing" for row in promotions),
            "review_requests": sum(row.get("status", "open") == "open" for row in reviews),
        },
        "mandates": mandates, "jobs": jobs, "paper_promotions": promotions,
        "paper_review_requests": reviews, "strategy_cards": cards,
        "portfolio_review": data["portfolio"],
    }


@router.get("/summary", summary="读取 HyperTrade 研究工作台真实摘要")
async def summary(request: Request):
    return ok(await _summary_payload(request))


@router.get("/mandates")
async def list_mandates(request: Request):
    return ok(await _call("GET", "/api/research/mandates", request, action="list_mandates"))


@router.post("/mandates")
async def create_mandate(payload: MandateCreateRequest, request: Request):
    upstream = payload.model_dump(exclude={"reason", "idempotency_key"})
    return ok(await _call("POST", "/api/research/mandates", request, action="create_mandate", reason=payload.reason, idempotency_key=payload.idempotency_key, payload=upstream))


@router.post("/mandates/{mandate_id}/pause")
async def pause_mandate(mandate_id: str, payload: WriteRequest, request: Request):
    return ok(await _call("POST", f"/api/research/mandates/{mandate_id}/pause", request, action="pause_mandate", reason=payload.reason, idempotency_key=payload.idempotency_key))


@router.post("/mandates/{mandate_id}/resume")
async def resume_mandate(mandate_id: str, payload: WriteRequest, request: Request):
    return ok(await _call("POST", f"/api/research/mandates/{mandate_id}/resume", request, action="resume_mandate", reason=payload.reason, idempotency_key=payload.idempotency_key))


@router.post("/mandates/{mandate_id}/strategy-specs/draft")
async def draft_strategy_spec(mandate_id: str, payload: StrategySpecDraftRequest, request: Request):
    return ok(await _call("POST", f"/api/research/mandates/{mandate_id}/strategy-specs/draft", request, action="draft_strategy_spec", reason=payload.reason, idempotency_key=payload.idempotency_key, payload={"prompt": payload.prompt}))


@router.get("/jobs")
async def list_jobs(request: Request, mandate_id: str = "", status: str = ""):
    return ok(await _call("GET", "/api/research/jobs", request, action="list_jobs", query={"mandate_id": mandate_id, "status": status}))


@router.post("/mandates/{mandate_id}/jobs")
async def create_job(mandate_id: str, payload: ResearchJobCreateRequest, request: Request):
    return ok(await _call("POST", f"/api/research/mandates/{mandate_id}/jobs", request, action="create_research_job", reason=payload.reason, idempotency_key=payload.idempotency_key, payload={"prompt": payload.prompt, "idempotency_key": payload.idempotency_key, "source_run_id": payload.source_run_id}))


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request):
    return ok(await _call("GET", f"/api/research/jobs/{job_id}", request, action="get_research_job"))


@router.get("/jobs/{job_id}/report")
async def get_job_report(job_id: str, request: Request):
    return ok(await _call("GET", f"/api/research/jobs/{job_id}/report", request, action="get_research_report"))


@router.post("/jobs/{job_id}/run")
async def run_job(job_id: str, payload: WriteRequest, request: Request):
    return ok(await _call("POST", f"/api/research/jobs/{job_id}/run", request, action="run_research_job", reason=payload.reason, idempotency_key=payload.idempotency_key))


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, payload: ResearchJobCancelRequest, request: Request):
    return ok(await _call("POST", f"/api/research/jobs/{job_id}/cancel", request, action="cancel_research_job", reason=payload.reason, idempotency_key=payload.idempotency_key, payload={"reason": payload.reason}))


@router.get("/candidates")
async def list_candidates(request: Request, limit: int = Query(default=24, ge=1, le=50)):
    jobs_response = await _call("GET", "/api/research/jobs", request, action="list_candidate_jobs")
    jobs = _items(jobs_response)[:limit]
    reports = await asyncio.gather(*[
        _call("GET", f"/api/research/jobs/{job['id']}/report", request, action="get_candidate_report")
        for job in jobs if job.get("id")
    ], return_exceptions=True)
    candidates: list[dict[str, Any]] = []
    report_errors: list[str] = []
    for report in reports:
        if isinstance(report, Exception):
            report_errors.append(_safe_text(report))
            continue
        if not isinstance(report, dict):
            continue
        job = report.get("job") if isinstance(report.get("job"), dict) else {}
        evidence_rows = report.get("evidence") if isinstance(report.get("evidence"), list) else []
        for evidence in evidence_rows:
            if not isinstance(evidence, dict):
                continue
            candidates.append({
                **evidence,
                "job": job,
                "data_gaps": list(evidence.get("data_gaps") or evidence.get("rejection_reasons") or []),
                "backtest_references": dict(evidence.get("result_refs") or {}),
            })
    return ok({"items": candidates, "report_errors": report_errors})


async def _verify_passing_evidence(request: Request, *, job_id: str, evidence_id: str) -> None:
    report = await _call("GET", f"/api/research/jobs/{job_id}/report", request, action="verify_paper_promotion_evidence")
    evidence = next((row for row in report.get("evidence", []) if isinstance(row, dict) and str(row.get("id")) == evidence_id), None) if isinstance(report, dict) else None
    gates = dict(evidence.get("gate_results") or {}) if evidence else {}
    if not evidence or evidence.get("status") != "evidence_recorded" or not gates or not all(gates.values()):
        raise HTTPException(status_code=409, detail={"code": "EVIDENCE_NOT_ELIGIBLE", "message": "只有完整通过验证并已记录证据的候选可申请模拟盘"})


@router.get("/paper-promotions")
async def list_paper_promotions(request: Request, status: str = ""):
    return ok(await _call("GET", "/api/research/paper-promotions", request, action="list_paper_promotions", query={"status": status}))


@router.post("/paper-promotions")
async def request_paper_promotion(payload: PaperPromotionRequest, request: Request):
    await _verify_passing_evidence(request, job_id=payload.job_id, evidence_id=payload.evidence_id)
    return ok(await _call("POST", "/api/research/paper-promotions", request, action="request_paper_promotion", reason=payload.reason, idempotency_key=payload.idempotency_key, payload={"evidence_id": payload.evidence_id, "reason": payload.reason}))


@router.get("/paper-promotions/{promotion_id}")
async def get_paper_promotion(promotion_id: str, request: Request):
    return ok(await _call("GET", f"/api/research/paper-promotions/{promotion_id}", request, action="get_paper_promotion"))


@router.post("/paper-promotions/{promotion_id}/approve")
async def approve_paper_promotion(promotion_id: str, payload: PaperApprovalRequest, request: Request):
    return ok(await _call("POST", f"/api/research/paper-promotions/{promotion_id}/approve", request, action="approve_paper_promotion", reason=payload.reason, idempotency_key=payload.idempotency_key, payload={"reason": payload.reason, "idempotency_key": payload.idempotency_key}))


@router.post("/paper-promotions/{promotion_id}/observe")
async def observe_paper_promotion(promotion_id: str, payload: WriteRequest, request: Request):
    return ok(await _call("POST", f"/api/research/paper-promotions/{promotion_id}/observe", request, action="observe_paper_promotion", reason=payload.reason, idempotency_key=payload.idempotency_key))


@router.post("/paper-observations/sample")
async def sample_paper_observations(payload: WriteRequest, request: Request):
    return ok(await _call("POST", "/api/research/paper-observations/sample", request, action="sample_paper_observations", reason=payload.reason, idempotency_key=payload.idempotency_key))


@router.get("/paper-review-requests")
async def list_paper_review_requests(request: Request, status: str = "open"):
    response = await _call("GET", "/api/research/paper-review-requests", request, action="list_paper_review_requests", query={"status": status})
    return ok({"items": _review_items(response)})


@router.get("/strategy-cards")
async def list_strategy_cards(request: Request):
    return ok(await _call("GET", "/api/research/strategy-cards", request, action="list_strategy_cards"))


@router.get("/portfolio-review")
async def get_portfolio_review(request: Request):
    """Read-only StrategyCard portfolio review; it exposes no defensive-action write route."""
    return ok(await _call("GET", "/api/world-model/portfolio", request, action="get_portfolio_review"))
