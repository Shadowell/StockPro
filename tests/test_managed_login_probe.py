import asyncio
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.agent.providers.registry import ProviderDefinition  # noqa: E402


@dataclass
class FakeCompletedProcess:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def managed_definition(provider_key: str = "codex") -> ProviderDefinition:
    return ProviderDefinition(
        provider_key=provider_key,
        display_name=provider_key.title(),
        transport_type="codex_cli" if provider_key == "codex" else "cursor_cli",
        credential_mode="managed_login",
        command="codex" if provider_key == "codex" else "agent",
        default_model="model-1",
        models=["model-1"],
        reasoning_efforts=["auto"],
        speed_modes=["standard"],
        builtin=True,
    )


def test_provider_fixtures_do_not_patch_standard_library_subprocess_run():
    completed = subprocess.run(
        [sys.executable, "-c", "print('ordinary-subprocess')"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "ordinary-subprocess"


def test_probe_singleflight_and_ttl_cache_run_command_once():
    from app.services.agent.providers.managed_login import ManagedLoginProbeService

    calls = 0

    def runner(argv, **kwargs):
        nonlocal calls
        calls += 1
        time.sleep(0.03)
        return FakeCompletedProcess(stdout="Logged in using ChatGPT")

    async def scenario():
        service = ManagedLoginProbeService(runner=runner, which=lambda command: command, ttl_sec=60)
        definition = managed_definition()
        first = await asyncio.gather(*(service.probe(definition) for _ in range(6)))
        cached = await service.probe(definition)
        return first, cached

    first, cached = asyncio.run(scenario())

    assert calls == 1
    assert all(item.login_verified is True for item in first)
    assert cached.login_verified is True


def test_probe_does_not_block_event_loop_and_requires_positive_marker():
    from app.services.agent.providers.managed_login import ManagedLoginProbeService

    def runner(argv, **kwargs):
        time.sleep(0.05)
        return FakeCompletedProcess(stdout="status ok")

    async def scenario():
        service = ManagedLoginProbeService(runner=runner, which=lambda command: command, ttl_sec=0)
        task = asyncio.create_task(service.probe(managed_definition()))
        await asyncio.sleep(0.005)
        ticked_before_runner_finished = not task.done()
        result = await task
        return ticked_before_runner_finished, result

    ticked, result = asyncio.run(scenario())

    assert ticked is True
    assert result.command_available is True
    assert result.login_verified is False
    assert result.status_detail == "CLI 已发现，但登录状态未验证"
    assert "status ok" not in result.model_dump_json()


def test_probe_recognizes_only_provider_specific_authenticated_markers():
    from app.services.agent.providers.managed_login import ManagedLoginProbeService

    outputs = {
        "codex": FakeCompletedProcess(stdout="Logged in using ChatGPT"),
        "cursor": FakeCompletedProcess(stdout="Authenticated as Cursor user"),
    }

    def runner(argv, **kwargs):
        provider = "cursor" if argv[0] == "agent" else "codex"
        return outputs[provider]

    async def scenario():
        service = ManagedLoginProbeService(runner=runner, which=lambda command: command, ttl_sec=60)
        return await asyncio.gather(
            service.probe(managed_definition("codex")),
            service.probe(managed_definition("cursor")),
        )

    codex, cursor = asyncio.run(scenario())

    assert codex.login_verified is True
    assert cursor.login_verified is True
    assert codex.probed_at
    assert cursor.probed_at


def test_probe_rejects_negative_login_status_even_when_it_contains_positive_words():
    from app.services.agent.providers.managed_login import ManagedLoginProbeService

    outputs = iter(("Not logged in", "Unauthenticated: login required"))
    service = ManagedLoginProbeService(
        runner=lambda argv, **kwargs: FakeCompletedProcess(stdout=next(outputs)),
        which=lambda command: command,
        ttl_sec=0,
    )

    async def scenario():
        definition = managed_definition()
        return await service.probe(definition), await service.probe(definition, force=True)

    first, second = asyncio.run(scenario())

    assert first.login_verified is False
    assert second.login_verified is False


def test_probe_failure_is_sanitized_and_cached():
    from app.services.agent.providers.managed_login import ManagedLoginProbeService

    calls = 0

    def runner(argv, **kwargs):
        nonlocal calls
        calls += 1
        return FakeCompletedProcess(returncode=1, stderr="token=secret@example.com")

    async def scenario():
        service = ManagedLoginProbeService(runner=runner, which=lambda command: command, ttl_sec=60)
        definition = managed_definition()
        return await service.probe(definition), await service.probe(definition)

    first, second = asyncio.run(scenario())

    assert calls == 1
    assert first.login_verified is False
    assert first.error_code == "managed_login_unverified"
    assert first == second
    assert "secret@example.com" not in first.model_dump_json()


def test_probe_supports_safe_async_runner_timeout_without_raw_output():
    from app.services.agent.providers.managed_login import ManagedLoginProbeService
    from app.services.agent.providers.subprocess_runner import SubprocessResult

    calls = []

    async def safe_runner(argv, **kwargs):
        calls.append((tuple(argv), kwargs))
        return SubprocessResult(
            timed_out=True,
            error_code="provider_timeout",
            stderr="token=must-not-leak",
        )

    service = ManagedLoginProbeService(
        runner=safe_runner,
        which=lambda command: command,
        ttl_sec=0,
    )
    result = asyncio.run(service.probe(managed_definition()))

    assert calls[0][0] == ("codex", "login", "status")
    assert result.login_verified is False
    assert result.error_code == "managed_login_probe_failed"
    assert "must-not-leak" not in result.model_dump_json()


def test_runtime_capability_list_probes_each_cli_once_per_cache_window(monkeypatch, tmp_path):
    from app.services.agent import llm_client
    from app.services.agent.providers.managed_login import (
        ManagedLoginProbeService,
        list_runtime_provider_capabilities,
    )
    from app.services.agent.providers.registry import ProviderRegistry

    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", tmp_path / "models.json")
    calls: list[tuple[str, ...]] = []

    def runner(argv, **kwargs):
        calls.append(tuple(argv))
        return FakeCompletedProcess(stdout="Authenticated and logged in")

    async def scenario():
        service = ManagedLoginProbeService(
            runner=runner,
            which=lambda command: command,
            ttl_sec=60,
        )
        registry = ProviderRegistry()
        first = await list_runtime_provider_capabilities(registry, service=service)
        second = await list_runtime_provider_capabilities(registry, service=service)
        return first, second

    first, second = asyncio.run(scenario())

    assert calls == [("codex", "login", "status"), ("agent", "status")]
    assert len(first) == len(second)
    assert {item.provider_key: item.login_verified for item in first}["codex"] is True
    assert {item.provider_key: item.login_verified for item in first}["cursor"] is True
