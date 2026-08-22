"""API contract helpers for v2 endpoints."""
from __future__ import annotations

from typing import Any, Dict, Optional


def ok(data: Any = None, *, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return success envelope."""
    payload: Dict[str, Any] = {"success": True, "data": data}
    if meta is not None:
        payload["meta"] = meta
    return payload


def fail(code: str, message: str, *, details: Any = None) -> Dict[str, Any]:
    """Return error envelope."""
    error: Dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"success": False, "error": error}


def page_meta(*, total: int, offset: int, limit: int) -> Dict[str, int]:
    """Build pagination metadata."""
    return {"total": int(total), "offset": int(offset), "limit": int(limit)}
