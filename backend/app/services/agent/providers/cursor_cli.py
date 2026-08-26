"""Cursor ACP (newline-delimited JSON-RPC) research Provider."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .contracts import (
    ProviderCapabilities,
    ProviderExecutionError,
    ProviderRunRequest,
    ProviderRunResult,
    validate_provider_selection,
)
from .http_client import _strip_json_fence, _validate_json_schema
from .registry import ProviderDefinition
from .subprocess_runner import (
    SubprocessResult,
    run_subprocess_safely,
    spawn_subprocess_safely,
    terminate_subprocess,
)


_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+\-\[\]=,]{1,127}$")
_MODEL_HINT_RE = re.compile(r"(?:\d|auto|gpt|claude|sonnet|opus|gemini|composer|o[134])", re.I)
_MODEL_DIAGNOSTIC_RE = re.compile(r"(?:error|failed|failure|warning|status|diagnostic|truncated|unknown|not[-_ ]found)", re.I)
_IDLE_STATES = {"idle", "end_turn", "completed", "complete", "stopped", "finished", "success"}
_ACP_FRAME_LIMIT_BYTES = 256 * 1024
_ACP_CANCEL_TIMEOUT_SEC = 0.25


class OutputLimitExceeded(Exception):
    """Raised when ACP protocol or diagnostic output exceeds its byte budget."""


@dataclass(slots=True)
class _OutputBudget:
    limit_bytes: int
    consumed_bytes: int = 0

    def consume(self, size: int) -> None:
        self.consumed_bytes += max(0, int(size))
        if self.consumed_bytes > self.limit_bytes:
            raise OutputLimitExceeded


@dataclass(slots=True)
class _CursorRunContext:
    deadline: float
    output_budget: _OutputBudget
    stderr_overflow: asyncio.Event
    session_id: str | None = None

    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())


def build_cursor_argv(*, executable: str, execution: Any) -> list[str]:
    """Build the only supported Cursor invocation: ACP over stdio."""

    return [
        str(executable),
        "--model",
        str(execution.model),
        "--sandbox",
        "enabled",
        "acp",
    ]


def _fallback_capabilities(definition: ProviderDefinition) -> ProviderCapabilities:
    return ProviderCapabilities(
        provider_key=definition.provider_key,
        display_name=definition.display_name,
        transport_type=definition.transport_type,
        credential_mode=definition.credential_mode,
        credential_source="managed_login",
        models=list(definition.models) or [definition.default_model],
        reasoning_efforts=list(definition.reasoning_efforts),
        speed_modes=list(definition.speed_modes),
        supports_tools=definition.supports_tools,
        supports_structured_output=definition.supports_structured_output,
        supports_resume=definition.supports_resume,
        configured=False,
        healthy=False,
        command_available=False,
        login_verified=False,
        status_detail="CLI 能力尚未验证",
        config_revision="sha256:runtime",
        error_code="managed_login_unverified",
    )


@dataclass(frozen=True, slots=True)
class CursorModelProbeResult:
    models: list[str]
    status_detail: str
    error_code: str | None = None
    configured: bool = False
    healthy: bool = False

    def __iter__(self):
        # A small compatibility convenience for callers that want ``models,
        # status = await probe_cursor_models(...)`` without sacrificing named
        # fields for API capability consumers.
        yield self.models
        yield self.status_detail


def _valid_model(value: Any, *, plain_text: bool = False) -> str | None:
    model = str(value or "").strip()
    if not _MODEL_RE.fullmatch(model) or not _MODEL_HINT_RE.search(model):
        return None
    if _MODEL_DIAGNOSTIC_RE.search(model) or (plain_text and ":" in model):
        return None
    return model


def _models_from_json(value: Any) -> list[str]:
    raw_models: Any = value
    if isinstance(value, dict):
        if set(value) - {"models", "model_list", "availableModels", "data", "items", "status", "version"}:
            return []
        status = value.get("status")
        if status is not None and str(status).lower() not in {"ok", "success", "ready"}:
            return []
        for key in ("models", "model_list", "availableModels", "data", "items"):
            if key in value:
                raw_models = value[key]
                break
    if not isinstance(raw_models, list):
        return []
    models: list[str] = []
    for item in raw_models:
        candidate = item
        if isinstance(item, dict):
            if set(item) - {"id", "model", "name", "displayName"}:
                return []
            candidate = item.get("id") or item.get("model") or item.get("name")
        elif not isinstance(item, str):
            return []
        model = _valid_model(candidate)
        if model is None:
            return []
        if model not in models:
            models.append(model)
    return models


def parse_cursor_model_listing(stdout: str) -> list[str]:
    text = str(stdout or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = None
    if parsed is not None:
        # The probe accepts only the documented JSON container shapes.  A
        # syntactically valid diagnostic object is not a model listing.
        if not isinstance(parsed, (dict, list)):
            return []
        return _models_from_json(parsed)
    models: list[str] = []
    lines = [line.strip().lstrip("-*• ").strip() for line in text.splitlines() if line.strip()]
    for candidate in lines:
        model = _valid_model(candidate, plain_text=True)
        if model is None:
            # A mixed listing is ambiguous (for example ``Error:gpt-failed``
            # after a partial success); fail closed instead of returning a
            # potentially stale subset of models.
            return []
        if model and model not in models:
            models.append(model)
    return models


async def probe_cursor_models(
    *,
    executable: str = "agent",
    timeout_sec: float = 10,
    allowed_env: Mapping[str, str] | None = None,
    output_limit_bytes: int = 512 * 1024,
) -> CursorModelProbeResult:
    """Probe ``agent --list-models`` without inventing a fallback model list."""

    with tempfile.TemporaryDirectory(prefix="bitpro-cursor-probe-") as raw_workspace:
        workspace = Path(raw_workspace)
        workspace.chmod(0o700)
        result: SubprocessResult = await run_subprocess_safely(
            [executable, "--list-models"],
            cwd=workspace,
            timeout_sec=timeout_sec,
            allowed_env=allowed_env,
            output_limit_bytes=output_limit_bytes,
        )
    if result.timed_out:
        return CursorModelProbeResult([], "Cursor 模型探测超时", "provider_timeout", configured=True, healthy=False)
    if result.error_code:
        if result.error_code == "provider_timeout":
            return CursorModelProbeResult([], "Cursor 模型探测超时", "provider_timeout", configured=True, healthy=False)
        if result.error_code in {"output_limit", "provider_output_limit"}:
            return CursorModelProbeResult([], "Cursor 模型列表输出超限，拒绝使用不完整结果", "provider_output_limit", configured=True)
        return CursorModelProbeResult([], "Cursor 模型列表命令失败，未返回可验证模型", "provider_probe_failed", configured=True)
    if result.returncode != 0:
        return CursorModelProbeResult([], "Cursor 模型列表命令失败，未返回可验证模型", "provider_probe_failed", configured=True)
    if result.output_truncated or result.error_code == "output_limit":
        return CursorModelProbeResult([], "Cursor 模型列表输出超限，拒绝使用不完整结果", "provider_output_limit", configured=True)
    models = parse_cursor_model_listing(result.stdout)
    if not models:
        return CursorModelProbeResult([], "Cursor 模型列表解析失败，未返回可验证模型", "provider_models_invalid", configured=True)
    return CursorModelProbeResult(models, f"已探测 {len(models)} 个 Cursor 模型", configured=True, healthy=True)


def _text_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "value", "delta", "content"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate
            if isinstance(candidate, dict):
                nested = _text_value(candidate)
                if nested:
                    return nested
        return ""
    if isinstance(value, list):
        return "".join(_text_value(item) for item in value)
    return ""


async def _drain_stream(stream: Any, *, context: _CursorRunContext) -> None:
    """Drain stderr while sharing the bounded ACP output budget."""

    if stream is None or not callable(getattr(stream, "read", None)):
        return
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            return
        try:
            if len(chunk) > _ACP_FRAME_LIMIT_BYTES:
                raise OutputLimitExceeded
            context.output_budget.consume(len(chunk))
        except OutputLimitExceeded:
            context.stderr_overflow.set()
            # Keep draining after the first overflow so the child cannot block
            # on a full stderr pipe; the foreground reader observes the event
            # and performs the controlled termination.


def _extract_update_text(update: dict[str, Any], params: dict[str, Any]) -> str:
    for key in ("content", "message", "text", "delta", "agentMessage"):
        text = _text_value(update.get(key))
        if text:
            return text
    return _text_value(params.get("content")) or _text_value(params.get("message"))


def _is_idle_message(message: dict[str, Any]) -> bool:
    params = message.get("params")
    if not isinstance(params, dict):
        return False
    update = params.get("update")
    if not isinstance(update, dict):
        update = params
    for key in ("stopReason", "stop_reason", "status", "state", "sessionUpdate", "type"):
        value = update.get(key) if isinstance(update, dict) else None
        if isinstance(value, str) and value.lower() in _IDLE_STATES:
            return True
        value = params.get(key)
        if isinstance(value, str) and value.lower() in _IDLE_STATES:
            return True
    return False


def _permission_denial(request_id: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {"outcome": {"outcome": "cancelled"}},
    }


class CursorCliProviderClient:
    """Run Cursor Agent in ACP mode with all permission requests denied."""

    def __init__(
        self,
        definition: ProviderDefinition,
        capabilities: ProviderCapabilities | None = None,
        *,
        executable: str | None = None,
        allowed_env: Mapping[str, str] | None = None,
    ) -> None:
        self.definition = definition
        self.provider_key = definition.provider_key
        self.executable = executable or definition.command or "agent"
        self.capabilities = capabilities or _fallback_capabilities(definition)
        self.allowed_env = dict(allowed_env) if allowed_env is not None else None

    async def close(self) -> None:
        """Keep the common Provider lifecycle contract; ``run`` owns all resources."""

        return None

    @staticmethod
    async def _send(process: Any, message: dict[str, Any]) -> None:
        stdin = getattr(process, "stdin", None)
        if stdin is None:
            raise ProviderExecutionError("Cursor ACP stdin 不可用", error_code="provider_process_invalid")
        stdin.write((json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
        drain = getattr(stdin, "drain", None)
        if callable(drain):
            await drain()

    @staticmethod
    async def _read_frame(
        process: Any,
        *,
        timeout_sec: float,
        context: _CursorRunContext | None = None,
    ) -> dict[str, Any]:
        stdout = getattr(process, "stdout", None)
        if stdout is None or not callable(getattr(stdout, "readline", None)):
            raise ProviderExecutionError("Cursor ACP stdout 不可用", error_code="provider_process_invalid")
        read_task = asyncio.create_task(stdout.readline())
        overflow_task: asyncio.Task[Any] | None = None
        if context is not None:
            overflow_task = asyncio.create_task(context.stderr_overflow.wait())
        wait_set: set[asyncio.Task[Any]] = {read_task}
        if overflow_task is not None:
            wait_set.add(overflow_task)
        done: set[asyncio.Task[Any]] = set()
        try:
            done, _pending = await asyncio.wait(
                wait_set,
                timeout=max(0.0, timeout_sec),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                raise asyncio.TimeoutError
            if overflow_task is not None and overflow_task in done and context is not None and context.stderr_overflow.is_set():
                raise OutputLimitExceeded
            raw = read_task.result()
            if not raw:
                raise ProviderExecutionError("Cursor ACP 进程提前退出", error_code="provider_execution_failed")
            raw_bytes = bytes(raw)
            if len(raw_bytes) > _ACP_FRAME_LIMIT_BYTES:
                raise OutputLimitExceeded
            if context is not None:
                context.output_budget.consume(len(raw_bytes))
                if context.stderr_overflow.is_set():
                    raise OutputLimitExceeded
            try:
                value = json.loads(raw_bytes.decode("utf-8", errors="replace"))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ProviderExecutionError("Cursor ACP 返回无效 JSON-RPC", error_code="provider_response_invalid") from exc
            if not isinstance(value, dict):
                raise ProviderExecutionError("Cursor ACP 返回无效 JSON-RPC", error_code="provider_response_invalid")
            return value
        finally:
            for task in wait_set:
                if not task.done():
                    task.cancel()
            for task in wait_set:
                with suppress(BaseException):
                    await task

    async def _send_with_deadline(self, process: Any, message: dict[str, Any], context: _CursorRunContext) -> None:
        remaining = context.remaining()
        if remaining <= 0:
            raise asyncio.TimeoutError
        await asyncio.wait_for(self._send(process, message), timeout=remaining)

    async def _read_response(self, process: Any, request_id: int, context: _CursorRunContext) -> dict[str, Any]:
        while True:
            remaining = context.remaining()
            if remaining <= 0:
                raise asyncio.TimeoutError
            message = await self._read_frame(process, timeout_sec=remaining, context=context)
            if message.get("method") == "session/request_permission":
                request_id_for_permission = message.get("id")
                if request_id_for_permission is not None:
                    await self._send_with_deadline(process, _permission_denial(request_id_for_permission), context)
                continue
            if message.get("id") == request_id:
                return message

    async def _run_acp(self, process: Any, request: ProviderRunRequest, workspace: Path, context: _CursorRunContext) -> str:
        next_id = 1
        await self._send_with_deadline(
            process,
            {
                "jsonrpc": "2.0",
                "id": next_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": 1,
                    "clientInfo": {"name": "bitpro-factorlab", "version": "1"},
                    "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
                },
            },
            context,
        )
        initialize_response = await self._read_response(process, next_id, context)
        if "error" in initialize_response:
            raise ProviderExecutionError("Cursor ACP 初始化失败", error_code="provider_execution_failed")

        next_id += 1
        await self._send_with_deadline(
            process,
            {
                "jsonrpc": "2.0",
                "id": next_id,
                "method": "session/new",
                "params": {"cwd": str(workspace), "mcpServers": []},
            },
            context,
        )
        new_session_response = await self._read_response(process, next_id, context)
        session_result = new_session_response.get("result")
        session_id = session_result.get("sessionId") if isinstance(session_result, dict) else None
        if not isinstance(session_id, str) or not session_id:
            raise ProviderExecutionError("Cursor ACP 未返回 sessionId", error_code="provider_response_invalid")
        context.session_id = session_id

        next_id += 1
        prompt_id = next_id
        await self._send_with_deadline(
            process,
            {
                "jsonrpc": "2.0",
                "id": prompt_id,
                "method": "session/prompt",
                "params": {
                    "sessionId": session_id,
                    "prompt": [{"type": "text", "text": _prompt_text(request)}],
                },
            },
            context,
        )

        chunks: list[str] = []
        while True:
            remaining = context.remaining()
            if remaining <= 0:
                raise asyncio.TimeoutError
            message = await self._read_frame(process, timeout_sec=remaining, context=context)
            if message.get("method") == "session/request_permission":
                permission_id = message.get("id")
                if permission_id is not None:
                    await self._send_with_deadline(process, _permission_denial(permission_id), context)
                continue
            if message.get("method") == "session/update":
                params = message.get("params") if isinstance(message.get("params"), dict) else {}
                update = params.get("update") if isinstance(params.get("update"), dict) else params
                text = _extract_update_text(update, params)
                if text:
                    chunks.append(text)
                if _is_idle_message(message):
                    return "".join(chunks)
                continue
            if message.get("id") == prompt_id:
                result = message.get("result")
                if isinstance(result, dict):
                    stop_reason = result.get("stopReason") or result.get("stop_reason") or result.get("status")
                    if isinstance(stop_reason, str) and stop_reason.lower() in _IDLE_STATES:
                        return "".join(chunks) or _text_value(result)

    async def _cancel_and_terminate(self, process: Any, session_id: str | None) -> None:
        try:
            if session_id:
                with suppress(BaseException):
                    await asyncio.wait_for(
                        self._send(
                            process,
                            {"jsonrpc": "2.0", "id": 999_999, "method": "session/cancel", "params": {"sessionId": session_id}},
                        ),
                        timeout=_ACP_CANCEL_TIMEOUT_SEC,
                    )
        finally:
            # A non-reading or broken ACP stdin must never prevent process
            # termination.  This call is unconditional even when cancel fails.
            await terminate_subprocess(process)

    async def run(self, request: ProviderRunRequest) -> ProviderRunResult:
        try:
            validate_provider_selection(self.capabilities, request.execution)
        except ValueError as exc:
            raise ProviderExecutionError(
                f"Provider {self.provider_key} 任务选择无效",
                provider_key=self.provider_key,
                error_code="provider_selection_invalid",
                status_code=400,
            ) from exc

        started = time.monotonic()
        process: Any = None
        output_limit_bytes = max(1024, int(request.max_output_tokens) * 4)
        context = _CursorRunContext(
            deadline=started + max(0.001, float(request.timeout_sec)),
            output_budget=_OutputBudget(output_limit_bytes),
            stderr_overflow=asyncio.Event(),
        )
        stderr_failure: BaseException | None = None
        process_cleanup_attempted = False
        with tempfile.TemporaryDirectory(prefix="bitpro-cursor-") as raw_workspace:
            workspace = Path(raw_workspace)
            workspace.chmod(0o700)
            argv = build_cursor_argv(executable=self.executable, execution=request.execution)
            stderr_task: asyncio.Task[Any] | None = None
            try:
                spawn_budget = context.remaining()
                if spawn_budget <= 0:
                    raise asyncio.TimeoutError
                process = await asyncio.wait_for(
                    spawn_subprocess_safely(argv, cwd=workspace, allowed_env=self.allowed_env),
                    timeout=spawn_budget,
                )
                stderr = getattr(process, "stderr", None)
                stdout = getattr(process, "stdout", None)
                if stderr is not None and stderr is not stdout:
                    stderr_task = asyncio.create_task(_drain_stream(stderr, context=context))
                text = await self._run_acp(process, request, workspace, context)
                reported_error = getattr(process, "error_code", None) or getattr(process, "runner_error_code", None)
                if reported_error:
                    raise ProviderExecutionError(
                        f"Provider {self.provider_key} 执行失败",
                        provider_key=self.provider_key,
                        error_code="provider_execution_failed",
                    )
                if context.stderr_overflow.is_set():
                    raise OutputLimitExceeded
                if stderr_task is not None and stderr_task.done() and not stderr_task.cancelled():
                    stderr_task.result()
            except asyncio.TimeoutError as exc:
                await self._cancel_and_terminate(process, context.session_id)
                process_cleanup_attempted = True
                raise ProviderExecutionError(
                    f"Provider {self.provider_key} 执行超时",
                    provider_key=self.provider_key,
                    error_code="provider_timeout",
                    status_code=504,
                ) from exc
            except OutputLimitExceeded as exc:
                await self._cancel_and_terminate(process, context.session_id)
                process_cleanup_attempted = True
                raise ProviderExecutionError(
                    f"Provider {self.provider_key} 输出超过安全上限",
                    provider_key=self.provider_key,
                    error_code="provider_output_limit",
                    status_code=502,
                ) from exc
            except asyncio.CancelledError:
                await self._cancel_and_terminate(process, context.session_id)
                process_cleanup_attempted = True
                raise
            except ProviderExecutionError:
                await terminate_subprocess(process)
                process_cleanup_attempted = True
                raise
            except BaseException as exc:
                await terminate_subprocess(process)
                process_cleanup_attempted = True
                raise ProviderExecutionError(
                    f"Provider {self.provider_key} 执行失败",
                    provider_key=self.provider_key,
                    error_code="provider_execution_failed",
                ) from exc
            finally:
                if process is not None and getattr(process, "returncode", None) is None and not process_cleanup_attempted:
                    process_cleanup_attempted = True
                    await terminate_subprocess(process)
                if stderr_task is not None:
                    if not stderr_task.done():
                        with suppress(BaseException):
                            await asyncio.wait_for(stderr_task, timeout=0.05)
                    if stderr_task.done() and not stderr_task.cancelled():
                        try:
                            stderr_task.result()
                        except BaseException as exc:
                            stderr_failure = exc
                    if not stderr_task.done():
                        stderr_task.cancel()
                        with suppress(BaseException):
                            await stderr_task

        if stderr_failure is not None:
            raise ProviderExecutionError(
                f"Provider {self.provider_key} 执行失败",
                provider_key=self.provider_key,
                error_code="provider_execution_failed",
            ) from stderr_failure
        if not text:
            raise ProviderExecutionError(
                f"Provider {self.provider_key} 返回内容为空",
                provider_key=self.provider_key,
                error_code="provider_response_invalid",
            )
        structured = None
        if request.response_schema is not None:
            try:
                parsed = json.loads(_strip_json_fence(text))
                if not isinstance(parsed, dict):
                    raise ValueError("结构化响应必须是对象")
                _validate_json_schema(parsed, request.response_schema)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ProviderExecutionError(
                    f"Provider {self.provider_key} 返回的结构化内容不是有效 JSON",
                    provider_key=self.provider_key,
                    error_code="provider_structured_output_invalid",
                ) from exc
            if not isinstance(parsed, dict):
                raise ProviderExecutionError(
                    f"Provider {self.provider_key} 返回的结构化内容必须是 JSON 对象",
                    provider_key=self.provider_key,
                    error_code="provider_structured_output_invalid",
                )
            structured = parsed
        return ProviderRunResult(
            provider_key=self.provider_key,
            model=request.execution.model,
            text=text,
            structured=structured,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            usage={
                "audit": {
                    "executable": Path(self.executable).name,
                    "version": "unknown",
                    "model": request.execution.model,
                    "duration_ms": max(0, int((time.monotonic() - started) * 1000)),
                    "returncode": getattr(process, "returncode", None),
                }
            },
        )


def _prompt_text(request: ProviderRunRequest) -> str:
    return "\n\n".join(
        f"{str(message.get('role') or 'user').strip() or 'user'}: {str(message.get('content') or '')}"
        for message in request.messages
    )


__all__ = [
    "CursorCliProviderClient",
    "CursorModelProbeResult",
    "build_cursor_argv",
    "parse_cursor_model_listing",
    "probe_cursor_models",
]
