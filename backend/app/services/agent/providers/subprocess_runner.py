"""Small, fail-closed subprocess boundary for managed research CLIs.

The runner deliberately does not expose a shell, inherited environment, command
line prompt, or raw child-process diagnostics.  Managed-login CLIs still receive
the small set of non-secret process variables they need, while credentials stay
inside their own profiles and never cross this provider boundary.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
import os
import re
import signal
import subprocess
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


_DEFAULT_OUTPUT_LIMIT_BYTES = 2 * 1024 * 1024
_TERMINATE_GRACE_SEC = 0.5
_SAFE_ENV_KEYS = frozenset(
    {
        "CODEX_HOME",
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "TERM",
        "TMPDIR",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
    }
)
_SECRET_ENV_RE = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD|PASS|COOKIE|AUTH|CREDENTIAL)", re.I)
_SAFE_MODEL_RE = re.compile(r"^[A-Za-z0-9._:/+\[\]=,-]{1,256}$")


@dataclass(slots=True)
class SubprocessResult:
    """Bounded child output plus sanitized execution metadata."""

    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
    timed_out: bool = False
    output_truncated: bool = False
    duration_ms: int = 0
    audit_metadata: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None


def _validate_argv(argv: Sequence[str]) -> list[str]:
    if not argv:
        raise ValueError("Provider CLI 命令不能为空")
    args = [str(value) for value in argv]
    if any(not value or "\x00" in value or "\n" in value or "\r" in value for value in args):
        raise ValueError("Provider CLI 命令参数无效")
    # The executable is fixed by the Provider definition.  Reject shell-like
    # command strings here even though create_subprocess_exec never invokes a
    # shell, so callers cannot accidentally turn this into a command wrapper.
    executable_name = Path(args[0]).name.lower()
    if executable_name in {"sh", "bash", "zsh", "fish", "dash", "ksh", "cmd", "powershell", "pwsh"}:
        raise ValueError("Provider CLI 不允许使用 shell 可执行文件")
    if any(character in args[0] for character in (";", "|", "&", "`")):
        raise ValueError("Provider CLI 可执行文件无效")
    return args


def build_allowlisted_env(allowed_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build an environment containing only explicitly safe, non-secret keys."""

    source = allowed_env if allowed_env is not None else os.environ
    result: dict[str, str] = {}
    for raw_key, raw_value in source.items():
        key = str(raw_key)
        if key not in _SAFE_ENV_KEYS or _SECRET_ENV_RE.search(key):
            continue
        value = str(raw_value)
        if "\x00" in value:
            continue
        result[key] = value
    return result


def _prepare_cwd(cwd: str | os.PathLike[str] | None) -> tuple[Path, bool]:
    if cwd is None:
        path = Path(tempfile.mkdtemp(prefix="bitpro-provider-"))
        owned = True
    else:
        path = Path(cwd)
        if not path.exists():
            path.mkdir(parents=True, mode=0o700)
        if not path.is_dir():
            raise ValueError("Provider CLI 工作目录无效")
        owned = False
    os.chmod(path, 0o700)
    return path, owned


async def _read_bounded(
    stream: Any,
    limit_bytes: int,
    *,
    overflow_event: asyncio.Event | None = None,
) -> tuple[bytes, bool]:
    if stream is None:
        return b"", False
    limit = max(1, int(limit_bytes))
    chunks: list[bytes] = []
    size = 0
    truncated = False
    while True:
        read = getattr(stream, "read", None)
        if not callable(read):
            break
        chunk = await read(65536)
        if not chunk:
            break
        raw = bytes(chunk)
        previous_size = size
        if size < limit:
            kept = raw[: limit - size]
            chunks.append(kept)
            size += len(kept)
        if previous_size + len(raw) > limit:
            truncated = True
            if overflow_event is not None:
                overflow_event.set()
    return b"".join(chunks), truncated


async def _write_stdin(process: Any, input_text: str | None) -> None:
    stdin = getattr(process, "stdin", None)
    if stdin is None:
        return
    try:
        if input_text is not None:
            stdin.write(str(input_text).encode("utf-8"))
            drain = getattr(stdin, "drain", None)
            if callable(drain):
                await drain()
        close = getattr(stdin, "close", None)
        if callable(close):
            close()
    finally:
        # Do not retain the prompt in this helper frame longer than needed.
        input_text = None


async def terminate_subprocess(process: Any) -> None:
    """Terminate a child process group, then kill the group after a short grace."""

    if process is None:
        return
    pid = getattr(process, "pid", None)

    def signal_group(sig: int) -> bool:
        if not isinstance(pid, int) or pid <= 0:
            return False
        if os.name == "nt":
            send_signal = getattr(process, "send_signal", None)
            if callable(send_signal):
                with suppress(BaseException):
                    send_signal(signal.CTRL_BREAK_EVENT if sig == signal.SIGTERM else signal.SIGTERM)
                    return True
            return False
        with suppress(ProcessLookupError, OSError):
            os.killpg(pid, sig)
            return True
        return False

    group_signaled = signal_group(signal.SIGTERM)
    if not group_signaled and getattr(process, "returncode", None) is None:
        terminate = getattr(process, "terminate", None)
        if callable(terminate):
            with suppress(BaseException):
                terminate()
    wait = getattr(process, "wait", None)
    leader_reaped = False
    if callable(wait):
        try:
            await asyncio.wait_for(wait(), timeout=_TERMINATE_GRACE_SEC)
            leader_reaped = True
        except (asyncio.TimeoutError, ProcessLookupError, OSError):
            pass

    # The group may still contain descendants after its leader exits.  On
    # POSIX, always follow the grace period with a group SIGKILL; a missing
    # group is harmless and suppressed by signal_group().
    group_killed = signal_group(signal.SIGKILL) if group_signaled and os.name != "nt" else False
    if not group_killed and getattr(process, "returncode", None) is None:
        kill = getattr(process, "kill", None)
        if callable(kill):
            with suppress(ProcessLookupError, OSError):
                kill()
    if callable(wait) and not leader_reaped:
        with suppress(asyncio.TimeoutError, ProcessLookupError, OSError):
            await asyncio.wait_for(wait(), timeout=_TERMINATE_GRACE_SEC)


def _audit_value(value: Any, *, max_length: int = 256) -> str:
    text = str(value or "")
    if not _SAFE_MODEL_RE.fullmatch(text):
        return "redacted"
    return text[:max_length]


async def spawn_subprocess_safely(
    argv: Sequence[str],
    *,
    cwd: str | os.PathLike[str],
    allowed_env: Mapping[str, str] | None = None,
) -> Any:
    """Start an interactive managed CLI with the same safe process boundary."""

    args = _validate_argv(argv)
    workdir = Path(cwd)
    if not workdir.exists() or not workdir.is_dir():
        raise ValueError("Provider CLI 工作目录无效")
    os.chmod(workdir, 0o700)
    # create_subprocess_exec is used directly; no shell command is ever built.
    spawn_kwargs: dict[str, Any] = {
        "stdin": asyncio.subprocess.PIPE,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
        "cwd": str(workdir),
        "env": build_allowlisted_env(allowed_env),
    }
    if os.name == "nt":
        spawn_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        spawn_kwargs["start_new_session"] = True
    return await asyncio.create_subprocess_exec(
        *args,
        **spawn_kwargs,
    )


async def run_subprocess_safely(
    argv: Sequence[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    timeout_sec: float = 240,
    allowed_env: Mapping[str, str] | None = None,
    input_text: str | None = None,
    output_limit_bytes: int = _DEFAULT_OUTPUT_LIMIT_BYTES,
    model: str | None = None,
    version: str | None = None,
) -> SubprocessResult:
    """Run one fixed executable with bounded output and sanitized audit data."""

    args = _validate_argv(argv)
    workdir, owned_workdir = _prepare_cwd(cwd)
    env = build_allowlisted_env(allowed_env)
    started = time.monotonic()
    deadline = started + max(0.001, float(timeout_sec))
    process: Any = None
    stdout = b""
    stderr = b""
    output_truncated = False
    timed_out = False
    error_code: str | None = None
    cancellation: BaseException | None = None
    stdout_task: asyncio.Task[Any] | None = None
    stderr_task: asyncio.Task[Any] | None = None
    wait_task: asyncio.Task[Any] | None = None
    overflow_task: asyncio.Task[Any] | None = None
    process_cleanup_attempted = False

    def remaining() -> float:
        return max(0.0, deadline - time.monotonic())

    async def await_bounded(awaitable: Any) -> Any:
        budget = remaining()
        if budget <= 0:
            close = getattr(awaitable, "close", None)
            if callable(close):
                with suppress(BaseException):
                    close()
            raise asyncio.TimeoutError
        return await asyncio.wait_for(awaitable, timeout=budget)

    try:
        try:
            spawn_kwargs: dict[str, Any] = {
                "stdin": asyncio.subprocess.PIPE,
                "stdout": asyncio.subprocess.PIPE,
                "stderr": asyncio.subprocess.PIPE,
                "cwd": str(workdir),
                "env": env,
            }
            if os.name == "nt":
                spawn_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            else:
                spawn_kwargs["start_new_session"] = True
            process = await await_bounded(
                asyncio.create_subprocess_exec(
                    *args,
                    **spawn_kwargs,
                )
            )
        except asyncio.TimeoutError:
            timed_out = True
            error_code = "provider_timeout"
        except asyncio.CancelledError as exc:
            cancellation = exc
            error_code = "process_cancelled"
        except BaseException:
            # Child-start failures are returned as sanitized results so the
            # Provider adapter can add its provider key without exposing paths.
            error_code = "process_start_failed"

        if process is not None:
            stdout_stream = getattr(process, "stdout", None)
            stderr_stream = getattr(process, "stderr", None)
            overflow_event = asyncio.Event()
            stdout_task = asyncio.create_task(
                _read_bounded(stdout_stream, output_limit_bytes, overflow_event=overflow_event)
            )
            stderr_task = asyncio.create_task(
                _read_bounded(stderr_stream, output_limit_bytes, overflow_event=overflow_event)
            )
            wait = getattr(process, "wait", None)
            wait_task = asyncio.create_task(wait()) if callable(wait) else None
            overflow_task = asyncio.create_task(overflow_event.wait())
            try:
                await await_bounded(_write_stdin(process, input_text))
                pending: list[asyncio.Task[Any]] = [stdout_task, stderr_task]
                if wait_task is not None:
                    pending.append(wait_task)
                pending_with_overflow = {*pending, overflow_task}
                wait_budget = remaining()
                if wait_budget <= 0:
                    raise asyncio.TimeoutError
                done, _pending_after_wait = await asyncio.wait(
                    pending_with_overflow,
                    timeout=wait_budget,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    raise asyncio.TimeoutError
                if overflow_task in done and overflow_event.is_set():
                    error_code = "output_limit"
                else:
                    await await_bounded(asyncio.gather(*pending))
                    # Surface a read/wait exception as a controlled process I/O
                    # failure instead of silently returning partial output.
                    for task in pending:
                        if task.done() and not task.cancelled():
                            task.result()
            except asyncio.TimeoutError:
                timed_out = True
                if error_code is None:
                    error_code = "provider_timeout"
            except asyncio.CancelledError as exc:
                cancellation = exc
                error_code = "process_cancelled"
            except BaseException:
                error_code = "process_io_failed"
            finally:
                if process is not None and getattr(process, "returncode", None) is None:
                    process_cleanup_attempted = True
                    await terminate_subprocess(process)
                for task in (stdout_task, stderr_task, wait_task, overflow_task):
                    if task is not None and not task.done():
                        task.cancel()
                for task in (stdout_task, stderr_task, wait_task, overflow_task):
                    if task is not None:
                        with suppress(BaseException):
                            await task
                for task in (stdout_task, stderr_task):
                    if task is not None and task.done() and not task.cancelled():
                        with suppress(BaseException):
                            value = task.result()
                            if task is stdout_task:
                                stdout, stdout_truncated = value
                            else:
                                stderr, stderr_truncated = value
                            output_truncated = output_truncated or bool(stdout_truncated or stderr_truncated)
                input_text = None

        if output_truncated and error_code is None:
            error_code = "output_limit"
        returncode = getattr(process, "returncode", None) if process is not None else None
        duration_ms = max(0, int((time.monotonic() - started) * 1000))
        audit_metadata: dict[str, Any] = {
            "executable": _audit_value(Path(args[0]).name),
            "version": _audit_value(version or "unknown"),
            "duration_ms": duration_ms,
            "returncode": returncode,
        }
        if model:
            audit_metadata["model"] = _audit_value(model)
        if timed_out:
            audit_metadata["error"] = "timeout"
        elif error_code:
            audit_metadata["error"] = error_code
        if output_truncated:
            audit_metadata["output_truncated"] = True
        result = SubprocessResult(
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            returncode=returncode,
            timed_out=timed_out,
            output_truncated=output_truncated,
            duration_ms=duration_ms,
            audit_metadata=audit_metadata,
            error_code=error_code,
        )
        if cancellation is not None:
            raise cancellation
        return result
    finally:
        input_text = None
        for task in (stdout_task, stderr_task, wait_task, overflow_task):
            if task is not None and not task.done():
                task.cancel()
        for task in (stdout_task, stderr_task, wait_task, overflow_task):
            if task is not None:
                with suppress(BaseException):
                    await task
        if process is not None and getattr(process, "returncode", None) is None and not process_cleanup_attempted:
            process_cleanup_attempted = True
            await terminate_subprocess(process)
        if owned_workdir:
            # This directory was created by this function and is never a
            # caller-supplied workspace, so remove any CLI-created output files
            # without touching user data outside the exact private path.
            shutil.rmtree(workdir, ignore_errors=True)


__all__ = [
    "SubprocessResult",
    "build_allowlisted_env",
    "run_subprocess_safely",
    "spawn_subprocess_safely",
    "terminate_subprocess",
]
