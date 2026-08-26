"""Read-only Codex CLI research Provider."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
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
from .subprocess_runner import SubprocessResult, run_subprocess_safely


_SAFE_TEXT_RE = re.compile(r"^[\s\S]{0,16777216}$")


def build_codex_argv(
    *,
    executable: str,
    workspace: str | os.PathLike[str],
    execution: Any,
    schema_path: str | os.PathLike[str] | None = None,
) -> list[str]:
    """Build the fixed, non-interactive-safe Codex command line.

    The final ``-`` is intentional: the research prompt is written to stdin and
    can never appear in process arguments or audit metadata.
    """

    argv = [
        str(executable),
        "exec",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--ignore-rules",
        "--ignore-user-config",
        "--json",
        "--model",
        str(execution.model),
        "--config",
        f'model_reasoning_effort="{execution.reasoning_effort}"',
    ]
    if execution.speed_mode == "fast":
        argv.extend(["--config", 'service_tier="fast"'])
    if schema_path is not None:
        argv.extend(["--output-schema", str(schema_path)])
    argv.extend(["--cd", str(workspace), "-"])
    return argv


def messages_to_prompt(messages: list[dict[str, str]]) -> str:
    parts: list[str] = []
    for message in messages:
        role = str(message.get("role") or "user").strip() or "user"
        content = str(message.get("content") or "")
        parts.append(f"{role}: {content}")
    return "\n\n".join(parts)


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


def _text_from_event(event: Any) -> str:
    if not isinstance(event, dict):
        return ""
    candidates: list[Any] = [event.get("text"), event.get("output_text"), event.get("content"), event.get("delta")]
    item = event.get("item")
    if isinstance(item, dict):
        candidates.extend([item.get("text"), item.get("content")])
    response = event.get("response")
    if isinstance(response, dict):
        candidates.extend([response.get("output_text"), response.get("text")])
        output = response.get("output")
        if isinstance(output, list):
            candidates.extend(_text_from_event(value) for value in output)
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
        if isinstance(candidate, list):
            chunks = []
            for value in candidate:
                if isinstance(value, str):
                    chunks.append(value)
                elif isinstance(value, dict) and isinstance(value.get("text"), str):
                    chunks.append(value["text"])
            if chunks:
                return "".join(chunks)
    return ""


def parse_codex_output(stdout: str) -> str:
    """Extract agent text from Codex JSONL while tolerating CLI version drift."""

    messages: list[str] = []
    for raw_line in str(stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        event_type = event.get("type") if isinstance(event, dict) else None
        item_type = event.get("item", {}).get("type") if isinstance(event, dict) and isinstance(event.get("item"), dict) else None
        if (
            event_type in {"item.completed", "agent_message", "message", "response.completed", "result"}
            or (isinstance(event_type, str) and ("message" in event_type or "delta" in event_type))
            or item_type in {
            "agent_message",
            "assistant_message",
            "message",
            }
        ):
            text = _text_from_event(event)
            if text:
                messages.append(text)
    if messages:
        return "".join(messages)
    # A test double or an older CLI may return plain text despite --json.  It is
    # still safe to return bounded stdout; stderr remains private diagnostics.
    return str(stdout or "").strip()


def _parse_structured(text: str, schema: dict[str, Any], *, provider_key: str) -> dict[str, Any]:
    try:
        value = json.loads(_strip_json_fence(text))
        if not isinstance(value, dict):
            raise ValueError("结构化响应必须是对象")
        _validate_json_schema(value, schema)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ProviderExecutionError(
            f"Provider {provider_key} 返回的结构化内容不是有效 JSON",
            provider_key=provider_key,
            error_code="provider_structured_output_invalid",
        ) from exc
    if not isinstance(value, dict):
        raise ProviderExecutionError(
            f"Provider {provider_key} 返回的结构化内容必须是 JSON 对象",
            provider_key=provider_key,
            error_code="provider_structured_output_invalid",
        )
    return value


class CodexCliProviderClient:
    """Execute Codex with a private temporary cwd and read-only sandbox."""

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
        self.executable = executable or definition.command or "codex"
        self.capabilities = capabilities or _fallback_capabilities(definition)
        self.allowed_env = dict(allowed_env) if allowed_env is not None else None

    async def close(self) -> None:
        """Keep the common Provider lifecycle contract; ``run`` owns all resources."""

        return None

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
        with tempfile.TemporaryDirectory(prefix="bitpro-codex-") as raw_workspace:
            workspace = Path(raw_workspace)
            workspace.chmod(0o700)
            schema_path: Path | None = None
            try:
                if request.response_schema is not None:
                    schema_path = workspace / "output-schema.json"
                    schema_path.write_text(
                        json.dumps(request.response_schema, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8",
                    )
                    schema_path.chmod(0o600)
                argv = build_codex_argv(
                    executable=self.executable,
                    workspace=workspace,
                    execution=request.execution,
                    schema_path=schema_path,
                )
                result: SubprocessResult = await run_subprocess_safely(
                    argv,
                    cwd=workspace,
                    timeout_sec=request.timeout_sec,
                    allowed_env=self.allowed_env,
                    input_text=messages_to_prompt(request.messages),
                    output_limit_bytes=max(1024, int(request.max_output_tokens) * 4),
                    model=request.execution.model,
                )
            finally:
                if schema_path is not None:
                    try:
                        schema_path.unlink()
                    except FileNotFoundError:
                        pass

        if result.timed_out:
            raise ProviderExecutionError(
                f"Provider {self.provider_key} 执行超时",
                provider_key=self.provider_key,
                error_code="provider_timeout",
                status_code=504,
            )
        if result.error_code:
            if result.error_code in {"output_limit", "provider_output_limit"}:
                raise ProviderExecutionError(
                    f"Provider {self.provider_key} 输出超过安全上限",
                    provider_key=self.provider_key,
                    error_code="provider_output_limit",
                    status_code=502,
                )
            if result.error_code == "provider_timeout":
                raise ProviderExecutionError(
                    f"Provider {self.provider_key} 执行超时",
                    provider_key=self.provider_key,
                    error_code="provider_timeout",
                    status_code=504,
                )
            raise ProviderExecutionError(
                f"Provider {self.provider_key} 执行失败",
                provider_key=self.provider_key,
                error_code="provider_execution_failed",
            )
        if result.output_truncated:
            raise ProviderExecutionError(
                f"Provider {self.provider_key} 输出超过安全上限",
                provider_key=self.provider_key,
                error_code="provider_output_limit",
                status_code=502,
            )
        if result.returncode != 0:
            raise ProviderExecutionError(
                f"Provider {self.provider_key} 执行失败",
                provider_key=self.provider_key,
                error_code="provider_execution_failed",
            )
        text = parse_codex_output(result.stdout)
        if not text or not _SAFE_TEXT_RE.fullmatch(text):
            raise ProviderExecutionError(
                f"Provider {self.provider_key} 返回内容为空或超限",
                provider_key=self.provider_key,
                error_code="provider_response_invalid",
            )
        structured = _parse_structured(text, request.response_schema, provider_key=self.provider_key) if request.response_schema else None
        duration_ms = result.duration_ms or max(0, int((time.monotonic() - started) * 1000))
        return ProviderRunResult(
            provider_key=self.provider_key,
            model=request.execution.model,
            text=text,
            structured=structured,
            duration_ms=duration_ms,
            usage={"audit": dict(result.audit_metadata)},
        )


__all__ = [
    "CodexCliProviderClient",
    "build_codex_argv",
    "messages_to_prompt",
    "parse_codex_output",
]
