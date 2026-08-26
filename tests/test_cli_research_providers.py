from __future__ import annotations

import asyncio
from functools import wraps
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.agent.providers import get_research_provider_client  # noqa: E402
from app.services.agent.providers.codex_cli import (  # noqa: E402
    CodexCliProviderClient,
    build_codex_argv,
)
from app.services.agent.providers.contracts import (  # noqa: E402
    ProviderExecutionConfig,
    ProviderExecutionError,
    ProviderRunRequest,
    ProviderRunResult,
    capability_snapshot_hash,
)
from app.services.agent.providers.cursor_cli import (  # noqa: E402
    CursorCliProviderClient,
    build_cursor_argv,
    parse_cursor_model_listing,
    probe_cursor_models,
)
from app.services.agent.providers.registry import (  # noqa: E402
    BUILTIN_PROVIDER_DEFINITIONS,
    ProviderCapabilities,
    ProviderRegistry,
)
from app.services.agent.providers.subprocess_runner import (  # noqa: E402
    SubprocessResult,
    build_allowlisted_env,
    run_subprocess_safely,
)


def run_async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


def _request(
    provider_key: str,
    model: str,
    *,
    reasoning_effort: str = "auto",
    speed_mode: str = "standard",
    response_schema: dict | None = None,
    timeout_sec: int = 10,
) -> ProviderRunRequest:
    return ProviderRunRequest(
        messages=[{"role": "user", "content": "private research prompt"}],
        execution=ProviderExecutionConfig(
            provider_key=provider_key,
            model=model,
            reasoning_effort=reasoning_effort,
            speed_mode=speed_mode,
        ),
        response_schema=response_schema,
        timeout_sec=timeout_sec,
    )


def _capabilities(provider_key: str, *, models: list[str] | None = None) -> ProviderCapabilities:
    definition = BUILTIN_PROVIDER_DEFINITIONS[provider_key]
    return ProviderCapabilities(
        provider_key=provider_key,
        display_name=definition.display_name,
        transport_type=definition.transport_type,
        credential_mode=definition.credential_mode,
        credential_source="managed_login",
        models=models or list(definition.models),
        reasoning_efforts=list(definition.reasoning_efforts),
        speed_modes=list(definition.speed_modes),
        supports_tools=definition.supports_tools,
        supports_structured_output=definition.supports_structured_output,
        supports_resume=definition.supports_resume,
        configured=True,
        healthy=True,
        config_revision="sha256:test",
    )


def test_direct_cli_client_construction_without_verified_capabilities_fails_closed():
    codex = CodexCliProviderClient(BUILTIN_PROVIDER_DEFINITIONS["codex"])
    cursor = CursorCliProviderClient(BUILTIN_PROVIDER_DEFINITIONS["cursor"])

    assert codex.capabilities.configured is False
    assert codex.capabilities.login_verified is False
    assert cursor.capabilities.configured is False
    assert cursor.capabilities.login_verified is False

    with pytest.raises(ProviderExecutionError) as codex_error:
        asyncio.run(codex.run(_request("codex", "gpt-5.6-sol")))
    with pytest.raises(ProviderExecutionError) as cursor_error:
        asyncio.run(cursor.run(_request("cursor", "auto")))

    assert codex_error.value.error_code == "provider_selection_invalid"
    assert cursor_error.value.error_code == "provider_selection_invalid"


def test_codex_argv_uses_read_only_ephemeral_mode_without_dangerous_flags(tmp_path):
    argv = build_codex_argv(
        executable="codex",
        workspace=tmp_path,
        execution=ProviderExecutionConfig(
            provider_key="codex",
            model="gpt-5.6-sol",
            reasoning_effort="max",
            speed_mode="fast",
        ),
        schema_path=tmp_path / "output-schema.json",
    )

    assert argv[:2] == ["codex", "exec"]
    assert ["--sandbox", "read-only"] == argv[argv.index("--sandbox") : argv.index("--sandbox") + 2]
    assert "--ephemeral" in argv
    assert "--skip-git-repo-check" in argv
    assert "--ignore-rules" in argv
    assert "--ignore-user-config" in argv
    assert 'model_reasoning_effort="max"' in argv
    assert 'service_tier="fast"' in argv
    assert "--dangerously-bypass-approvals-and-sandbox" not in argv
    assert "--full-auto" not in argv
    assert not any("mcp" in str(arg).lower() for arg in argv)
    assert argv[-1] == "-"


def test_cursor_argv_uses_acp_stdio_and_sandbox_without_force(tmp_path):
    argv = build_cursor_argv(
        executable="agent",
        execution=ProviderExecutionConfig(
            provider_key="cursor",
            model="gpt-5.6-sol[effort=high,fast=true]",
            reasoning_effort="auto",
            speed_mode="standard",
        ),
    )

    assert argv[-1] == "acp"
    assert ["--sandbox", "enabled"] == argv[argv.index("--sandbox") : argv.index("--sandbox") + 2]
    assert "--force" not in argv
    assert "--yolo" not in argv


def test_codex_home_is_allowlisted_for_managed_auth_without_secret_env():
    env = build_allowlisted_env(
        {
            "CODEX_HOME": "/tmp/bitpro-codex-home",
            "OPENAI_API_KEY": "secret",
            "PATH": "/usr/bin",
        }
    )

    assert env == {"CODEX_HOME": "/tmp/bitpro-codex-home", "PATH": "/usr/bin"}


@run_async_test
async def test_subprocess_spawn_starts_a_new_process_group(monkeypatch, tmp_path):
    from app.services.agent.providers import subprocess_runner

    captured = {}

    async def fake_create(*argv, **kwargs):
        captured.update(kwargs)
        return type("Process", (), {"returncode": 0})()

    monkeypatch.setattr(subprocess_runner.asyncio, "create_subprocess_exec", fake_create)
    await subprocess_runner.spawn_subprocess_safely(["fake-agent"], cwd=tmp_path)

    if subprocess_runner.os.name == "nt":
        assert "creationflags" in captured
    else:
        assert captured["start_new_session"] is True


@run_async_test
async def test_subprocess_termination_signals_the_whole_process_group(monkeypatch):
    from app.services.agent.providers import subprocess_runner

    signals = []

    class GroupProcess:
        pid = 4242
        returncode = None

        async def wait(self):
            self.returncode = -15
            return self.returncode

        def terminate(self):
            raise AssertionError("individual terminate must not be the primary path")

    process = GroupProcess()
    monkeypatch.setattr(subprocess_runner.os, "killpg", lambda pid, sig: signals.append((pid, sig)))

    await subprocess_runner.terminate_subprocess(process)

    assert signals
    assert signals[0][0] == process.pid


@run_async_test
async def test_subprocess_termination_kills_group_after_leader_exits_on_sigterm(monkeypatch):
    from app.services.agent.providers import subprocess_runner

    signals = []

    class LeaderExitsProcess:
        pid = 5252
        returncode = None

        async def wait(self):
            self.returncode = -15
            return self.returncode

    process = LeaderExitsProcess()
    monkeypatch.setattr(subprocess_runner.os, "killpg", lambda pid, sig: signals.append((pid, sig)))

    await subprocess_runner.terminate_subprocess(process)

    assert signals == [
        (process.pid, subprocess_runner.signal.SIGTERM),
        (process.pid, subprocess_runner.signal.SIGKILL),
    ]


@run_async_test
async def test_subprocess_timeout_terminates_process_and_redacts_environment(monkeypatch, tmp_path):
    class HangingProcess:
        returncode = None

        def __init__(self):
            self.stdin = None
            self.stdout = None
            self.stderr = None
            self.terminated = False
            self.killed = False

        async def communicate(self, input=None):
            await asyncio.sleep(10)
            return b"", b""

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

        async def wait(self):
            while self.returncode is None:
                await asyncio.sleep(0.01)
            self.returncode = -15
            return self.returncode

    process = HangingProcess()

    async def fake_create(*argv, **kwargs):
        assert argv == ("fake-agent",)
        assert "shell" not in kwargs
        assert "OPENAI_API_KEY" not in kwargs["env"]
        assert "SOME_TOKEN" not in kwargs["env"]
        assert kwargs["env"] == {"PATH": "/usr/bin"}
        return process

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    result = await run_subprocess_safely(
        ["fake-agent"],
        cwd=tmp_path,
        timeout_sec=0.01,
        allowed_env={"PATH": "/usr/bin", "OPENAI_API_KEY": "secret", "SOME_TOKEN": "secret"},
        input_text="prompt must stay on stdin",
    )
    assert result.timed_out is True
    assert process.terminated is True
    assert "OPENAI_API_KEY" not in result.audit_metadata
    assert "prompt must stay on stdin" not in json.dumps(result.audit_metadata)


@run_async_test
async def test_subprocess_deadline_covers_stdin_drain_and_reaps_child(monkeypatch, tmp_path):
    from app.services.agent.providers import subprocess_runner

    class BlockingStdin:
        def write(self, data):
            return None

        async def drain(self):
            await asyncio.sleep(3600)

        def close(self):
            return None

    class Child:
        returncode = None

        def __init__(self):
            self.stdin = BlockingStdin()
            self.stdout = None
            self.stderr = None
            self.terminated = False
            self.killed = False
            self.waited = False

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def wait(self):
            self.waited = True
            return self.returncode

    child = Child()

    async def fake_create(*argv, **kwargs):
        assert "shell" not in kwargs
        return child

    monkeypatch.setattr(subprocess_runner.asyncio, "create_subprocess_exec", fake_create)
    result = await subprocess_runner.run_subprocess_safely(
        ["fake-agent"], cwd=tmp_path, timeout_sec=0.01, input_text="prompt"
    )
    assert result.timed_out is True
    assert child.terminated is True
    assert child.waited is True


@run_async_test
async def test_subprocess_broken_pipe_terminates_child_and_returns_controlled_error(monkeypatch, tmp_path):
    from app.services.agent.providers import subprocess_runner

    class Child:
        returncode = None

        class Stdin:
            def write(self, data):
                raise BrokenPipeError("pipe closed")

            def close(self):
                return None

        def __init__(self):
            self.stdin = self.Stdin()
            self.stdout = None
            self.stderr = None
            self.terminated = False
            self.waited = False

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        async def wait(self):
            self.waited = True
            return self.returncode

    child = Child()

    async def fake_create(*argv, **kwargs):
        return child

    monkeypatch.setattr(subprocess_runner.asyncio, "create_subprocess_exec", fake_create)
    result = await subprocess_runner.run_subprocess_safely(
        ["fake-agent"], cwd=tmp_path, timeout_sec=1, input_text="prompt"
    )
    assert result.audit_metadata["error"] == "process_io_failed"
    assert child.terminated is True
    assert child.waited is True


@run_async_test
async def test_subprocess_read_failure_terminates_child_and_reaps(monkeypatch, tmp_path):
    from app.services.agent.providers import subprocess_runner

    class FailingStream:
        async def read(self, size):
            raise OSError("read failed")

    class Child:
        returncode = None

        def __init__(self):
            self.stdin = None
            self.stdout = FailingStream()
            self.stderr = None
            self.terminated = False
            self.waited = False

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        async def wait(self):
            self.waited = True
            return self.returncode

    child = Child()

    async def fake_create(*argv, **kwargs):
        return child

    monkeypatch.setattr(subprocess_runner.asyncio, "create_subprocess_exec", fake_create)
    result = await subprocess_runner.run_subprocess_safely(["fake-agent"], cwd=tmp_path, timeout_sec=1)
    assert result.audit_metadata["error"] == "process_io_failed"
    assert child.terminated is True
    assert child.waited is True


@run_async_test
async def test_codex_client_keeps_prompt_on_stdin_and_parses_agent_message(monkeypatch):
    from app.services.agent.providers import codex_cli

    observed: dict[str, object] = {}

    async def fake_run(argv, **kwargs):
        observed["argv"] = argv
        observed.update(kwargs)
        assert Path(kwargs["cwd"]).exists()
        return SubprocessResult(
            stdout=json.dumps(
                {"type": "item.completed", "item": {"type": "agent_message", "text": "research result"}}
            ),
            stderr="",
            returncode=0,
            duration_ms=4,
            audit_metadata={"executable": "codex", "model": "gpt-5.6-sol", "duration_ms": 4, "returncode": 0},
        )

    monkeypatch.setattr(codex_cli, "run_subprocess_safely", fake_run)
    client = CodexCliProviderClient(
        BUILTIN_PROVIDER_DEFINITIONS["codex"],
        capabilities=_capabilities("codex", models=["gpt-5.6-sol"]),
    )
    result = await client.run(_request("codex", "gpt-5.6-sol", reasoning_effort="max"))

    assert isinstance(result, ProviderRunResult)
    assert result.text == "research result"
    assert observed["input_text"] == "user: private research prompt"
    assert "private research prompt" not in observed["argv"]
    assert "--cd" in observed["argv"]


class _FakeCursorProcess:
    def __init__(self, lines: list[dict], *, hang_on_eof: bool = False, stderr_data: bytes = b""):
        self._lines = [json.dumps(line).encode() + b"\n" for line in lines]
        self.hang_on_eof = hang_on_eof
        self._stderr_data = stderr_data
        self.writes: list[dict] = []
        self.returncode = None
        self.terminated = False
        self.killed = False

        class _Stdin:
            def __init__(self, owner):
                self.owner = owner

            def write(self, data):
                self.owner.writes.append(json.loads(data.decode()))

            async def drain(self):
                return None

            def close(self):
                return None

        class _Stdout:
            def __init__(self, owner):
                self.owner = owner

            async def readline(self):
                if self.owner._lines:
                    return self.owner._lines.pop(0)
                if self.owner.hang_on_eof:
                    await asyncio.sleep(3600)
                self.owner.returncode = 0
                return b""

        class _Stderr:
            def __init__(self, owner):
                self.owner = owner

            async def read(self, size):
                data, self.owner._stderr_data = self.owner._stderr_data, b""
                return data

        self.stdin = _Stdin(self)
        self.stdout = _Stdout(self)
        self.stderr = _Stderr(self)

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        return self.returncode or 0


@run_async_test
async def test_cursor_read_frame_cancellation_cleans_all_child_tasks():
    from app.services.agent.providers import cursor_cli

    class HangingStdout:
        def __init__(self):
            self.started = asyncio.Event()
            self.active = 0

        async def readline(self):
            self.active += 1
            self.started.set()
            try:
                await asyncio.sleep(3600)
            finally:
                self.active -= 1

    stdout = HangingStdout()
    process = type("Process", (), {"stdout": stdout})()
    context = cursor_cli._CursorRunContext(
        deadline=asyncio.get_running_loop().time() + 10,
        output_budget=cursor_cli._OutputBudget(1024),
        stderr_overflow=asyncio.Event(),
    )
    client = CursorCliProviderClient(BUILTIN_PROVIDER_DEFINITIONS["cursor"], capabilities=_capabilities("cursor", models=["auto"]))
    task = asyncio.create_task(client._read_frame(process, timeout_sec=10, context=context))
    await stdout.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)
    assert stdout.active == 0
    current = asyncio.current_task()
    assert not [pending for pending in asyncio.all_tasks() if pending is not current and not pending.done()]


@run_async_test
async def test_cursor_rejects_oversized_frame_and_terminates(monkeypatch):
    from app.services.agent.providers import cursor_cli

    process = _FakeCursorProcess(
        [
            {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}},
            {"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "s-oversize"}},
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "x" * (cursor_cli._ACP_FRAME_LIMIT_BYTES + 1024)}}},
            },
        ]
    )

    async def fake_spawn(argv, **kwargs):
        return process

    monkeypatch.setattr(cursor_cli, "spawn_subprocess_safely", fake_spawn)
    request = _request("cursor", "auto")
    request.max_output_tokens = 65536
    with pytest.raises(Exception) as exc_info:
        await CursorCliProviderClient(BUILTIN_PROVIDER_DEFINITIONS["cursor"], capabilities=_capabilities("cursor", models=["auto"])).run(request)
    assert getattr(exc_info.value, "error_code", "") == "provider_output_limit"
    assert process.terminated is True or process.killed is True


@run_async_test
async def test_cursor_rejects_cumulative_output_and_stderr_flood(monkeypatch):
    from app.services.agent.providers import cursor_cli

    process = _FakeCursorProcess(
        [
            {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}},
            {"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "s-flood"}},
            {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "x" * 400}}}},
            {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "y" * 400}}}},
        ],
        stderr_data=b"z" * 4096,
    )

    async def fake_spawn(argv, **kwargs):
        return process

    monkeypatch.setattr(cursor_cli, "spawn_subprocess_safely", fake_spawn)
    request = _request("cursor", "auto")
    request.max_output_tokens = 1
    with pytest.raises(Exception) as exc_info:
        await CursorCliProviderClient(BUILTIN_PROVIDER_DEFINITIONS["cursor"], capabilities=_capabilities("cursor", models=["auto"])).run(request)
    assert getattr(exc_info.value, "error_code", "") == "provider_output_limit"
    assert process.terminated is True or process.killed is True


@run_async_test
async def test_cursor_acp_denies_permissions_and_stops_on_idle(monkeypatch):
    from app.services.agent.providers import cursor_cli

    process = _FakeCursorProcess(
        [
            {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}},
            {"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "s-1"}},
            {
                "jsonrpc": "2.0",
                "method": "session/request_permission",
                "id": 7,
                "params": {"sessionId": "s-1", "toolCall": {"name": "shell"}},
            },
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": "s-1",
                    "update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "safe answer"}},
                },
            },
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {"sessionId": "s-1", "update": {"sessionUpdate": "idle"}},
            },
        ]
    )
    observed_cwd: Path | None = None

    async def fake_spawn(argv, **kwargs):
        nonlocal observed_cwd
        assert argv[-1] == "acp"
        assert kwargs["allowed_env"] == {"PATH": "/usr/bin"}
        observed_cwd = Path(kwargs["cwd"])
        assert observed_cwd.exists()
        return process

    monkeypatch.setattr(cursor_cli, "spawn_subprocess_safely", fake_spawn)
    client = CursorCliProviderClient(
        BUILTIN_PROVIDER_DEFINITIONS["cursor"],
        capabilities=_capabilities("cursor", models=["gpt-5.6-sol[effort=high,fast=true]"]),
        allowed_env={"PATH": "/usr/bin"},
    )
    result = await client.run(_request("cursor", "gpt-5.6-sol[effort=high,fast=true]"))

    assert result.text == "safe answer"
    methods = [message.get("method") for message in process.writes]
    assert methods[:3] == ["initialize", "session/new", "session/prompt"]
    session_new = process.writes[1]
    assert session_new["params"]["mcpServers"] == []
    assert observed_cwd is not None
    assert session_new["params"]["cwd"] == str(observed_cwd)
    permission_response = next(message for message in process.writes if message.get("id") == 7)
    assert permission_response["result"]["outcome"]["outcome"] in {"cancelled", "denied"}


@run_async_test
async def test_cursor_timeout_sends_cancel_before_termination(monkeypatch):
    from app.services.agent.providers import cursor_cli

    process = _FakeCursorProcess(
        [
            {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}},
            {"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "s-1"}},
        ],
        hang_on_eof=True,
    )

    async def fake_spawn(argv, **kwargs):
        return process

    monkeypatch.setattr(cursor_cli, "spawn_subprocess_safely", fake_spawn)
    client = CursorCliProviderClient(
        BUILTIN_PROVIDER_DEFINITIONS["cursor"],
        capabilities=_capabilities("cursor", models=["auto"]),
    )
    with pytest.raises(Exception, match="超时"):
        await client.run(_request("cursor", "auto", timeout_sec=10))

    assert any(message.get("method") == "session/cancel" for message in process.writes)
    assert process.terminated is True or process.killed is True


@run_async_test
async def test_cursor_cancel_drain_timeout_still_terminates_process(monkeypatch):
    from app.services.agent.providers import cursor_cli

    process = _FakeCursorProcess(
        [
            {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}},
            {"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "s-cancel"}},
        ],
        hang_on_eof=True,
    )
    original_drain = process.stdin.drain
    drain_count = 0

    async def selective_drain():
        nonlocal drain_count
        drain_count += 1
        if drain_count >= 4:
            await asyncio.sleep(3600)
        await original_drain()

    process.stdin.drain = selective_drain

    async def fake_spawn(argv, **kwargs):
        return process

    monkeypatch.setattr(cursor_cli, "spawn_subprocess_safely", fake_spawn)
    request = _request("cursor", "auto")
    request.timeout_sec = 0.01
    with pytest.raises(Exception, match="超时"):
        await CursorCliProviderClient(BUILTIN_PROVIDER_DEFINITIONS["cursor"], capabilities=_capabilities("cursor", models=["auto"])).run(request)
    assert any(message.get("method") == "session/cancel" for message in process.writes)
    assert process.terminated is True or process.killed is True


@run_async_test
async def test_cursor_concurrent_runs_cancel_their_own_session(monkeypatch):
    from app.services.agent.providers import cursor_cli

    process_one = _FakeCursorProcess(
        [
            {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}},
            {"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "s-one"}},
        ],
        hang_on_eof=True,
    )
    process_two = _FakeCursorProcess(
        [
            {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}},
            {"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "s-two"}},
            {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "ok"}}}},
            {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "idle"}}},
        ]
    )
    processes = iter([process_one, process_two])

    async def fake_spawn(argv, **kwargs):
        return next(processes)

    monkeypatch.setattr(cursor_cli, "spawn_subprocess_safely", fake_spawn)
    client = CursorCliProviderClient(BUILTIN_PROVIDER_DEFINITIONS["cursor"], capabilities=_capabilities("cursor", models=["auto"]))
    first = _request("cursor", "auto")
    first.timeout_sec = 0.01
    second = _request("cursor", "auto", timeout_sec=10)
    first_result, second_result = await asyncio.gather(client.run(first), client.run(second), return_exceptions=True)
    assert isinstance(first_result, Exception)
    assert second_result.text == "ok"
    first_cancel = next(message for message in process_one.writes if message.get("method") == "session/cancel")
    assert first_cancel["params"]["sessionId"] == "s-one"
    assert not any(message.get("method") == "session/cancel" for message in process_two.writes)


@run_async_test
async def test_cursor_model_probe_failure_does_not_fabricate_models(monkeypatch):
    from app.services.agent.providers import cursor_cli

    async def fake_run(*argv, **kwargs):
        return SubprocessResult(
            stdout="not a model listing",
            stderr="permission denied",
            returncode=1,
            duration_ms=3,
            audit_metadata={"executable": "agent", "duration_ms": 3, "returncode": 1},
        )

    monkeypatch.setattr(cursor_cli, "run_subprocess_safely", fake_run)
    result = await probe_cursor_models(executable="agent")
    assert result.models == []
    assert "模型" in result.status_detail
    assert result.error_code is not None


def test_cursor_model_parser_rejects_diagnostic_lines_and_accepts_only_known_schema():
    assert parse_cursor_model_listing("Error:gpt-failed") == []
    assert parse_cursor_model_listing("Status: gpt-5\n") == []
    assert parse_cursor_model_listing('{"models":[{"id":"gpt-5.6-sol"}]}') == ["gpt-5.6-sol"]
    assert parse_cursor_model_listing('{"status":"ok","models":[]}') == []
    assert parse_cursor_model_listing('{"status":"failed","models":[{"id":"gpt-5.6-sol"}]}') == []


@run_async_test
async def test_cursor_model_probe_fails_closed_on_truncated_output(monkeypatch):
    from app.services.agent.providers import cursor_cli

    async def fake_run(*argv, **kwargs):
        return SubprocessResult(
            stdout='{"models":[{"id":"gpt-5.6-sol"}]}',
            stderr="",
            returncode=0,
            output_truncated=True,
            audit_metadata={"error": "output_limit"},
        )

    monkeypatch.setattr(cursor_cli, "run_subprocess_safely", fake_run)
    result = await probe_cursor_models(executable="agent")
    assert result.models == []
    assert result.error_code == "provider_output_limit"


@run_async_test
async def test_codex_rejects_non_null_runner_error_even_with_valid_output(monkeypatch):
    from app.services.agent.providers import codex_cli

    async def fake_run(*argv, **kwargs):
        return SubprocessResult(
            stdout=json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "valid"}}),
            returncode=0,
            error_code="process_io_failed",
            audit_metadata={"error": "process_io_failed"},
        )

    monkeypatch.setattr(codex_cli, "run_subprocess_safely", fake_run)
    request = _request("codex", "gpt-5.6-sol")
    with pytest.raises(Exception) as exc_info:
        await CodexCliProviderClient(BUILTIN_PROVIDER_DEFINITIONS["codex"], capabilities=_capabilities("codex", models=["gpt-5.6-sol"])).run(request)
    assert getattr(exc_info.value, "error_code", "") == "provider_execution_failed"


@run_async_test
async def test_cursor_model_probe_rejects_non_null_runner_error_even_with_valid_output(monkeypatch):
    from app.services.agent.providers import cursor_cli

    async def fake_run(*argv, **kwargs):
        return SubprocessResult(
            stdout='{"models":[{"id":"gpt-5.6-sol"}]}',
            returncode=0,
            error_code="process_io_failed",
            audit_metadata={"error": "process_io_failed"},
        )

    monkeypatch.setattr(cursor_cli, "run_subprocess_safely", fake_run)
    result = await probe_cursor_models(executable="agent")
    assert result.models == []
    assert result.error_code == "provider_probe_failed"


@run_async_test
async def test_cursor_propagates_stderr_reader_failure_after_valid_session(monkeypatch):
    from app.services.agent.providers import cursor_cli

    class FailingStderr:
        async def read(self, size):
            raise OSError("stderr reader failed")

    process = _FakeCursorProcess(
        [
            {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}},
            {"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "s-stderr"}},
            {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "valid"}}}},
            {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "idle"}}},
        ]
    )
    process.stderr = FailingStderr()

    async def fake_spawn(argv, **kwargs):
        return process

    monkeypatch.setattr(cursor_cli, "spawn_subprocess_safely", fake_spawn)
    with pytest.raises(Exception) as exc_info:
        await CursorCliProviderClient(BUILTIN_PROVIDER_DEFINITIONS["cursor"], capabilities=_capabilities("cursor", models=["auto"])).run(
            _request("cursor", "auto")
        )
    assert getattr(exc_info.value, "error_code", "") == "provider_execution_failed"


def test_factory_routes_cli_transports_without_http_or_qwen_fallback(monkeypatch):
    registry = ProviderRegistry()
    monkeypatch.setattr("app.services.agent.providers.codex_cli.CodexCliProviderClient", CodexCliProviderClient)
    monkeypatch.setattr("app.services.agent.providers.cursor_cli.CursorCliProviderClient", CursorCliProviderClient)

    runtime_capabilities = {
        key: registry.get_capabilities(key).model_copy(
            update={
                "configured": True,
                "healthy": True,
                "command_available": True,
                "login_verified": True,
            }
        )
        for key in ("codex", "cursor")
    }
    codex_execution = ProviderExecutionConfig(
        provider_key="codex",
        model="gpt-5.6-sol",
        provider_config_revision=runtime_capabilities["codex"].config_revision,
        capability_snapshot_hash=capability_snapshot_hash(runtime_capabilities["codex"]),
    )
    cursor_execution = ProviderExecutionConfig(
        provider_key="cursor",
        model="auto",
        provider_config_revision=runtime_capabilities["cursor"].config_revision,
        capability_snapshot_hash=capability_snapshot_hash(runtime_capabilities["cursor"]),
    )
    codex = get_research_provider_client(
        codex_execution,
        registry=registry,
        capabilities_override=runtime_capabilities["codex"],
    )
    cursor = get_research_provider_client(
        cursor_execution,
        registry=registry,
        capabilities_override=runtime_capabilities["cursor"],
    )
    assert isinstance(codex, CodexCliProviderClient)
    assert isinstance(cursor, CursorCliProviderClient)


def test_registry_managed_cli_definitions_have_no_http_or_secret_metadata():
    for key in ("codex", "cursor"):
        definition = BUILTIN_PROVIDER_DEFINITIONS[key]
        assert definition.transport_type in {"codex_cli", "cursor_cli"}
        assert definition.credential_mode == "managed_login"
        assert definition.base_url == ""
        assert definition.api_key_env == ""


@run_async_test
async def test_codex_structured_output_reuses_fail_closed_schema_validation(monkeypatch):
    from app.services.agent.providers import codex_cli

    async def fake_run(argv, **kwargs):
        return SubprocessResult(
            stdout=json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": '{"ok":"wrong"}'}}),
            returncode=0,
            duration_ms=1,
            audit_metadata={},
        )

    monkeypatch.setattr(codex_cli, "run_subprocess_safely", fake_run)
    request = _request(
        "codex",
        "gpt-5.6-sol",
        response_schema={"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
    )
    with pytest.raises(Exception) as exc_info:
        await CodexCliProviderClient(BUILTIN_PROVIDER_DEFINITIONS["codex"], capabilities=_capabilities("codex", models=["gpt-5.6-sol"])).run(request)
    assert getattr(exc_info.value, "error_code", "") == "provider_structured_output_invalid"


@run_async_test
async def test_cursor_structured_output_reuses_fail_closed_schema_validation(monkeypatch):
    from app.services.agent.providers import cursor_cli

    process = _FakeCursorProcess(
        [
            {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}},
            {"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "s-schema"}},
            {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"text": '{"ok":"wrong"}'}}}},
            {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "idle"}}},
        ]
    )

    async def fake_spawn(argv, **kwargs):
        return process

    monkeypatch.setattr(cursor_cli, "spawn_subprocess_safely", fake_spawn)
    request = _request(
        "cursor",
        "auto",
        response_schema={"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
    )
    with pytest.raises(Exception) as exc_info:
        await CursorCliProviderClient(BUILTIN_PROVIDER_DEFINITIONS["cursor"], capabilities=_capabilities("cursor", models=["auto"])).run(request)
    assert getattr(exc_info.value, "error_code", "") == "provider_structured_output_invalid"
