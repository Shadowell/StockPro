from __future__ import annotations

from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
TEXT_SUFFIXES = {".env", ".json", ".md", ".py", ".sh", ".toml", ".txt", ".yaml", ".yml"}
FEISHU_WEBHOOK_TOKEN = re.compile(
    r"https://open\.feishu\.cn/open-apis/bot/v2/hook/"
    r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}",
    re.IGNORECASE,
)
FEISHU_CREDENTIAL = re.compile(
    r"(?i)(?:FEISHU_APP_(?:ID|SECRET)|['\"]app_(?:id|secret)['\"])"
    r"\s*[:=]\s*['\"]([^'\"]+)['\"]"
)


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return (
        not value
        or "your_" in lowered
        or "your-" in lowered
        or "placeholder" in lowered
        or "<redacted>" in lowered
        or "xxxx" in lowered
    )


def test_tracked_files_do_not_contain_feishu_credentials() -> None:
    output = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT
    ).decode().split("\0")
    findings: list[str] = []
    for item in output:
        if not item or Path(item).suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = (ROOT / item).read_text(encoding="utf-8", errors="replace")
        if FEISHU_WEBHOOK_TOKEN.search(text):
            findings.append(item)
        for match in FEISHU_CREDENTIAL.finditer(text):
            if not _is_placeholder(match.group(1).strip()):
                findings.append(item)
    assert not sorted(set(findings)), f"tracked Feishu credentials found in: {sorted(set(findings))}"
