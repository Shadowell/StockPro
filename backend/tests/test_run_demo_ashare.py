from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "scripts" / "run_demo.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("stockpro_run_demo", DEMO)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_demo_source_has_no_crypto_path() -> None:
    source = DEMO.read_text(encoding="utf-8")
    for token in (
        "crypto_data.db",
        "BTC/USDT",
        "kairos_dca",
        "kairos_30m",
        "PaperBroker",
        "sqlite3",
        "'okx'",
        '"okx"',
    ):
        assert token not in source, token
    assert "AShareSpotBroker" in source
    assert "600000.SH" in source
    assert "CNY" in source


def test_run_demo_broker_round_is_ashare_cny() -> None:
    demo = _load_demo()
    result = demo.run_paper_broker_demo()
    assert result["runtime_mode"] == "ashare_paper"
    assert result["currency"] == "CNY"
    assert result["symbol"] == "600000.SH"
    assert result["trades"][0]["side"] == "buy"
    assert result["trades"][1]["side"] == "sell"
    assert result["trades"][0]["quantity"] % 100 == 0
    assert result["trades"][1]["fees"]["tax"] > 0
    assert result["final_cash"] != result["initial_cash"]


def test_run_demo_refuses_crypto_symbol() -> None:
    demo = _load_demo()
    try:
        demo.run_paper_broker_demo("BTC/USDT")
    except SystemExit as exc:
        assert "crypto" in str(exc).lower() or "code.market" in str(exc)
    else:
        raise AssertionError("crypto symbol must be refused")


def test_run_demo_cli_prints_cny_ledger() -> None:
    result = subprocess.run(
        ["python3", str(DEMO)],
        cwd=str(ROOT),
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "backend")},
    )
    output = result.stdout + result.stderr
    assert "A-share paper demo" in output
    assert "600000.SH" in output
    assert "CNY" in output
    assert "BTC" not in output
    assert "USDT" not in output
