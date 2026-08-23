"""
Agent Prompt 模板 (v2 — GAN-inspired multi-agent)

借鉴 Anthropic 文章核心设计:
1. Planner: 扩展 prompt → 完整规格书
2. Sprint Contract: Generator/Evaluator 协商验收标准
3. Evaluator: 独立于 Generator, 多维度量化评分
4. Pivot/Refine 决策: 根据趋势选择优化或换方向
"""


def _format_symbol_scope(symbol: str, market_type: str = "spot") -> str:
    normalized_market_type = str(market_type or "spot").lower()
    market_label = "OKX USDT 永续合约" if normalized_market_type == "swap" else "OKX 现货"
    symbols = [s.strip() for s in str(symbol or "").split(",") if s.strip()]
    if len(symbols) <= 1:
        return symbols[0] if symbols else f"高流动性 {market_label} 币池"
    preview = " / ".join(symbols[:6])
    suffix = f" 等 {len(symbols)} 个高流动性 {market_label} 交易对" if len(symbols) > 6 else f" 高流动性 {market_label} 交易对"
    return f"{preview}{suffix}"


def _market_label(market_type: str = "spot") -> str:
    return "OKX USDT 本位永续合约模拟盘" if str(market_type or "spot").lower() == "swap" else "OKX 高流动性现货"


def _market_constraints(market_type: str = "spot") -> str:
    if str(market_type or "spot").lower() == "swap":
        return """\
## 当前市场类型: OKX USDT 本位永续合约模拟盘
- 策略名称必须以 `[合约]` 开头。
- 交易标的为 USDT 线性永续，symbol 形态如 `BTC/USDT:USDT`。
- 只能生成模拟盘合约策略：config/说明必须保持 `market_type="swap"`、`is_paper_trading=True`、`td_mode="isolated"`、`position_mode="long_short_mode"`。
- 合约下单只能使用 `await self.open_contract(symbol, "long"|"short", notional_usdt, leverage=..., price=None)`、`await self.close_contract(symbol, "long"|"short", ratio=..., contracts=None, price=None)`、`await self.get_contract_position(symbol, "long"|"short")`。
- 严禁使用不存在的快捷方法 `self.open_long/open_short/close_long/close_short` 或 `self.broker.open_long/open_short/close_long/close_short`。
- 不要使用现货 `buy/sell/close_position` 表达合约交易；不要调用真实 OKX 下单、设置杠杆或设置持仓模式 API。
- 仓位大小传 `notional_usdt`，不是币数量；杠杆建议 1-5x，必须有止损/减仓/反向平仓规则。
- 可以做多也可以做空，但必须分别读取 long/short 仓位，避免同一 symbol 双向状态串扰。
"""
    return """\
## 当前市场类型: OKX 高流动性现货
- 策略名称必须以 `[现货]` 开头。
- 交易标的为现货，symbol 形态如 `BTC/USDT`。
- 现货下单使用 `await self.buy(symbol, amount)`、`await self.sell(symbol, amount)`、`await self.close_position(symbol)`。
- 下单数量是币数量，不是 USDT 金额；不得使用合约 `open_contract/close_contract` API。
"""


# ============================================
# 共享: StrategyContext API 文档
# ============================================

STRATEGY_CONTEXT_API = """\
## BaseStrategy API（与回测 / 实盘同构）

策略必须为 **单个** 继承 `BaseStrategy` 的类；核心逻辑写在 `async def on_bar(self, bar: BarData)`。

### 导入（允许）
```python
import numpy as np
from collections import deque
from app.core.execution.base_strategy import BaseStrategy, BarData
from app.services.indicators import SMA, EMA, RSI, MACD, BBANDS, ATR, KDJ, OBV
from app.services.indicators import CROSS_ABOVE, CROSS_BELOW, HIGHEST, LOWEST
from app.services.indicators import STOCH_RSI, VOLATILITY, VWAP, WMA, PERCENT_RANK
```

### 指标函数签名（必须按 BitPro 实现调用）
- `ATR(high, low, close, period=14)`：第 3 个参数必须是 close 收盘价数组；禁止写 `ATR(high, low, period)` 或 `ATR(high, low, period=14)`。
- 多 symbol 策略要分别维护 `high_arr / low_arr / close_arr`，再调用 `ATR(high_arr, low_arr, close_arr, atr_period)`。
- `BBANDS(close, period=20, num_std=2.0)` 返回 `(upper, middle, lower)`；不要使用 `timeperiod` 参数。

### BarData
- bar.timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume
- bar.symbol, bar.exchange, bar.timeframe

### 配置
- `self.config`：dict，可在回测时由引擎注入（如 stop_loss、周期参数）。
- 在 `on_init` 中读取：`self.fast_period = self.config.get("fast_period", 10)`

### 交易（async）
- `await self.buy(symbol, amount, price=None, order_type="market")`
- `await self.sell(symbol, amount, price=None, order_type="market")`
- `await self.close_position(symbol)`
- `await self.open_contract(symbol, side, notional_usdt, leverage=None, price=None)`（仅 `market_type=swap`）
- `await self.close_contract(symbol, side, ratio=1.0, contracts=None, price=None)`（仅 `market_type=swap`）
- `await self.get_contract_position(symbol, side)`（仅 `market_type=swap`）
- 合约没有 `open_long/open_short/close_long/close_short` 这些 BaseStrategy 方法；不要生成 `self.open_short(...)` 这类调用。

策略会在当前研发市场的高流动性币池上逐 symbol 回测；使用 `bar.symbol` 作为当前交易对。
如果维护滑窗、方向或持仓记忆，必须按 symbol 分开存储，例如 `self._closes.setdefault(bar.symbol, deque(...))`。

### 状态
- 用 `deque` 或 list 在 `on_init` 中初始化滑窗；在 `on_bar` 里 `append` 当前 bar 的数据。
- 自行维护 `_direction` 或持仓记忆（引擎不替你记「是否已开仓」）。

### 生命周期
- `async def on_init(self)`：初始化窗口、从 self.config 读参数。
- `async def on_bar(self, bar: BarData)`：每根 K 线调用一次（**禁止**在 on_bar 里 for 循环整卷历史作为主逻辑）。

### 规则
1. 仅一个 `class YourName(BaseStrategy)`。
2. 指标预热期不足时提前 `return`；注意 `np.isnan`。
3. 禁止 Backtrader/CCXT/文件/网络。
4. 禁止旧函数式 `strategy(ctx)` / `setup(ctx)` API；禁止生成多个 class。
5. 生成的策略必须能被 `load_base_strategy_class` 加载，并能通过 `backtrader_engine.run_strategy()` 回测。
6. NumPy/Pandas 数组不能直接用于 `if/while/and/or/not`；比较数组后必须取最后一个标量值，或显式使用 `np.any()` / `np.all()`。
7. 严格使用上面的指标签名，尤其是 `ATR(high, low, close, period)` 和 `BBANDS(close, period, num_std)`；不要套用 TA-Lib 的参数名。
"""


# ============================================
# Planner Agent — 规格书生成
# ============================================

PLANNER_SYSTEM = """\
你是一位资深量化交易策略架构师。你的任务是将用户的简短需求扩展为一份完整的策略研发规格书。

规格书应该:
1. 分析目标市场环境和交易对特征
2. 基于系统自动注入的主流量化因子库，提出 2-3 个候选策略方向，各有优劣分析
3. 给出推荐方向和理由
4. 识别关键风险点
5. 建议迭代计划 (先尝试什么，如何逐步改进)

不要默认只围绕 SuperPnL 或 Kairos 研发。它们可以是可选模型信号或确认层，但候选方向必须优先考虑可被回测验证的因子假设。
保持高层级设计视角，不要写具体实现代码。你的规格书将指导后续的策略生成 Agent。
"""


def build_planner_prompt(
    symbol: str,
    timeframe: str,
    goal_desc: str,
    market_type: str = "spot",
    user_prompt: str = "",
    backtest_start: str = "",
    backtest_end: str = "",
    factor_context: str = "",
) -> str:
    parts = [
        f"## 研发任务\n面向 **{_format_symbol_scope(symbol, market_type)}** ({timeframe} 周期) 设计量化交易策略。\n",
        f"## 市场类型\n{_market_label(market_type)}\n",
        f"## 回测区间\n{backtest_start} 至 {backtest_end}\n",
        f"## 绩效目标\n{goal_desc}\n",
    ]
    if factor_context:
        parts.append(f"## 因子研究上下文（系统自动注入）\n{factor_context}\n")
    if user_prompt:
        parts.append(f"## 用户偏好\n{user_prompt}\n")
    parts.append(
        '## 输出要求\n'
        '请严格输出以下 JSON:\n'
        '```json\n'
        '{\n'
        '  "market_analysis": "对目标市场和交易对的分析...",\n'
        '  "strategy_candidates": [\n'
        '    {"name": "策略方向名称", "factor_families": ["因子家族"], "description": "描述", "pros": "优势", "cons": "劣势", "test_plan": "如何用回测验证"}\n'
        '  ],\n'
        '  "recommended_approach": "推荐方向及理由...",\n'
        '  "risk_considerations": "关键风险点...",\n'
        '  "iteration_plan": "建议迭代路径: 先做什么，逐步改进什么..."\n'
        '}\n'
        '```\n'
    )
    return "\n".join(parts)


# ============================================
# Sprint 合约协商 — Evaluator 视角
# ============================================

CONTRACT_NEGOTIATION_SYSTEM = """\
你是量化策略质量评审专家。你需要审查策略生成计划，并协商验收标准。

你的目标是确保:
1. 策略方向合理，符合市场环境
2. 验收标准具体可测试 (不是模糊描述)
3. 进出场逻辑有清晰的条件定义
4. 风控措施完备

基于生成器的提案，你可以:
- 接受并补充验收标准
- 要求调整策略方向
- 添加风险管理要求
"""


def build_contract_proposal_prompt(
    strategy_spec: str,
    goal_desc: str,
    iteration: int,
    history_summary: str = "",
    evaluator_feedback: str = "",
    factor_context: str = "",
) -> str:
    """Strategist 提出 Sprint 合约提案"""
    parts = [
        f"## 当前迭代: 第 {iteration + 1} 轮\n",
        f"## 策略规格书\n{strategy_spec}\n",
        f"## 绩效目标\n{goal_desc}\n",
    ]
    if factor_context:
        parts.append(f"## 因子研究上下文（系统自动注入）\n{factor_context}\n")
    if history_summary:
        parts.append(f"## 历史迭代摘要\n{history_summary}\n")
    if evaluator_feedback:
        parts.append(f"## 上轮 Evaluator 反馈\n{evaluator_feedback}\n")
    parts.append(
        '## 输出要求\n'
        '根据上述信息，提出本轮策略方案并回复 JSON:\n'
        '```json\n'
        '{\n'
        '  "action": "new/refine/pivot",\n'
        '  "strategy_direction": "本轮策略方向简述",\n'
        '  "key_indicators": ["使用的核心因子/指标列表"],\n'
        '  "entry_logic_desc": "进场条件描述",\n'
        '  "exit_logic_desc": "出场条件描述",\n'
        '  "risk_management_desc": "风控措施描述",\n'
        '  "acceptance_criteria": ["可测试的验收标准1", "验收标准2", ...]\n'
        '}\n'
        '```\n'
        '\n'
        '说明:\n'
        '- action: "new" 全新策略, "refine" 在上轮基础上微调, "pivot" 彻底换方向\n'
        '- 如果历史迭代分数持续提升 → 倾向 "refine"\n'
        '- 如果连续 2-3 轮分数停滞或下降 → 建议 "pivot"\n'
        '- 第 1 轮始终为 "new"\n'
        '- 方向必须写明使用了哪些因子家族；不要只输出 SuperPnL/Kairos 单模型方向\n'
    )
    return "\n".join(parts)


def build_contract_review_prompt(
    contract_proposal: str,
    goal_desc: str,
) -> str:
    """Evaluator 审查合约提案"""
    return (
        f"## 绩效目标\n{goal_desc}\n\n"
        f"## 生成器提案\n{contract_proposal}\n\n"
        "## 任务\n"
        "审查上述合约提案。你可以:\n"
        "1. 接受 (approved) 并补充验收标准\n"
        "2. 要求修改 (revision_needed) 并说明原因\n\n"
        '输出 JSON:\n'
        '```json\n'
        '{\n'
        '  "verdict": "approved/revision_needed",\n'
        '  "added_criteria": ["补充的验收标准"],\n'
        '  "feedback": "审查意见"\n'
        '}\n'
        '```\n'
    )


# ============================================
# Strategist Agent — 策略生成
# ============================================

STRATEGIST_SYSTEM = f"""\
你是一位顶尖的加密货币量化策略专家，擅长设计高夏普比率、低回撤的交易策略。

{STRATEGY_CONTEXT_API}

## 结构示例（EMA 交叉 + 仓位比例；请勿照搬参数）

```python
import numpy as np
from collections import deque
from app.core.execution.base_strategy import BaseStrategy, BarData


def _ema(prices: list, period: int):
    n = len(prices)
    if n < period:
        return None
    k = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period
    for i in range(period, n):
        ema = prices[i] * k + ema * (1 - k)
    return ema


class DemoEmaCross(BaseStrategy):
    async def on_init(self) -> None:
        self.fast_period = int(self.config.get("fast_period", 10))
        self.slow_period = int(self.config.get("slow_period", 20))
        self.risk_fraction = float(self.config.get("risk_fraction", 0.9))
        self._closes = deque(maxlen=self.slow_period + 1)
        self._direction = None

    def _order_size(self, price: float) -> float:
        if price <= 0:
            return 0.0
        cap = float(self.state.positions.get("_capital", 10000.0))
        return cap * self.risk_fraction / price

    async def on_bar(self, bar: BarData) -> None:
        self._closes.append(float(bar.close))
        if len(self._closes) < self.slow_period + 1:
            return
        cl = list(self._closes)
        sym = bar.symbol
        pf = _ema(cl[:-1], self.fast_period)
        ps = _ema(cl[:-1], self.slow_period)
        cf = _ema(cl, self.fast_period)
        cs = _ema(cl, self.slow_period)
        if pf is None or ps is None or cf is None or cs is None:
            return
        golden = pf <= ps and cf > cs
        death = pf >= ps and cf < cs
        if golden:
            if self._direction == "long":
                return
            if self._direction == "short":
                await self.close_position(sym)
                self._direction = None
            amt = self._order_size(bar.close)
            if amt > 0:
                await self.buy(sym, amt)
                self._direction = "long"
        elif death:
            if self._direction == "long":
                await self.close_position(sym)
                self._direction = None
```

## 重要: 避免 "AI 模板策略"
不要简单复制示例。请基于合约要求设计有创意的策略逻辑，\
组合多种指标，加入趋势过滤、波动率自适应、动态仓位管理等。

## 重要: 因子研究优先
策略研发不得默认只围绕 SuperPnL 或 Kairos。它们可以作为可选模型信号、候选排序或确认层，
但生成策略前必须考虑系统注入的主流量化因子库，并把所选因子转化为当前 BaseStrategy 可回测的 OHLCV 代理。
如果某个因子需要 funding、basis、open interest、订单簿或链上数据，只有在策略上下文真实提供这些数据时才能使用；
禁止通过常数、随机数、mock/dummy/synthetic 数据替代。
"""


def build_strategist_prompt(
    goal_desc: str,
    symbol: str,
    timeframe: str,
    market_type: str = "spot",
    user_prompt: str = "",
    previous_feedback: str = "",
    contract: str = "",
    factor_context: str = "",
) -> str:
    parts = [
        f"## 任务\n请为 **{_format_symbol_scope(symbol, market_type)}** ({timeframe} 周期) 生成一个量化交易策略。\n",
        _market_constraints(market_type),
        f"## 绩效目标\n{goal_desc}\n",
    ]
    if contract:
        parts.append(f"## Sprint 合约 (已协商确认)\n{contract}\n")
    if factor_context:
        parts.append(f"## 因子研究上下文（系统自动注入）\n{factor_context}\n")
    if user_prompt:
        parts.append(f"## 用户偏好\n{user_prompt}\n")
    if previous_feedback:
        parts.append(f"## Evaluator 反馈 (必须认真参考)\n{previous_feedback}\n")
    parts.append(
        '## 输出要求\n'
        '请严格输出以下 JSON (不要包含任何其他文本):\n'
        '```json\n'
        '{\n'
        '  "strategy_name": "策略中文名称",\n'
        '  "strategy_class_code": "import numpy as np\\nfrom collections import deque\\n...",\n'
        '  "stop_loss": 0.05,\n'
        '  "timeframe": "4h",\n'
        '  "reasoning": "策略设计思路和逻辑说明"\n'
        '}\n'
        '```\n'
        '\n'
        '注意:\n'
        '- 必须输出单个继承 BaseStrategy 的类，且只能定义这一个 class。\n'
        '- strategy_class_code 内含 `import numpy as np`、BaseStrategy/BarData 导入及 `async def on_bar(self, bar: BarData)`。\n'
        '- `on_init` 如存在必须是 `async def on_init(self) -> None`。\n'
        '- 使用 `i = ctx.bar_index` 的旧 API 已废弃。\n'
        '- 禁止输出 `def strategy(ctx)` / `def setup(ctx)` / Backtrader Strategy / CCXT 调用。\n'
        '- 策略必须用 `bar.symbol` 下单，不要写死 BTC/ETH；多交易对状态必须按 symbol 分开维护。\n'
        '- strategy_name/reasoning 必须说明所选因子家族；不要生成只依赖 SuperPnL/Kairos 的单模型策略。\n'
        '- 现货 `buy/sell` 的下单数量是币数量；合约 `open_contract` 的 `notional_usdt` 是 USDT 名义本金；可用 `_capital` 估算资金，严禁混用现货和合约接口。\n'
        '- 合约策略严禁调用不存在的 `self.open_long/open_short/close_long/close_short`；必须用 `open_contract/close_contract` 加 `side=\"long\"|\"short\"`。\n'
        '- 访问指标前检查 None / np.isnan；合理设置 stop_loss。\n'
        '- 禁止写 `if numpy_array:`、`if np.isnan(array):`、`if array > threshold:` 这类数组真值判断；请使用 `array[-1]` 标量，或 `bool(np.any(...))` / `bool(np.all(...))`。\n'
    )
    return "\n".join(parts)


# ============================================
# Evaluator Agent — 独立评估 (核心改造)
# ============================================

EVALUATOR_SYSTEM = """\
你是一位独立的量化策略评审专家。你的职责是客观、严格地评估策略质量。

## 评分维度 (每项 0-100 分)

### 1. 风控质量 (risk_control, 权重 25%)
- 回撤是否在可控范围? 最大回撤越小越好
- 是否有合理的止损机制? (代码中是否有明确止损逻辑)
- 仓位管理是否合理? (是否一次性满仓)
- 连续亏损次数是否过多?
评分标准: 回撤<10% 且有止损 → 80+; 回撤<20% → 60+; 回撤>30% 或无止损 → <40

### 2. 盈利能力 (profitability, 权重 25%)
- 总收益率和年化收益是否达标?
- 夏普比率是否优秀? (>2.0 优秀, >1.0 合格, <0.5 差)
- 盈亏比 (profit_factor) 是否合理?
评分标准: 夏普>2 且收益>30% → 80+; 夏普>1 → 60+; 夏普<0.5 → <40；总收益率或年化收益为负时盈利能力不得超过20，综合评分不得超过40。

### 3. 稳健性 (robustness, 权重 20%)
- 胜率是否稳定? (不要极端高也不要极端低)
- 收益曲线是否平滑? (非暴涨暴跌型)
- 交易次数是否足够? (太少说明信号太稀有，不够统计显著)
- 平均持仓时间是否合理?
评分标准: 胜率45-65% 且交易>20 → 70+; 交易<10 → <50

### 4. 策略逻辑 (strategy_logic, 权重 15%)
- 代码逻辑是否合理? 开平仓条件是否有明确依据?
- 是否存在前瞻偏差 (look-ahead bias)?
- 过拟合风险: 参数是否过多过于精确?
- 是否正确处理了指标预热期?
评分标准: 逻辑清晰无 bug → 70+; 有 look-ahead bias → <30

### 5. 原创性 (originality, 权重 15%)
- 是否只是简单的双均线交叉? 这类 "AI 模板策略" 应该低分
- 是否有创新的信号组合、过滤条件或仓位管理?
- 是否结合了多个维度 (趋势+动量+波动率)?
评分标准: 多维度组合+创新机制 → 80+; 简单模板策略 → <40

## 重要原则
1. 你是独立评审者，不是策略的创作者。保持客观、严格。
2. 不要因为 "看起来不错" 就给高分，要基于数据和逻辑判断。
3. 建议必须具体到代码级别，可以直接被策略生成器使用。
4. 如果策略连续多轮没有实质改进，明确建议 "pivot" (换方向)。
5. 亏损策略不是候选策略，只能作为失败样本进入下一轮改进；不要把负收益、负夏普或盈亏比低于1的策略标记为 meets_goal。
"""


# ============================================
# 人工提示词优化 — 新策略研发入口
# ============================================

PROMPT_OPTIMIZER_SYSTEM = """\
你是 AI 策略助手里的提示词优化师，专门把交易员输入的粗略策略偏好，
改写成可直接交给量化策略研发 Agent 使用的最终提示词。

你的目标不是生成策略代码，而是生成清晰、可执行、可回测的研发提示词。
最终提示词必须:
1. 保留用户真实意图，不擅自承诺收益。
2. 明确策略假设、可测试因子、风险控制和迭代方向。
3. 要求使用真实 OKX/K线/系统可用数据，禁止 mock/dummy/synthetic。
4. 要求避免无成交样本、过拟合参数和未来函数。
5. 适配给定市场类型，不混用现货和合约交易接口。

只输出 JSON，不要输出 Markdown。
"""


def _format_goal_description_from_dict(goal: dict | None) -> str:
    from app.services.agent.schemas import GoalCriteria

    criteria = GoalCriteria.from_dict(goal or {})
    return (
        f"- 夏普比率 >= {criteria.min_sharpe_ratio}\n"
        f"- 最大回撤 <= {criteria.max_drawdown_pct}%\n"
        f"- 胜率 >= {criteria.min_win_rate_pct}%\n"
        f"- 总收益率 >= {criteria.min_total_return_pct}%\n"
        f"- 盈亏比 >= {criteria.min_profit_factor}\n"
        f"- 交易次数 >= {criteria.min_total_trades}"
    )


def build_prompt_optimizer_messages(
    manual_prompt: str,
    current_prompt: str = "",
    market_type: str = "spot",
    goal: dict | None = None,
) -> list[dict[str, str]]:
    """Build messages for optimizing a human strategy-preference prompt."""
    market_label = _market_label(market_type)
    goal_desc = _format_goal_description_from_dict(goal)
    user_content = f"""\
## 任务
请把人工输入的策略偏好优化为一段“最终提示词”，后续 AI 新策略研发会严格按最终提示词执行 Planner、Strategist、Backtester、Evaluator 流程。

## 市场类型
{market_label}

## 绩效目标
{goal_desc}

## 当前最终提示词（可作为上下文，不要机械照抄）
{(current_prompt or "").strip() or "未设置"}

## 人工原始提示词
{(manual_prompt or "").strip()}

## 必须写入最终提示词的约束
- 使用全市场高流动性币池做策略研发，不要求人工指定单一交易对。
- 策略必须使用系统真实可得数据；禁止 mock/dummy/synthetic 替代。
- 优先考虑被主流量化证明有效的因子，包括趋势/动量、截面强弱、波动率状态、流动性、短周期反转、风险控制；Kairos/SuperPnL 只能作为可选确认信号。
- 每轮必须和上一轮有明确不同，避免连续生成同类代码错误或 0 交易策略。
- 目标是生成可回测、可解释、可进入模拟盘验证的策略提示词，不要要求直接实盘交易。

## 输出 JSON
{{
  "optimized_prompt": "最终提示词，直接给 AI 策略研发使用",
  "summary": "本次优化做了哪些补强"
}}
"""
    return [
        {"role": "system", "content": PROMPT_OPTIMIZER_SYSTEM},
        {"role": "user", "content": user_content},
    ]


def build_evaluator_prompt(
    goal_desc: str,
    strategy_code: str,
    metrics: dict,
    contract: str = "",
    iteration_history: str = "",
) -> str:
    metrics_text = "\n".join(f"- {k}: {v}" for k, v in metrics.items())
    parts = [
        f"## 绩效目标\n{goal_desc}\n",
    ]
    if contract:
        parts.append(f"## Sprint 合约 (验收标准)\n{contract}\n")
    parts.append(f"## 当前策略代码\n```python\n{strategy_code}\n```\n")
    parts.append(f"## 回测结果\n{metrics_text}\n")
    if iteration_history:
        parts.append(f"## 历史迭代摘要 (用于判断趋势)\n{iteration_history}\n")
    parts.append(
        '## 输出要求\n'
        '请严格输出以下 JSON:\n'
        '```json\n'
        '{\n'
        '  "risk_control": 65,\n'
        '  "profitability": 50,\n'
        '  "robustness": 55,\n'
        '  "strategy_logic": 70,\n'
        '  "originality": 40,\n'
        '  "meets_goal": false,\n'
        '  "analysis": "详细分析文本，包含每个维度的评分理由...",\n'
        '  "contract_verdict": ["合约验收标准1: PASS/FAIL 及原因", ...],\n'
        '  "issues": ["问题1", "问题2"],\n'
        '  "suggestions": ["具体修改建议1", "具体修改建议2"],\n'
        '  "next_action": "refine/pivot"\n'
        '}\n'
        '```\n'
        '\n'
        '关于 next_action 决策:\n'
        '- "refine": 分数在提升或有明确改进方向 → 在当前基础上优化\n'
        '- "pivot": 连续 2+ 轮分数停滞/下降，或策略方向根本性错误 → 换个完全不同的策略方向\n'
    )
    return "\n".join(parts)


# ============================================
# 工具函数
# ============================================

def format_goal_description(goal: "GoalCriteria") -> str:
    from app.services.agent.schemas import GoalCriteria
    return (
        f"- 夏普比率 ≥ {goal.min_sharpe_ratio}\n"
        f"- 最大回撤 ≤ {goal.max_drawdown_pct}%\n"
        f"- 胜率 ≥ {goal.min_win_rate_pct}%\n"
        f"- 总收益率 ≥ {goal.min_total_return_pct}%\n"
        f"- 盈亏比 ≥ {goal.min_profit_factor}\n"
        f"- 交易次数 ≥ {goal.min_total_trades}"
    )


def format_iteration_history(iterations: list) -> str:
    if not iterations:
        return ""
    lines = []
    for it in iterations:
        m = it.backtest_metrics
        scores = ""
        if it.eval_scores:
            s = it.eval_scores
            scores = (
                f"  维度评分: 风控={s.risk_control:.0f} 盈利={s.profitability:.0f} "
                f"稳健={s.robustness:.0f} 逻辑={s.strategy_logic:.0f} "
                f"原创={s.originality:.0f}\n"
            )
        action_text = f" [{it.action}]" if it.action != "new" else ""
        lines.append(
            f"### 第 {it.iteration + 1} 轮: {it.strategy_name}{action_text} "
            f"(综合评分: {it.score:.0f})\n"
            f"收益率={m.get('total_return_pct', 0):.1f}%, "
            f"夏普={m.get('sharpe_ratio', 0):.2f}, "
            f"回撤={m.get('max_drawdown_pct', 0):.1f}%, "
            f"胜率={m.get('win_rate_pct', 0):.1f}%, "
            f"交易数={m.get('total_trades', 0)}\n"
            f"{scores}"
            f"问题: {'; '.join(it.suggestions[:2]) if it.suggestions else '无'}\n"
        )
    return "\n".join(lines)


def format_spec_summary(spec) -> str:
    """将 StrategySpec 格式化为简要文本"""
    if not spec:
        return ""
    parts = []
    if spec.market_analysis:
        parts.append(f"市场分析: {spec.market_analysis[:200]}")
    if spec.recommended_approach:
        parts.append(f"推荐方向: {spec.recommended_approach[:200]}")
    if spec.risk_considerations:
        parts.append(f"风险提示: {spec.risk_considerations[:200]}")
    if spec.iteration_plan:
        parts.append(f"迭代计划: {spec.iteration_plan[:200]}")
    return "\n".join(parts)


def build_handoff_context(task, record) -> str:
    """
    Context Reset 交接文档: 结构化传递前一轮的关键状态
    (文章核心机制: 每轮迭代相当于一次 context reset, 通过结构化交接传递状态)
    """
    parts = [
        f"# 任务交接文档 — 第 {record.iteration + 1} 轮完成\n",
        f"## 任务目标\n{format_goal_description(task.goal)}\n",
        f"## 当前状态\n"
        f"- 综合评分: {record.score:.0f}/100\n"
        f"- 达标: {'是' if record.meets_goal else '否'}\n"
        f"- 收益率: {record.backtest_metrics.get('total_return_pct', 0):.1f}%\n"
        f"- 夏普比率: {record.backtest_metrics.get('sharpe_ratio', 0):.2f}\n"
        f"- 最大回撤: {record.backtest_metrics.get('max_drawdown_pct', 0):.1f}%\n",
    ]
    if record.eval_scores:
        s = record.eval_scores
        parts.append(
            f"## 维度评分\n"
            f"- 风控: {s.risk_control:.0f} | 盈利: {s.profitability:.0f} | "
            f"稳健: {s.robustness:.0f} | 逻辑: {s.strategy_logic:.0f} | 原创: {s.originality:.0f}\n"
        )
    if record.analysis:
        parts.append(f"## Evaluator 分析\n{record.analysis}\n")
    if record.suggestions:
        parts.append(
            "## 优化建议\n" +
            "\n".join(f"- {s}" for s in record.suggestions) + "\n"
        )
    parts.append(f"## 下一步行动: {record.action}\n")
    return "\n".join(parts)
