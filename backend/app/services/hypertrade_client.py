"""Thin HyperTrade transport for the ARC console. No research logic, no cache."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid
from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import AppError

SERVICE_TOKEN_HEADER = "X-HyperTrade-Service-Token"
OPERATOR_ASSERTION_HEADER = "X-Operator-Assertion"


class HyperTradeClientError(AppError):
    code = "HYPERTRADE_UNREACHABLE"
    status_code = 502

    def __init__(self, message: str, *, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def hypertrade_base_url() -> str:
    return str(settings.HYPERTRADE_BASE_URL or settings.HYPERTRADE_API_BASE or "").strip().rstrip("/")


def hypertrade_console_status() -> dict[str, bool]:
    return {
        "configured": bool(
            hypertrade_base_url()
            and str(settings.HYPERTRADE_SERVICE_TOKEN or "").strip()
        ),
        "base_url_set": bool(hypertrade_base_url()),
        "token_set": bool(str(settings.HYPERTRADE_SERVICE_TOKEN or "").strip()),
        "signing_secret_set": bool(
            str(settings.HYPERTRADE_APPROVAL_SIGNING_SECRET or "").strip()
        ),
    }


def sign_operator_assertion(
    *,
    mission_id: str,
    decision: str,
    operator_id: str,
    idempotency_key: str,
    issued_at: int,
    secret: str,
) -> str:
    """Mirror of HyperTrade ``sign_operator_assertion``. Change both together."""
    payload = f"v1|{mission_id}|{decision}|{operator_id}|{idempotency_key}|{issued_at}"
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256)
    encoded_operator = base64.urlsafe_b64encode(operator_id.encode("utf-8")).decode("ascii")
    return f"v1:{issued_at}:{encoded_operator}:{signature.hexdigest()}"


class HyperTradeClient:
    def _require_config(self) -> tuple[str, str]:
        base = hypertrade_base_url()
        token = str(settings.HYPERTRADE_SERVICE_TOKEN or "").strip()
        if not base or not token:
            raise HyperTradeClientError(
                "HyperTrade 未配置",
                code="HYPERTRADE_UNAVAILABLE",
                status_code=503,
            )
        return base, token

    async def create_mission(self, **payload: Any) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/arc/missions", json=payload)

    async def list_missions(self, *, state: str | None, limit: int) -> dict[str, Any]:
        query: dict[str, Any] = {"limit": limit}
        if state:
            query["state"] = state
        return await self._request("GET", "/api/v1/arc/missions", params=query)

    async def get_progress(self, mission_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/api/v1/arc/missions/{mission_id}/progress")

    async def get_evidence(self, mission_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/api/v1/arc/missions/{mission_id}/evidence")

    async def get_candidate(self, mission_id: str, attempt_id: str) -> dict[str, Any]:
        return await self._request(
            "GET", f"/api/v1/arc/missions/{mission_id}/candidates/{attempt_id}"
        )

    async def decide(
        self,
        mission_id: str,
        *,
        decision: str,
        reason: str,
        operator_id: str,
        idempotency_key: str,
        force: bool = False,
    ) -> dict[str, Any]:
        secret = str(settings.HYPERTRADE_APPROVAL_SIGNING_SECRET or "").strip()
        if not secret:
            raise HyperTradeClientError(
                "HyperTrade 审批签名密钥未配置",
                code="HYPERTRADE_UNAVAILABLE",
                status_code=503,
            )
        issued_at = int(time.time())
        assertion = sign_operator_assertion(
            mission_id=mission_id,
            decision=decision,
            operator_id=operator_id,
            idempotency_key=idempotency_key,
            issued_at=issued_at,
            secret=secret,
        )
        return await self._request(
            "POST",
            f"/api/v1/arc/missions/{mission_id}/live-approval/decide",
            json={"decision": decision, "reason": reason, "force": force},
            extra_headers={
                OPERATOR_ASSERTION_HEADER: assertion,
                "Idempotency-Key": idempotency_key,
            },
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        base, token = self._require_config()
        headers = {SERVICE_TOKEN_HEADER: token, **(extra_headers or {})}
        timeout = max(1.0, float(settings.HYPERTRADE_REQUEST_TIMEOUT_SEC))
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.request(
                    method,
                    f"{base}{path}",
                    headers=headers,
                    json=json,
                    params=params,
                )
        except httpx.TimeoutException as exc:
            raise HyperTradeClientError(
                "HyperTrade 请求超时",
                code="HYPERTRADE_UNREACHABLE",
                status_code=504,
            ) from exc
        except httpx.HTTPError as exc:
            raise HyperTradeClientError(
                "HyperTrade 服务不可达",
                code="HYPERTRADE_UNREACHABLE",
                status_code=502,
            ) from exc
        if response.status_code in {401, 403}:
            raise HyperTradeClientError(
                "HyperTrade 拒绝了该凭据",
                code="HYPERTRADE_UNAUTHORIZED",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            detail = _safe_detail(response)
            raise HyperTradeClientError(
                detail or "HyperTrade 拒绝了该请求",
                code="HYPERTRADE_REJECTED",
                status_code=response.status_code,
            )
        body = response.json()
        if not isinstance(body, dict):
            raise HyperTradeClientError(
                "HyperTrade 返回了无法识别的载荷",
                code="HYPERTRADE_UNREACHABLE",
                status_code=502,
            )
        return body


def new_idempotency_key() -> str:
    return f"bp-arc-{uuid.uuid4().hex}"


def _safe_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return str(response.text or "")[:500]
    if isinstance(body, dict):
        detail = body.get("detail") or body.get("message")
        if isinstance(detail, dict):
            return str(detail.get("message") or detail.get("code") or "")[:500]
        return str(detail or "")[:500]
    return str(body)[:500]
