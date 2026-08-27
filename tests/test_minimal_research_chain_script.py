from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "create_minimal_research_chain.py"


def load_script():
    spec = importlib.util.spec_from_file_location("create_minimal_research_chain", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_script_defaults_to_dry_run_without_confirmation() -> None:
    script = load_script()
    args = script.parse_args([])

    assert args.apply is False
    script.require_apply_confirmation(args, {})


def test_apply_requires_confirmation_flag_and_environment() -> None:
    script = load_script()
    args = argparse.Namespace(apply=True, confirm_production_sample_write="")

    with pytest.raises(script.SampleChainError, match="confirm-production-sample-write"):
        script.require_apply_confirmation(args, {script.ALLOW_ENV: "1"})

    args.confirm_production_sample_write = script.CONFIRM_TEXT
    with pytest.raises(script.SampleChainError, match=script.ALLOW_ENV):
        script.require_apply_confirmation(args, {})

    script.require_apply_confirmation(args, {script.ALLOW_ENV: "1"})


def test_script_documents_real_source_and_does_not_fabricate_market_rows() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "FROM stock_history" in source
    assert "all_stocks_realtime.change_percent" in source
    assert '"source_table": "stock_history"' in source
    assert "import random" not in source
    assert "uuid4" not in source


def test_dry_run_reports_missing_database_url_without_applying(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    script = load_script()

    exit_code = script.main([])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert '"mode":"dry_run"' in captured.err
    assert "DATABASE_URL" in captured.err
