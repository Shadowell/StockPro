"""Auditable A-share AI research workbench boundary."""
from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import quote

import httpx
import psycopg2
import psycopg2.extras
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import ValidationError

from app.core.config import settings
from app.core.contracts import ok
from app.db import db_instance as db


router = APIRouter()


class ProxyFailure(Exception):
    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


class WriteRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=200)


def _redact(value: Any) -> str:
    text = str(value)
    for token in ("authorization=", "Cookie=", "api_key=", "token="):
        if token in text:
            text = text.replace(token + text.split(token, 1)[1].split()[0], token + "[已脱敏]")
    return text[:1000]


def _provider_snapshot() -> dict[str, Any]:
    model = settings.AI_AGENT_MODEL or settings.QWEN_MODEL
    configured = bool(settings.DASHSCOPE_API_KEY or settings.QWEN_API_KEY)
    return {
        "provider_key": "dashscope" if configured else "",
        "provider_name": "DashScope" if configured else "Not configured",
        "model": model if configured else "",
        "api_key_configured": configured,
        "status": "configured" if configured else "missing",
        "setup_path": "/settings",
    }


def _operator_id(request: Request) -> str:
    auth = getattr(request.state, "auth", None) or {}
    return str(auth.get("session_id") or auth.get("role") or "local_operator")


def _write_context(payload: dict[str, Any]) -> tuple[str, str]:
    try:
        parsed = WriteRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "WRITE_CONTEXT_REQUIRED", "message": "写操作必须提供 reason 和 idempotency_key"},
        ) from exc
    return parsed.reason, parsed.idempotency_key


def _proxy_error(exc: ProxyFailure) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.detail})


def _review_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    allowed = {"request_paper_review", "request_pause_review", "retire_candidate_review"}
    return [item for item in payload.get("items") or [] if item.get("action") in allowed]


class ResearchWorkbenchProxy:
    async def request(
        self,
        method: str,
        path: str,
        *,
        operator_id: str = "",
        action: str = "",
        reason: str = "",
        idempotency_key: str = "",
        payload: dict[str, Any] | None = None,
    ) -> Any:
        request_id = f"rw_{uuid.uuid4().hex}"
        base_url = settings.HYPERTRADE_API_BASE or settings.HYPERTRADE_BASE_URL
        cookie = settings.HYPERTRADE_ADMIN_SESSION_COOKIE
        if not base_url or not cookie:
            db.record_research_workbench_audit(
                request_id=request_id,
                operator_id=operator_id,
                action=action,
                upstream_path=path,
                reason=reason,
                idempotency_key=idempotency_key,
                success=False,
                status_code=502,
                error_code="HYPERTRADE_CONFIG_MISSING",
            )
            raise ProxyFailure(502, "HYPERTRADE_CONFIG_MISSING", "服务器环境配置缺失；使用 StockPro 本地研究台账")

        headers = {
            "X-BitPro-Operator": operator_id,
            "X-BitPro-Reason": quote(reason, safe=""),
            "X-BitPro-Reason-Encoding": "utf-8-percent-encoded",
            "Idempotency-Key": idempotency_key,
            "Cookie": cookie,
        }
        status_code: int | None = None
        returned_object_id = ""
        try:
            async with httpx.AsyncClient(timeout=settings.HYPERTRADE_REQUEST_TIMEOUT_SEC, trust_env=False) as client:
                response = await client.request(method=method, url=f"{base_url.rstrip('/')}{path}", headers=headers, json=payload)
            status_code = response.status_code
            data = response.json()
            if isinstance(data, dict):
                returned_object_id = str(data.get("id") or data.get("task_id") or data.get("job_id") or "")
            if response.status_code >= 400:
                detail = data.get("detail") if isinstance(data, dict) else data
                raise ProxyFailure(response.status_code, "HYPERTRADE_REJECTED", _redact(detail))
            db.record_research_workbench_audit(
                request_id=request_id,
                operator_id=operator_id,
                action=action,
                upstream_path=path,
                reason=reason,
                idempotency_key=idempotency_key,
                returned_object_id=returned_object_id,
                status_code=status_code,
                success=True,
            )
            return data
        except ProxyFailure as exc:
            db.record_research_workbench_audit(
                request_id=request_id,
                operator_id=operator_id,
                action=action,
                upstream_path=path,
                reason=reason,
                idempotency_key=idempotency_key,
                status_code=exc.status_code,
                success=False,
                error_code=exc.code,
            )
            raise
        except UnicodeEncodeError as exc:
            db.record_research_workbench_audit(
                request_id=request_id,
                operator_id=operator_id,
                action=action,
                upstream_path=path,
                reason=reason,
                idempotency_key=idempotency_key,
                success=False,
                status_code=502,
                error_code="HYPERTRADE_PROXY_ENCODING_ERROR",
            )
            raise ProxyFailure(502, "HYPERTRADE_PROXY_ENCODING_ERROR", _redact(exc)) from exc
        except httpx.TimeoutException as exc:
            db.record_research_workbench_audit(
                request_id=request_id,
                operator_id=operator_id,
                action=action,
                upstream_path=path,
                reason=reason,
                idempotency_key=idempotency_key,
                success=False,
                status_code=504,
                error_code="HYPERTRADE_TIMEOUT",
            )
            raise ProxyFailure(504, "HYPERTRADE_TIMEOUT", "上游研究服务超时") from exc


proxy = ResearchWorkbenchProxy()


class ResearchLedger:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or settings.DATABASE_URL

    def _connect(self, *, readonly: bool):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required")
        connection = psycopg2.connect(self.database_url)
        connection.set_session(readonly=readonly, autocommit=False)
        return connection

    @staticmethod
    def _table_ready(cursor) -> bool:
        cursor.execute("SELECT to_regclass('public.research_workbench_mandates')")
        row = cursor.fetchone()
        if isinstance(row, dict):
            return next(iter(row.values())) is not None
        return row[0] is not None

    @staticmethod
    def _json(row: dict[str, Any], key: str) -> Any:
        value = row.get(key)
        return value if value is not None else {}

    def summary(self) -> dict[str, Any]:
        provider = _provider_snapshot()
        try:
            connection = self._connect(readonly=True)
            try:
                with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    if not self._table_ready(cursor):
                        return self._empty_summary(provider, "migration_pending")
                    cursor.execute("SELECT COUNT(*) AS count FROM research_workbench_mandates")
                    mandates = int(dict(cursor.fetchone() or {}).get("count") or 0)
                    cursor.execute("SELECT * FROM research_workbench_jobs ORDER BY created_at DESC LIMIT 20")
                    jobs = [dict(row) for row in cursor.fetchall()]
                    cursor.execute("SELECT * FROM research_workbench_paper_promotions ORDER BY created_at DESC LIMIT 20")
                    promotions = [dict(row) for row in cursor.fetchall()]
            finally:
                connection.rollback()
                connection.close()
        except Exception as exc:
            payload = self._empty_summary(provider, "storage_unavailable")
            payload["connection"]["error"] = str(exc)[:240]
            return payload
        return {
            "connection": {
                "status": "ready",
                "mode": "local_postgres_ledger",
                "upstream_status": "configured" if settings.HYPERTRADE_API_BASE else "unavailable",
                "error": None,
            },
            "provider": provider,
            "write_path": {
                "status": "provider_required" if not provider["api_key_configured"] else "ready",
                "stores_input_output_cost_version": True,
                "paper_mutation": False,
            },
            "jobs": jobs,
            "paper_promotions": promotions,
            "paper_review_requests": _review_items({"items": promotions}),
            "metrics": {"mandates": mandates, "jobs": len(jobs), "paper_promotions": len(promotions)},
        }

    @staticmethod
    def _empty_summary(provider: dict[str, Any], status: str) -> dict[str, Any]:
        return {
            "connection": {
                "status": "unavailable",
                "mode": "local_postgres_ledger",
                "upstream_status": "unavailable",
                "error": "服务器环境配置缺失；本地研究台账等待数据库迁移" if status == "migration_pending" else status,
            },
            "provider": provider,
            "write_path": {"status": status, "stores_input_output_cost_version": True, "paper_mutation": False},
            "jobs": [],
            "paper_promotions": [],
            "paper_review_requests": [],
            "metrics": {},
        }

    def candidates(self) -> dict[str, Any]:
        try:
            connection = self._connect(readonly=True)
            try:
                with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    if not self._table_ready(cursor):
                        return {"items": [], "report_errors": ["research_workbench_mandates table is not migrated"]}
                    cursor.execute("SELECT * FROM research_workbench_candidates ORDER BY created_at DESC LIMIT 50")
                    return {"items": [dict(row) for row in cursor.fetchall()], "report_errors": []}
            finally:
                connection.rollback()
                connection.close()
        except Exception as exc:
            return {"items": [], "report_errors": [str(exc)[:240]]}

    def create_mandate(self, payload: dict[str, Any]) -> dict[str, Any]:
        reason, idempotency_key = _write_context(payload)
        provider = _provider_snapshot()
        mandate_id = f"mandate_{uuid.uuid4().hex[:12]}"
        name = str(payload.get("name") or "A 股研究提议")[:160]
        connection = self._connect(readonly=False)
        try:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO research_workbench_mandates
                    (id,name,status,request_json,provider_snapshot,reason,idempotency_key)
                    VALUES (%s,%s,'active',%s,%s,%s,%s)
                    ON CONFLICT (idempotency_key) DO UPDATE SET updated_at=NOW()
                    RETURNING *
                    """,
                    (
                        mandate_id,
                        name,
                        psycopg2.extras.Json(payload),
                        psycopg2.extras.Json(provider),
                        reason,
                        idempotency_key,
                    ),
                )
                row = dict(cursor.fetchone())
            connection.commit()
            return row
        finally:
            connection.close()

    def create_job(self, mandate_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        reason, idempotency_key = _write_context(payload)
        provider = _provider_snapshot()
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        connection = self._connect(readonly=False)
        try:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO research_workbench_jobs
                    (id,mandate_id,status,request_json,provider_snapshot,reason,idempotency_key)
                    VALUES (%s,%s,'created',%s,%s,%s,%s)
                    ON CONFLICT (idempotency_key) DO UPDATE SET updated_at=NOW()
                    RETURNING *
                    """,
                    (
                        job_id,
                        mandate_id,
                        psycopg2.extras.Json(payload),
                        psycopg2.extras.Json(provider),
                        reason,
                        idempotency_key,
                    ),
                )
                row = dict(cursor.fetchone())
            connection.commit()
            return {"job": row}
        finally:
            connection.close()

    def run_job(self, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        _write_context(payload)
        provider = _provider_snapshot()
        status = "failed" if not provider["api_key_configured"] else "queued"
        error = None if provider["api_key_configured"] else "LLM Provider not configured"
        output = {
            "provider_status": provider["status"],
            "result_saved": False,
            "candidate_created": False,
        }
        connection = self._connect(readonly=False)
        try:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    UPDATE research_workbench_jobs
                    SET status=%s,output_json=%s,cost_json=%s,error_message=%s,
                        started_at=COALESCE(started_at,NOW()),finished_at=CASE WHEN %s='failed' THEN NOW() ELSE finished_at END,
                        updated_at=NOW()
                    WHERE id=%s
                    RETURNING *
                    """,
                    (
                        status,
                        psycopg2.extras.Json(output),
                        psycopg2.extras.Json({"currency": "CNY", "total": 0, "provider_billable": False}),
                        error,
                        status,
                        job_id,
                    ),
                )
                row = cursor.fetchone()
            connection.commit()
        finally:
            connection.close()
        if row is None:
            raise HTTPException(status_code=404, detail="研究任务不存在")
        return {"job": dict(row)}


ledger = ResearchLedger()


@router.get("/summary")
async def summary():
    return ok(ledger.summary())


@router.get("/candidates")
async def candidates():
    return ok(ledger.candidates())


@router.get("/mandates")
async def mandates(request: Request):
    try:
        return ok(await proxy.request("GET", "/api/research/mandates", operator_id=_operator_id(request), action="list_mandates"))
    except ProxyFailure as exc:
        if exc.code == "HYPERTRADE_CONFIG_MISSING":
            return ok({"items": []})
        raise _proxy_error(exc) from exc


@router.post("/mandates")
async def create_mandate(payload: dict[str, Any], request: Request):
    try:
        return ok(await proxy.request("POST", "/api/research/mandates", operator_id=_operator_id(request), action="create_mandate", reason=str(payload.get("reason") or ""), idempotency_key=str(payload.get("idempotency_key") or ""), payload=payload))
    except ProxyFailure as exc:
        if exc.code == "HYPERTRADE_CONFIG_MISSING":
            return ok(ledger.create_mandate(payload))
        raise _proxy_error(exc) from exc


@router.post("/mandates/{mandate_id}/pause")
async def pause_mandate(mandate_id: str, payload: dict[str, Any], request: Request):
    reason, idempotency_key = _write_context(payload)
    try:
        return ok(await proxy.request("POST", f"/api/research/mandates/{mandate_id}/pause", operator_id=_operator_id(request), action="pause_mandate", reason=reason, idempotency_key=idempotency_key, payload=payload))
    except ProxyFailure as exc:
        raise _proxy_error(exc) from exc


@router.post("/mandates/{mandate_id}/resume")
async def resume_mandate(mandate_id: str, payload: dict[str, Any], request: Request):
    reason, idempotency_key = _write_context(payload)
    try:
        return ok(await proxy.request("POST", f"/api/research/mandates/{mandate_id}/resume", operator_id=_operator_id(request), action="resume_mandate", reason=reason, idempotency_key=idempotency_key, payload=payload))
    except ProxyFailure as exc:
        raise _proxy_error(exc) from exc


@router.post("/mandates/{mandate_id}/strategy-specs/draft")
async def draft_strategy_spec(mandate_id: str, payload: dict[str, Any], request: Request):
    reason, idempotency_key = _write_context(payload)
    try:
        return ok(await proxy.request("POST", f"/api/research/mandates/{mandate_id}/strategy-specs/draft", operator_id=_operator_id(request), action="draft_strategy_spec", reason=reason, idempotency_key=idempotency_key, payload=payload))
    except ProxyFailure as exc:
        raise _proxy_error(exc) from exc


@router.post("/mandates/{mandate_id}/jobs")
async def create_job(mandate_id: str, payload: dict[str, Any], request: Request):
    try:
        return ok(await proxy.request("POST", f"/api/research/mandates/{mandate_id}/jobs", operator_id=_operator_id(request), action="create_job", reason=str(payload.get("reason") or ""), idempotency_key=str(payload.get("idempotency_key") or ""), payload=payload))
    except ProxyFailure as exc:
        if exc.code == "HYPERTRADE_CONFIG_MISSING":
            return ok(ledger.create_job(mandate_id, payload))
        raise _proxy_error(exc) from exc


@router.post("/jobs/{job_id}/run")
async def run_job(job_id: str, payload: dict[str, Any], request: Request):
    try:
        return ok(await proxy.request("POST", f"/api/research/jobs/{job_id}/run", operator_id=_operator_id(request), action="run_job", reason=str(payload.get("reason") or ""), idempotency_key=str(payload.get("idempotency_key") or ""), payload=payload))
    except ProxyFailure as exc:
        if exc.code == "HYPERTRADE_CONFIG_MISSING":
            return ok(ledger.run_job(job_id, payload))
        raise _proxy_error(exc) from exc


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, payload: dict[str, Any], request: Request):
    reason, idempotency_key = _write_context(payload)
    try:
        return ok(await proxy.request("POST", f"/api/research/jobs/{job_id}/cancel", operator_id=_operator_id(request), action="cancel_job", reason=reason, idempotency_key=idempotency_key, payload=payload))
    except ProxyFailure as exc:
        raise _proxy_error(exc) from exc


def _evidence_eligible(report: dict[str, Any], evidence_id: str) -> bool:
    for item in report.get("evidence") or []:
        if str(item.get("id")) != str(evidence_id):
            continue
        gates = item.get("gate_results") or {}
        return bool(gates) and all(bool(value) for value in gates.values()) and item.get("status") not in {"rejected", "failed"}
    return False


@router.post("/paper-promotions")
async def request_paper_promotion(payload: dict[str, Any], request: Request):
    reason, idempotency_key = _write_context(payload)
    job_id = str(payload.get("job_id") or "")
    evidence_id = str(payload.get("evidence_id") or "")
    try:
        report = await proxy.request("GET", f"/api/research/jobs/{job_id}/report", operator_id=_operator_id(request), action="read_job_report")
        if not _evidence_eligible(report, evidence_id):
            raise HTTPException(status_code=409, detail={"code": "EVIDENCE_NOT_ELIGIBLE", "message": "研究证据未通过全部门禁"})
        return ok(await proxy.request("POST", "/api/research/paper-promotions", operator_id=_operator_id(request), action="request_paper_promotion", reason=reason, idempotency_key=idempotency_key, payload=payload))
    except ProxyFailure as exc:
        raise _proxy_error(exc) from exc


@router.post("/paper-promotions/{promotion_id}/approve")
async def approve_paper_promotion(promotion_id: str, payload: dict[str, Any], request: Request):
    reason, idempotency_key = _write_context(payload)
    try:
        return ok(await proxy.request("POST", f"/api/research/paper-promotions/{promotion_id}/approve", operator_id=_operator_id(request), action="approve_paper_promotion", reason=reason, idempotency_key=idempotency_key, payload=payload))
    except ProxyFailure as exc:
        raise _proxy_error(exc) from exc


@router.post("/paper-promotions/{promotion_id}/observe")
async def observe_paper_promotion(promotion_id: str, payload: dict[str, Any], request: Request):
    reason, idempotency_key = _write_context(payload)
    try:
        return ok(await proxy.request("POST", f"/api/research/paper-promotions/{promotion_id}/observe", operator_id=_operator_id(request), action="observe_paper_promotion", reason=reason, idempotency_key=idempotency_key, payload=payload))
    except ProxyFailure as exc:
        raise _proxy_error(exc) from exc


@router.post("/paper-observations/sample")
async def sample_paper_observations(payload: dict[str, Any]):
    _write_context(payload)
    return ok({"items": [], "data_status": "unavailable", "message": "没有已批准的 A 股 Paper 观察样本"})


@router.get("/portfolio-review")
async def portfolio_review():
    return ok({"items": [], "data_status": "unavailable", "message": "没有可复盘的 A 股 Paper 组合"})
