"""AI 策略研发提示词：全部围绕 StockPro Strategy API v1 与 A 股日线约束。"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

STRATEGY_API_RULES = """## StockPro Strategy API v1 硬性约束（违反任何一条代码会被沙箱拒绝）
1. 文件只允许包含：模块 docstring、字面量常量赋值（如 `PARAMS = {...}`）、函数定义。
2. 必须定义 `def initialize(context):` 和 `def handle_data(context, data):`。可选定义 `before_trading_start(context)`、`after_trading_end(context)`。
3. 禁止任何 import；禁止 print/open/eval/exec/__import__/input/globals/locals/vars/getattr/setattr/delattr/help/dir。
4. 禁止访问 os/sys/subprocess/socket/requests/pathlib 等任何外部能力；禁止 dunder 属性。
5. 禁止 datetime.now/today/utcnow：模拟时钟只能用 `context.current_dt`。
6. 可用内置函数：abs all any bool dict enumerate float int len list max min range round set sorted str sum tuple zip Exception ValueError。
7. 允许使用 `math` 模块（math.sqrt/math.isnan 等）和 `log.info/log.warning/log.error` 记录日志。
8. `get_price` 调用不得带 start_date/end_date 参数（防止取未来数据）。

## 平台 API（全部为顶层函数）
- `history(symbol, count, unit="1d", field="close")`：返回截至当前交易日的序列（list 子类，支持 `.mean()`、索引、切片）。field 可为 open/high/low/close/volume/turnover。
- `get_price(symbol, count=1, unit="1d", fields="close")`：fields 为字符串时返回单序列；为列表时返回 {字段: 序列}。
- `get_current_data()`：返回 {symbol: 当日bar}，bar 含 open/high/low/close/volume/turnover 属性。
- 下单：`order(symbol, amount)`、`order_value(symbol, value)`、`order_target(symbol, amount)`、`order_target_value(symbol, value)`、`order_target_percent(symbol, target)`（amount 正数买入、负数卖出）、`cancel_order(order_obj)`。
- `record(**values)` 记录自定义指标；`run_daily(func, time="open")` 注册周期回调。
- `set_option("avoid_future_data", True)` 必须在 initialize 中调用。
- `set_benchmark(symbol)`、`set_order_cost(...)`、`set_slippage(...)` 可选。
- `get_factor_values(factor_code, symbols=None)` 仅在绑定因子快照时返回值，否则为 None 字典。

## context 对象
- `context.current_dt`：模拟时间（datetime）；`context.previous_date`：上一交易日（str）。
- `context.parameters`：dict 运行参数（含 initial_cash）；`context.universe`：证券代码 list；`context.portfolio.cash`：现金。
- 注意：context 必须可 JSON 序列化，只能存放基本类型。

## A 股日线交易约束（引擎层已实现，策略逻辑必须假设成立）
- 只做多；卖出受 T+1 可卖数量限制；委托按 100 股整数手撮合。
- D 日收盘信号最早 D+1 日成交，策略不可能在同一根收盘价上成交。
- 回测区间有限（快速诊断窗口约 40-60 个交易日），信号不宜过于稀疏，确保至少产生 min_trades 笔交易。
- 涨跌停、停牌订单可能被拒绝，逻辑要能容忍空仓日。

## 参考骨架（必须遵守这种结构，不得使用未列出的能力）
```python
'''AI 生成策略。'''

def initialize(context):
    set_option("avoid_future_data", True)
    set_benchmark("000300.SH")

def handle_data(context, data):
    for symbol in context.universe:
        closes = history(symbol, 10, "1d", "close")
        if len(closes) < 10:
            continue
        fast = sum(list(closes)[-3:]) / 3.0
        slow = closes.mean()
        if fast > slow * 1.02 and context.portfolio.cash > 20000:
            order_value(symbol, min(context.portfolio.cash * 0.2, 100000))
        elif fast < slow * 0.98:
            order_target(symbol, 0)
```
"""


def _json_block(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_planner_messages(task: Any) -> List[Dict[str, str]]:
    system = (
        "你是资深 A 股量化策略规划师。你的职责是把用户目标扩展成一份可执行的策略研发规格书，"
        "不写代码。必须考虑 A 股日线、T+1、只做多、涨跌停与停牌约束，并避免过拟合。"
        "只输出严格 JSON。"
    )
    user = f"""## 用户目标
{task.user_prompt or "自动研发一个稳健的 A 股日线多头策略"}

## 绩效目标（硬性阈值）
{_json_block(task.goal.to_dict())}

## 研究环境
- 证券池：{", ".join((task.research_config.get("symbols") or [])[:20])}
- 基准：{task.research_config.get("benchmark_code", "000300.SH")}
- 数据快照：{task.research_config.get("dataset_snapshot_name", "")}（已封存日线）
- 诊断回测窗口：{task.research_config.get("start_date", "")} ~ {task.research_config.get("end_date", "")}（约 {task.research_config.get("event_limit", 45)} 个交易日）

## 输出 JSON 结构
{{
  "market_analysis": "对当前证券池与市场环境的分析（3-5 句）",
  "strategy_candidates": [
    {{"name": "策略名", "description": "进场/出场/风控概述", "fit_reason": "为何适合该目标"}}
  ],
  "recommended_approach": "推荐的策略方向（从候选中选择或综合，2-3 句）",
  "risk_considerations": "风控要点（回撤、仓位、止损、过拟合风险）",
  "iteration_plan": "迭代计划建议（首轮做什么、后续如何 refine/pivot）"
}}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_strategist_messages(
    task: Any,
    contract: Optional[Any],
    handoff_context: str,
    repair_issues: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, str]]:
    system = (
        "你是 A 股量化策略工程师。你只输出符合 StockPro Strategy API v1 硬性约束的纯 Python 策略代码。"
        "代码会被 AST 沙箱静态校验并在隔离进程中回放，任何违规能力调用都会被拒绝。只输出严格 JSON。"
    )
    spec_text = task.strategy_spec.to_dict() if task.strategy_spec else {}
    contract_text = contract.to_dict() if contract else {}
    sections = [
        "## 任务目标",
        task.user_prompt or "自动研发一个稳健的 A 股日线多头策略",
        "## 绩效目标",
        _json_block(task.goal.to_dict()),
        "## Planner 规格书",
        _json_block(spec_text),
        "## 本轮 Sprint 合约",
        _json_block(contract_text),
    ]
    if handoff_context:
        sections.append("## 上一轮交接文档（Context Reset，不要重复上一轮的失败）")
        sections.append(handoff_context)
    if repair_issues:
        sections.append("## 上一版代码的沙箱拒绝原因（必须全部修复）")
        sections.append(_json_block(repair_issues))
    sections.append(STRATEGY_API_RULES)
    sections.append("""## 输出 JSON 结构
{
  "strategy_name": "简短策略名（中文，不超过 12 字）",
  "strategy_code": "完整策略 Python 代码（一个字符串，保留换行）",
  "reasoning": "本轮设计思路（3-5 句，说明与合约的对应关系）"
}""")
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n\n".join(sections)}]


def build_evaluator_messages(
    task: Any,
    record: Any,
    contract: Optional[Any],
) -> List[Dict[str, str]]:
    system = (
        "你是独立于策略工程师的 A 股策略评审。基于回测指标与代码质量做多维评分，"
        "并给出下一轮方向建议（refine=继续优化 / pivot=换方向）。只输出严格 JSON。"
    )
    user = f"""## 任务目标
{task.user_prompt or "自动研发一个稳健的 A 股日线多头策略"}

## 绩效目标（硬性阈值）
{_json_block(task.goal.to_dict())}

## 本轮 Sprint 合约
{_json_block(contract.to_dict() if contract else {})}

## 回测指标（快速诊断窗口）
{_json_block(record.backtest_metrics)}

## 策略代码
```python
{record.strategy_code}
```

## 输出 JSON 结构
{{
  "eval_scores": {{
    "risk_control": 0, "profitability": 0, "robustness": 0,
    "strategy_logic": 0, "originality": 0
  }},
  "meets_goal": false,
  "analysis": "综合评审（3-6 句，指出关键弱点）",
  "suggestions": ["下一轮的具体改进建议（最多 5 条）"],
  "next_action": "refine 或 pivot"
}}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_handoff_context(task: Any, record: Any) -> str:
    """Context Reset：用结构化交接文档代替累积对话。"""
    lines = [
        f"第 {record.iteration + 1} 轮结果：{'达标' if record.meets_goal else '未达标'}（综合分 {record.score:.1f}）",
        f"行动：{record.action}",
    ]
    if record.error:
        lines.append(f"失败原因：{record.error[:500]}")
    if record.backtest_metrics:
        keys = ("strategy_return", "sharpe", "maximum_drawdown", "win_rate", "profit_loss_ratio", "completed_trades")
        lines.append("指标：" + "，".join(
            f"{key}={_fmt(record.backtest_metrics.get(key))}" for key in keys
        ))
    if record.analysis:
        lines.append(f"评审结论：{record.analysis[:800]}")
    if record.suggestions:
        lines.append("改进建议：" + "；".join(record.suggestions[:5]))
    return "\n".join(lines)


def _fmt(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)
