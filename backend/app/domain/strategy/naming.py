"""StockPro strategy / Paper instance display names.

Canonical form:

    [市场][周期][风格] 策略简称

Example: ``[A股][日线][打板] 首板放量隔日T``

The live / strategy pages already show timeframe and capital as separate
pills, so names must not repeat Paper / 模拟盘 / 100万 / dates / sprint labels.
"""
from __future__ import annotations

import re

CANONICAL_EXAMPLE = "[A股][日线][打板] 首板放量隔日T"
NAME_RULE = "[市场][周期][风格] 策略简称"

MARKETS = ("A股", "ETF")
TIMEFRAMES = ("日线", "60分", "30分", "15分", "5分")

CANONICAL_PATTERN = re.compile(
    r"^\[(?P<market>A股|ETF)\]\[(?P<timeframe>日线|60分|30分|15分|5分)\]"
    r"\[(?P<style>[^\]]{2,12})\] (?P<title>\S(?:.*\S)?)$"
)

_PREFIX = re.compile(r"^(?:Paper|模拟盘|模拟)\s*[-·/]?\s*", re.IGNORECASE)
_SUFFIX = re.compile(
    r"(?:\s*[-·/]\s*(?:Paper|模拟盘|封存回放模拟盘|100万|1,?000,?000(?:CNY)?))+$",
    re.IGNORECASE,
)
_SPRINT = re.compile(r"^Sprint\s*\d+\s+", re.IGNORECASE)
_DATE = re.compile(r"\s+\d{4}-\d{2}-\d{2}\b")
_TRAILING_PUNCT = re.compile(r"[。．.]+$")
_FORBIDDEN = re.compile(
    r"paper|sprint|e2e_|test probe|minimal research|research chain|验收|100万|模拟盘",
    re.IGNORECASE,
)

_ALIASES = {
    "StockPro minimal research chain": "[A股][日线][动量] 最小研究链",
    "全链路交易日": "[A股][日线][事件] 交易日全链路",
    "参与率拒单": "[A股][日线][事件] 参与率拒单",
    "五日回放": "[A股][日线][事件] 五日回放",
    "多因子风险预算": "[A股][日线][多因子] 风险预算",
    "A股多股动量模板": "[A股][日线][动量] 多股模板",
    "MA5 Reference": "[A股][日线][趋势] MA5参考",
}


def _collapse(value: str) -> str:
    return " ".join(str(value or "").split())


def _alias_lookup(text: str) -> str | None:
    if text in _ALIASES:
        return _ALIASES[text]
    stripped_acceptance = re.sub(r"验收$", "", text).strip()
    if stripped_acceptance != text and stripped_acceptance in _ALIASES:
        return _ALIASES[stripped_acceptance]
    return None


def normalize_strategy_name(raw: str) -> str:
    text = _collapse(raw)
    if not text:
        return ""
    changed = True
    while changed:
        previous = text
        text = _PREFIX.sub("", text)
        text = _SUFFIX.sub("", text)
        text = _DATE.sub("", text)
        text = _TRAILING_PUNCT.sub("", text)
        text = _collapse(text)
        changed = text != previous
    aliased = _alias_lookup(text)
    if aliased:
        return aliased
    unsprinted = _collapse(_SPRINT.sub("", text))
    if unsprinted and unsprinted != text:
        aliased = _alias_lookup(unsprinted)
        if aliased:
            return aliased
        if is_valid_strategy_name(unsprinted):
            return unsprinted
    return text


def is_valid_strategy_name(name: str) -> bool:
    match = CANONICAL_PATTERN.fullmatch(name)
    if not match:
        return False
    if _FORBIDDEN.search(name):
        return False
    if _DATE.search(f" {name}"):
        return False
    title = match.group("title")
    if len(title) > 40:
        return False
    return True


def display_strategy_name(raw: str, *, fallback: str = "") -> str:
    cleaned = normalize_strategy_name(raw)
    if is_valid_strategy_name(cleaned):
        return cleaned
    return cleaned or fallback or _collapse(raw)


def require_strategy_name(raw: str) -> str:
    cleaned = normalize_strategy_name(raw)
    if not cleaned:
        raise ValueError("策略名称必填")
    if not is_valid_strategy_name(cleaned):
        raise ValueError(
            f"策略名称须为「{NAME_RULE}」，例如「{CANONICAL_EXAMPLE}」。"
            "不要写 Paper、模拟盘、资金、Sprint、验收或日期。"
        )
    return cleaned
