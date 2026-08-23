"""Regression coverage for the BitPro-only HyperTrade research proxy."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.v2.endpoints import research_workbench  # noqa: E402
from app.core.auth_middleware import AuthMiddleware  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.errors import register_exception_handlers  # noqa: E402


def build_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(settings, "BITPRO_AUTH_ENABLED", False, raising=False)
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(research_workbench.router, prefix="/api/v2/research-workbench")
    register_exception_handlers(app)
    return TestClient(app, raise_server_exceptions=False)


def test_proxy_maps_operator_headers_and_audits_without_exposing_cookie(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    audit: list[dict[str, Any]] = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"id": "mandate_1"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def request(self, **kwargs):
            captured.update(kwargs)
            return FakeResponse()

    monkeypatch.setattr(settings, "HYPERTRADE_API_BASE", "https://hypertrade.internal", raising=False)
    monkeypatch.setattr(settings, "HYPERTRADE_ADMIN_SESSION_COOKIE", "hypertrade_session=server-only-secret", raising=False)
    monkeypatch.setattr(research_workbench.httpx, "AsyncClient", lambda **_: FakeClient())
    monkeypatch.setattr(research_workbench.db, "record_research_workbench_audit", lambda **kwargs: audit.append(kwargs))

    result = asyncio.run(
        research_workbench.proxy.request(
            "POST",
            "/api/research/mandates",
            operator_id="session_123",
            action="create_mandate",
            reason="验证研究章程",
            idempotency_key="idem-create-mandate-001",
            payload={"name": "研究章程"},
        )
    )

    assert result == {"id": "mandate_1"}
    assert captured["url"] == "https://hypertrade.internal/api/research/mandates"
    assert captured["headers"]["X-BitPro-Operator"] == "session_123"
    assert captured["headers"]["X-BitPro-Reason"] == quote("验证研究章程", safe="")
    assert captured["headers"]["X-BitPro-Reason-Encoding"] == "utf-8-percent-encoded"
    assert captured["headers"]["X-BitPro-Reason"].isascii()
    assert captured["headers"]["Idempotency-Key"] == "idem-create-mandate-001"
    assert captured["headers"]["Cookie"] == "hypertrade_session=server-only-secret"
    assert audit[0]["returned_object_id"] == "mandate_1"
    assert audit[0]["reason"] == "验证研究章程"
    assert "server-only-secret" not in str(audit[0])


def test_proxy_maps_header_encoding_error_to_a_controlled_failure(monkeypatch) -> None:
    class EncodingFailureClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def request(self, **kwargs):
            raise UnicodeEncodeError("ascii", "中文", 0, 1, "ordinal not in range")

    audit: list[dict[str, Any]] = []
    monkeypatch.setattr(settings, "HYPERTRADE_API_BASE", "https://hypertrade.internal", raising=False)
    monkeypatch.setattr(settings, "HYPERTRADE_ADMIN_SESSION_COOKIE", "hypertrade_session=server-only-secret", raising=False)
    monkeypatch.setattr(research_workbench.httpx, "AsyncClient", lambda **_: EncodingFailureClient())
    monkeypatch.setattr(research_workbench.db, "record_research_workbench_audit", lambda **kwargs: audit.append(kwargs))

    try:
        asyncio.run(
            research_workbench.proxy.request(
                "POST", "/api/research/mandates", operator_id="session_123", action="create_mandate", reason="创建受控研究章程"
            )
        )
    except research_workbench.ProxyFailure as exc:
        assert exc.status_code == 502
        assert exc.code == "HYPERTRADE_PROXY_ENCODING_ERROR"
    else:
        raise AssertionError("expected header encoding failure to become a controlled proxy failure")

    assert audit[0]["reason"] == "创建受控研究章程"
    assert audit[0]["error_code"] == "HYPERTRADE_PROXY_ENCODING_ERROR"


def test_summary_returns_real_unavailable_reason_when_server_config_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(settings, "HYPERTRADE_API_BASE", None, raising=False)
    monkeypatch.setattr(settings, "HYPERTRADE_ADMIN_SESSION_COOKIE", None, raising=False)
    client = build_client(monkeypatch)

    response = client.get("/api/v2/research-workbench/summary")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["connection"]["status"] == "unavailable"
    assert "服务器环境配置" in payload["connection"]["error"]


def test_proxy_maps_timeout_to_controlled_gateway_timeout(monkeypatch) -> None:
    class TimeoutClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def request(self, **kwargs):
            raise research_workbench.httpx.TimeoutException("upstream timeout")

    audit: list[dict[str, Any]] = []
    monkeypatch.setattr(settings, "HYPERTRADE_API_BASE", "https://hypertrade.internal", raising=False)
    monkeypatch.setattr(settings, "HYPERTRADE_ADMIN_SESSION_COOKIE", "hypertrade_session=server-only-secret", raising=False)
    monkeypatch.setattr(research_workbench.httpx, "AsyncClient", lambda **_: TimeoutClient())
    monkeypatch.setattr(research_workbench.db, "record_research_workbench_audit", lambda **kwargs: audit.append(kwargs))

    try:
        asyncio.run(
            research_workbench.proxy.request(
                "GET", "/api/research/mandates", operator_id="session_123", action="list_mandates"
            )
        )
    except research_workbench.ProxyFailure as exc:
        assert exc.status_code == 504
        assert exc.code == "HYPERTRADE_TIMEOUT"
    else:
        raise AssertionError("expected timeout to become a controlled proxy failure")
    assert audit[0]["error_code"] == "HYPERTRADE_TIMEOUT"


def test_proxy_redacts_upstream_credential_text_before_returning_error(monkeypatch) -> None:
    class RejectedResponse:
        status_code = 409

        def json(self):
            return {"detail": "authorization=top-secret-token gate rejected"}

    class RejectedClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def request(self, **kwargs):
            return RejectedResponse()

    monkeypatch.setattr(settings, "HYPERTRADE_API_BASE", "https://hypertrade.internal", raising=False)
    monkeypatch.setattr(settings, "HYPERTRADE_ADMIN_SESSION_COOKIE", "hypertrade_session=server-only-secret", raising=False)
    monkeypatch.setattr(research_workbench.httpx, "AsyncClient", lambda **_: RejectedClient())

    try:
        asyncio.run(
            research_workbench.proxy.request(
                "POST", "/api/research/mandates", operator_id="session_123", action="create_mandate"
            )
        )
    except research_workbench.ProxyFailure as exc:
        assert exc.status_code == 409
        assert "top-secret-token" not in exc.detail
        assert "[已脱敏]" in exc.detail
    else:
        raise AssertionError("expected controlled HyperTrade rejection")


def test_proxy_preserves_hypertrade_404_409_and_5xx_statuses(monkeypatch) -> None:
    client = build_client(monkeypatch)

    for status in (404, 409, 503):
        async def status_request(*args, _status=status, **kwargs):
            raise research_workbench.ProxyFailure(_status, "HYPERTRADE_REJECTED", f"upstream-{_status}")

        monkeypatch.setattr(research_workbench.proxy, "request", status_request)
        response = client.get("/api/v2/research-workbench/mandates")
        assert response.status_code == status
        assert response.json()["detail"]["message"] == f"upstream-{status}"


def test_writes_require_reason_and_idempotency_key(monkeypatch) -> None:
    client = build_client(monkeypatch)

    response = client.post("/api/v2/research-workbench/mandates/mandate_1/pause", json={})
    approval = client.post("/api/v2/research-workbench/paper-promotions/promotion_1/approve", json={})

    assert response.status_code == 422
    assert approval.status_code == 422


def test_rejected_or_incomplete_evidence_cannot_request_paper_promotion(monkeypatch) -> None:
    client = build_client(monkeypatch)
    calls: list[tuple[str, str]] = []

    async def fake_request(method: str, path: str, **kwargs):
        calls.append((method, path))
        if path.endswith("/report"):
            return {
                "job": {"id": "job_1"},
                "evidence": [{"id": "evidence_1", "status": "rejected", "gate_results": {"validation": False}}],
            }
        raise AssertionError(f"unexpected upstream request: {method} {path}")

    monkeypatch.setattr(research_workbench.proxy, "request", fake_request)
    response = client.post(
        "/api/v2/research-workbench/paper-promotions",
        json={
            "evidence_id": "evidence_1",
            "job_id": "job_1",
            "reason": "申请模拟盘人工审批",
            "idempotency_key": "idem-paper-request-001",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EVIDENCE_NOT_ELIGIBLE"
    assert calls == [("GET", "/api/research/jobs/job_1/report")]


def test_evidence_recorded_without_any_gate_results_cannot_request_paper_promotion(monkeypatch) -> None:
    client = build_client(monkeypatch)

    async def fake_request(method: str, path: str, **kwargs):
        assert method == "GET"
        assert path.endswith("/report")
        return {
            "job": {"id": "job_1"},
            "evidence": [{"id": "evidence_1", "status": "evidence_recorded", "gate_results": {}}],
        }

    monkeypatch.setattr(research_workbench.proxy, "request", fake_request)
    response = client.post(
        "/api/v2/research-workbench/paper-promotions",
        json={
            "evidence_id": "evidence_1",
            "job_id": "job_1",
            "reason": "验证缺失门禁不能晋级",
            "idempotency_key": "idem-empty-gates-001",
        },
    )

    assert response.status_code == 409


def test_review_queue_is_limited_to_human_review_actions() -> None:
    payload = {
        "items": [
            {"id": "review_1", "action": "request_paper_review"},
            {"id": "review_2", "action": "request_pause_review"},
            {"id": "review_3", "action": "retire_candidate_review"},
            {"id": "review_4", "action": "paper_stop"},
        ]
    }

    assert [item["id"] for item in research_workbench._review_items(payload)] == [
        "review_1",
        "review_2",
        "review_3",
    ]


def test_approval_passes_reason_and_unique_idempotency_key_without_direct_paper_control(monkeypatch) -> None:
    client = build_client(monkeypatch)
    captured: dict[str, Any] = {}

    async def fake_request(method: str, path: str, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return {"id": "promotion_1", "status": "paper_observing"}

    monkeypatch.setattr(research_workbench.proxy, "request", fake_request)
    response = client.post(
        "/api/v2/research-workbench/paper-promotions/promotion_1/approve",
        json={"reason": "人工审阅通过", "idempotency_key": "idem-paper-approval-001"},
    )

    assert response.status_code == 200
    assert captured["path"] == "/api/research/paper-promotions/promotion_1/approve"
    assert captured["payload"] == {"reason": "人工审阅通过", "idempotency_key": "idem-paper-approval-001"}
    source = (PROJECT_ROOT / "backend/app/api/v2/endpoints/research_workbench.py").read_text(encoding="utf-8")
    for forbidden in ("paper_pause", "paper_stop", "live_promote", "/order", "/transfer"):
        assert forbidden not in source
