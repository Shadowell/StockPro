"""模块5: 前端检查。"""

import os
import subprocess
from pathlib import Path

import httpx
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO_ROOT / "frontend"

# 禁用系统代理（ClashX等），避免 httpx 走代理返回 502
os.environ.setdefault("no_proxy", "*")
os.environ.setdefault("NO_PROXY", "*")


class TestFrontendCompile:
    """前端编译检查"""

    @pytest.mark.frontend
    def test_typescript_no_errors(self):
        """TypeScript 编译零错误"""
        result = subprocess.run(
            ["npx", "tsc", "--noEmit"],
            cwd=FRONTEND_DIR,
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, f"TypeScript 编译错误:\n{result.stdout}\n{result.stderr}"


class TestFrontendPages:
    """前端页面可访问性"""

    PAGES = ["/", "/market", "/strategy", "/backtest", "/live", "/monitor"]

    @pytest.mark.frontend
    @pytest.mark.parametrize("path", PAGES)
    def test_page_accessible(self, path):
        """页面返回 200（允许 Vite HMR 导致的短暂 502，最多重试 3 次）"""
        import time
        for attempt in range(3):
            r = httpx.get(f"http://127.0.0.1:8888{path}", timeout=10, proxy=None)
            if r.status_code == 200:
                break
            time.sleep(2)
        assert r.status_code == 200, f"页面 {path} 返回 {r.status_code}（重试3次仍失败）"

    @pytest.mark.frontend
    def test_page_has_html(self):
        """首页返回有效 HTML"""
        import time
        for attempt in range(3):
            r = httpx.get("http://127.0.0.1:8888/", timeout=10, proxy=None)
            if "<!DOCTYPE html>" in r.text or "<html" in r.text:
                break
            time.sleep(2)
        assert "<!DOCTYPE html>" in r.text or "<html" in r.text


class TestFrontendNoBybit:
    """前端不应包含 Bybit"""

    @pytest.mark.frontend
    def test_no_bybit_in_source(self):
        """前端源码中不应有 Bybit 引用"""
        matches = [
            path.relative_to(REPO_ROOT)
            for suffix in ("*.ts", "*.tsx")
            for path in (FRONTEND_DIR / "src").rglob(suffix)
            if "bybit" in path.read_text(encoding="utf-8").lower()
        ]
        assert not matches, "前端仍有 Bybit 引用:\n" + "\n".join(map(str, matches))
