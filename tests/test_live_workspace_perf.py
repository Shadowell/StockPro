"""实盘工作台加载性能修复回归（2026-08-24 review）。

根因：/live/strategies 冷态需对全部 DB 脚本策略逐个 AST+exec+BaseStrategy
合同校验（生产实测 6.9-16s），部署重启后第一波用户请求承担全部成本；
且校验失败（历史遗留行）以 WARNING 刷日志。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.strategy_registry import (  # noqa: E402
    _load_db_script_strategy_class,
)


def test_db_script_load_failure_logs_debug_not_warning(caplog) -> None:
    """校验失败是常态（历史遗留行），不得以 WARNING 污染每次请求的日志。"""
    strategy = {
        "name": "[合约][1H][CTA] 历史遗留 · 非 BaseStrategy · 100U",
        "config": {"strategy_source": "db_script", "script_content_source": "db"},
        "script_content": "x = 1  # 不是 BaseStrategy",
    }

    with caplog.at_level(logging.WARNING, logger="app.services.strategy_registry"):
        result = _load_db_script_strategy_class(
            name=strategy["name"],
            config=strategy["config"],
            script_content=strategy["script_content"],
        )

    assert result is None
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings == [], f"expected no WARNING records, got: {warnings}"


def test_main_lifespan_warms_live_workspace_cache() -> None:
    """启动时必须后台预热实盘工作台解析缓存，消除部署后的冷启动尖峰。"""
    main_src = (PROJECT_ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    assert "_warm_live_workspace_strategy_cache" in main_src
    assert "_list_live_execution_strategies" in main_src


def test_live_workspace_candidate_cache_is_bounded_and_stable() -> None:
    """缓存容量必须容纳全部策略（265 行），避免满即清空导致反复冷校验。"""
    live_src = (PROJECT_ROOT / "backend/app/api/v2/endpoints/live.py").read_text(
        encoding="utf-8"
    )
    assert "_LIVE_WORKSPACE_CANDIDATE_CACHE_MAX = 1024" in live_src
