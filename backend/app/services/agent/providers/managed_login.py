"""Async, cached managed-login capability probes for CLI Providers."""

from __future__ import annotations

import asyncio
import inspect
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import BaseModel

from .contracts import ProviderCapabilities
from .registry import ProviderDefinition, ProviderRegistry
from .subprocess_runner import run_subprocess_safely


class ManagedLoginProbeResult(BaseModel):
    provider_key: str
    command_available: bool
    login_verified: bool
    status_detail: str
    error_code: str | None = None
    probed_at: str


_PROBE_ARGV = {
    "codex_cli": ("login", "status"),
    "cursor_cli": ("status",),
}

_POSITIVE_MARKERS = {
    "codex": ("logged in", "authenticated", "using chatgpt"),
    "cursor": ("logged in", "authenticated"),
}

_NEGATIVE_MARKERS = (
    "not logged",
    "logged out",
    "unauthenticated",
    "not authenticated",
    "login required",
    "未登录",
)

_ALLOWED_ENV = {"PATH", "HOME", "CODEX_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"}


class ManagedLoginProbeService:
    def __init__(
        self,
        *,
        runner: Callable[..., Any] | None = None,
        which: Callable[[str], str | None] = shutil.which,
        ttl_sec: float = 60.0,
        timeout_sec: float = 5.0,
    ) -> None:
        self._runner = runner
        self._which = which
        self._ttl_sec = max(float(ttl_sec), 0.0)
        self._timeout_sec = max(float(timeout_sec), 0.1)
        self._cache: dict[str, tuple[float, ManagedLoginProbeResult]] = {}
        self._inflight: dict[str, asyncio.Task[ManagedLoginProbeResult]] = {}
        self._lock = asyncio.Lock()

    async def probe(
        self,
        definition: ProviderDefinition,
        *,
        force: bool = False,
    ) -> ManagedLoginProbeResult:
        key = definition.provider_key
        now = time.monotonic()
        async with self._lock:
            cached = self._cache.get(key)
            if not force and cached is not None and cached[0] > now:
                return cached[1]
            task = self._inflight.get(key)
            if task is None:
                task = asyncio.create_task(self._probe_uncached(definition))
                self._inflight[key] = task
        try:
            result = await asyncio.shield(task)
        finally:
            if task.done():
                async with self._lock:
                    if self._inflight.get(key) is task:
                        self._inflight.pop(key, None)
        async with self._lock:
            self._cache[key] = (time.monotonic() + self._ttl_sec, result)
        return result

    async def _probe_uncached(self, definition: ProviderDefinition) -> ManagedLoginProbeResult:
        probed_at = datetime.now(timezone.utc).isoformat()
        command = str(definition.command or "").strip()
        command_available = bool(command and self._which(command))
        if not command_available:
            return ManagedLoginProbeResult(
                provider_key=definition.provider_key,
                command_available=False,
                login_verified=False,
                status_detail="CLI 未安装",
                error_code="managed_login_command_missing",
                probed_at=probed_at,
            )

        suffix = _PROBE_ARGV.get(definition.transport_type)
        if suffix is None:
            return ManagedLoginProbeResult(
                provider_key=definition.provider_key,
                command_available=True,
                login_verified=False,
                status_detail="CLI 登录探测命令未定义",
                error_code="managed_login_probe_unsupported",
                probed_at=probed_at,
            )

        env = {name: value for name, value in os.environ.items() if name in _ALLOWED_ENV}
        try:
            if self._runner is None:
                completed = await run_subprocess_safely(
                    [command, *suffix],
                    timeout_sec=self._timeout_sec,
                    allowed_env=env,
                    output_limit_bytes=64 * 1024,
                )
            elif inspect.iscoroutinefunction(self._runner):
                completed = await self._runner(
                    [command, *suffix],
                    timeout_sec=self._timeout_sec,
                    allowed_env=env,
                    output_limit_bytes=64 * 1024,
                )
            else:
                completed = await asyncio.to_thread(
                    self._runner,
                    [command, *suffix],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout_sec,
                    shell=False,
                    env=env,
                )
        except asyncio.CancelledError:
            raise
        except (OSError, subprocess.SubprocessError):
            completed = None

        if (
            completed is None
            or bool(getattr(completed, "timed_out", False))
            or bool(getattr(completed, "error_code", None))
        ):
            return ManagedLoginProbeResult(
                provider_key=definition.provider_key,
                command_available=True,
                login_verified=False,
                status_detail="CLI 已发现，但登录状态未验证",
                error_code="managed_login_probe_failed",
                probed_at=probed_at,
            )

        text = f"{getattr(completed, 'stdout', '')} {getattr(completed, 'stderr', '')}".lower()
        markers = _POSITIVE_MARKERS.get(definition.provider_key, ())
        verified = (
            int(getattr(completed, "returncode", 1)) == 0
            and not any(marker in text for marker in _NEGATIVE_MARKERS)
            and any(marker in text for marker in markers)
        )
        return ManagedLoginProbeResult(
            provider_key=definition.provider_key,
            command_available=True,
            login_verified=verified,
            status_detail="CLI 已发现，登录已验证" if verified else "CLI 已发现，但登录状态未验证",
            error_code=None if verified else "managed_login_unverified",
            probed_at=probed_at,
        )


managed_login_probe_service = ManagedLoginProbeService()


def apply_managed_login_result(
    capability: ProviderCapabilities,
    result: ManagedLoginProbeResult,
    *,
    enabled: bool = True,
) -> ProviderCapabilities:
    if capability.provider_key != result.provider_key:
        raise ValueError("Provider 登录探测结果与能力不匹配")
    return capability.model_copy(
        update={
            "configured": bool(enabled and result.command_available and result.login_verified),
            "healthy": bool(enabled and result.login_verified),
            "command_available": result.command_available,
            "login_verified": result.login_verified,
            "status_detail": result.status_detail if enabled else "Provider 已停用",
            "error_code": result.error_code if enabled else "provider_disabled",
            "probed_at": result.probed_at,
        }
    )


async def get_runtime_provider_capabilities(
    registry: ProviderRegistry,
    provider_key: str,
    *,
    force_probe: bool = False,
    service: ManagedLoginProbeService | None = None,
) -> ProviderCapabilities:
    service = service or managed_login_probe_service
    capability = registry.get_capabilities(provider_key)
    if capability.credential_mode != "managed_login":
        return capability
    definition = registry.get_definition(provider_key)
    result = await service.probe(definition, force=force_probe)
    return apply_managed_login_result(capability, result, enabled=definition.enabled)


async def list_runtime_provider_capabilities(
    registry: ProviderRegistry,
    *,
    force_probe: bool = False,
    service: ManagedLoginProbeService | None = None,
) -> list[ProviderCapabilities]:
    service = service or managed_login_probe_service
    capabilities = registry.list_capabilities()
    enriched = await asyncio.gather(
        *(
            get_runtime_provider_capabilities(
                registry,
                capability.provider_key,
                force_probe=force_probe,
                service=service,
            )
            if capability.credential_mode == "managed_login"
            else asyncio.sleep(0, result=capability)
            for capability in capabilities
        )
    )
    return list(enriched)
