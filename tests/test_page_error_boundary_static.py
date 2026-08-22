from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_dynamic_import_error_auto_reloads_without_failure_card() -> None:
    source = read_text("frontend/src/components/PageErrorBoundary.tsx")

    assert "isDynamicImportError" in source
    assert "triggerChunkReload" in source
    assert "window.location.reload()" in source
    assert "return null" in source
    assert "isChunkLoadError ? '前端资源已更新或网络加载中断，请刷新页面后重试。'" not in source
