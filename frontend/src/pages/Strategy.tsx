import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Trash2, Plus, Code2, Save, X, FileCode, Copy, Search,
  ChevronDown, ChevronRight, Edit3, Zap, TrendingUp,
  BarChart3, Layers, BookOpen, Loader2, CheckCircle2,
  XCircle, ArrowLeft, Clock, Activity,
} from 'lucide-react';
import { strategyApi, agentApi } from '../api/client';
import type { Strategy as StrategyType } from '../types';
import clsx from 'clsx';
import CryptoSelect from '../components/CryptoSelect';
import ThemeDialog from '../components/ThemeDialog';
import StrategyParameterSections from '../components/StrategyParameterSections';
import { getStrategyParameterSections } from '../utils/strategyConfigDisplay';
import { formatTimeframeLabel } from '../utils/timeframe';
import { SELECTED_SEGMENT_CLASS, SELECTED_SEGMENT_COUNT_CLASS } from '../utils/selectionStyles';
import { useAuth } from '../auth/AuthProvider';

function isStrategyRunningOrPaused(status: string | undefined): boolean {
  return status === 'running' || status === 'paused';
}

// ============================================
// 策略模板 — 基于 BaseStrategy 异步架构
// ============================================
export const BITPRO_SOURCE_STRATEGY_TEMPLATES = [
  {
    key: 'kairos_30m_horizon_dca',
    name: 'Kairos 30分钟视界 DCA（1m）',
    category: '预测 / DCA',
    difficulty: '进阶',
    description:
      '与后端 Kairos30mHorizonDcaStrategy 一致：1m 执行、预测约 T+30m、信号通过则固定 USDT 买入、30 根 1m 后 FIFO 卖出。请优先使用种子导入。',
    tags: ['Kairos', 'DCA', '1m'],
    code: `"""使用内置类：config 设 strategy_key=kairos_30m_horizon_dca（见种子）。勿粘贴完整策略源码。"""

from app.core.execution.base_strategy import BaseStrategy, BarData

class _UseSeedKairosDca(BaseStrategy):
    async def on_bar(self, bar: BarData):
        raise RuntimeError("请通过种子/DB 使用 kairos_30m_horizon_dca，勿执行本占位")
`,
    defaultConfig: {
      strategy_key: 'kairos_30m_horizon_dca',
      timeframe: '1m',
      quote_per_order: 10,
      confidence_threshold: 0.24,
      hold_bars: 30,
      window_size: 256,
      warmup_bars: 300,
    },
  },
  {
    key: 'beginner_guide',
    name: '新手入门：如何写自己的策略',
    category: '教程',
    difficulty: '入门',
    description:
      '写给小白：K 线与 on_bar 是干什么的、config 怎么配、何时下单/平仓。内含双均线示例，默认仅日志，可自行打开真实下单行做回测。',
    tags: ['教程', 'BaseStrategy', '双均线'],
    code: `"""
===============================================================================
新手必读 — 用自己的方式写 BitPro 策略（BaseStrategy）
===============================================================================

【1】策略在系统里怎么跑？
  - 回测：引擎按时间顺序喂给你一根根 K 线；每根 K 线会调用一次下面的 on_bar。
  - 实盘：逻辑相同，只是 K 线来自交易所实时推送。你写的这一套代码两种环境共用。

【2】K 线（Bar）里有什么？
  - bar.open / high / low / close / volume：这根 K 线的开高低收、成交量
  - bar.symbol：交易对，如 BTC/USDT（与左侧配置里的交易对一致）
  - bar.timeframe：周期，如 1h、15m（与实例/回测选用的周期一致）

【3】你必须实现的核心：async def on_bar(self, bar)
  - 在这里写「看到当前这根 K 线时，我要不要买/卖」。
  - 用 async/await：下单要写 await self.buy(...) / await self.sell(...)。

【4】配置 self.config（左侧「策略参数 JSON」会注入到这里）
  - 在 on_init 里用 self.config.get("键", 默认值) 读取，方便改参数而不改代码。

【5】怎么查看持仓？
  - pos = self.broker.get_position_size(bar.symbol)  # 正数多仓数量，大概为 0 表示空仓（取决于 broker）

【6】下单金额单位
  - self.buy(symbol, amount) 里的 amount 是币的数量（如 BTC 个数），不是 USDT。
  - 建议先用很小 amount + 回测验证，再考虑实盘。

【7】常见错误
  - 前 N 根 K 线数据不够算指标时：先 return，等窗口攒够（「预热」）。
  - 每根 K 线不要「从头循环整段历史」，只处理当前 bar。

下面是一个「双均线交叉」示例：慢线上穿快线视为简单买入信号，反之为卖出。
默认全部用 logger 打印，真实下单语句已注释 —— 你确认逻辑后再去掉注释。
"""
import logging
import numpy as np
from collections import deque

from app.core.execution.base_strategy import BaseStrategy, BarData
from app.services.indicators import EMA

logger = logging.getLogger(__name__)


class BeginnerMaCrossStrategy(BaseStrategy):
    """双均线教程策略：类名可改，但必须继承 BaseStrategy 且只保留一个策略类。"""

    async def on_init(self):
        # 从配置里读参数；左侧 JSON 里没有的话就用第二个参数的默认值
        self.fast = int(self.config.get("fast_period", 12))
        self.slow = int(self.config.get("slow_period", 26))
        self.order_amount = float(self.config.get("order_amount", 0.001))
        # 只保留最近 slow+5 根收盘价就够了
        self.closes = deque(maxlen=max(self.slow + 5, 32))

        logger.info(
            "策略初始化: fast=%s slow=%s order_amount=%s",
            self.fast,
            self.slow,
            self.order_amount,
        )

    async def on_bar(self, bar: BarData):
        # 把当前收盘价放进滑动窗口
        self.closes.append(float(bar.close))

        # 预热：数据不够算两条 EMA 时直接跳过
        if len(self.closes) < self.slow + 2:
            return

        close_arr = np.array(self.closes, dtype=np.float64)
        fast_series = EMA(close_arr, self.fast)
        slow_series = EMA(close_arr, self.slow)

        f_prev, f_now = float(fast_series[-2]), float(fast_series[-1])
        s_prev, s_now = float(slow_series[-2]), float(slow_series[-1])

        # 金叉：前一天快线在慢线下方，今天在上方
        golden = f_prev <= s_prev and f_now > s_now
        # 死叉：前一天快线在慢线上方，今天在下方
        death = f_prev >= s_prev and f_now < s_now

        pos = self.broker.get_position_size(bar.symbol)

        if golden and pos <= 0:
            logger.info("[信号] 金叉 | bar=%s close=%s", bar.timestamp, bar.close)
            # 确认逻辑后再取消注释，先在回测里试：
            # await self.buy(bar.symbol, self.order_amount)

        elif death and pos > 0:
            logger.info("[信号] 死叉 | 当前持仓=%s", pos)
            # await self.sell(bar.symbol, pos)
            # 或者一键平仓：await self.close_position(bar.symbol)
`,
    defaultConfig: {
      fast_period: 12,
      slow_period: 26,
      order_amount: 0.001,
      timeframe: '1h',
    },
  },
  {
    key: 'empty',
    name: '空白策略模板',
    category: '自定义',
    difficulty: '自定义',
    description: '从零开始编写策略。继承 BaseStrategy，实现 on_bar 即可，支持回测和实盘。',
    tags: ['自定义', '灵活', 'BaseStrategy'],
    code: `"""自定义策略 — BaseStrategy 架构"""
import logging
from collections import deque
from app.core.execution.base_strategy import BaseStrategy, BarData

logger = logging.getLogger(__name__)


class MyStrategy(BaseStrategy):
    async def on_init(self):
        \"\"\"初始化：从 self.config 读取参数，创建 deque 容器。\"\"\"
        self.trade_amount = self.config.get("trade_amount", 0.001)
        self.closes = deque(maxlen=50)

    async def on_bar(self, bar: BarData):
        \"\"\"每根 K 线触发，在此编写交易逻辑。\"\"\"
        self.closes.append(bar.close)
        if len(self.closes) < 20:
            return

        # 示例：获取当前持仓
        pos = self.broker.get_position_size(bar.symbol)

        # 在此编写你的信号逻辑
        # await self.buy(bar.symbol, self.trade_amount)
        # await self.sell(bar.symbol, self.trade_amount)
        # await self.close_position(bar.symbol)
`,
    defaultConfig: { trade_amount: 0.001, timeframe: '1h' },
  },
];

const STRATEGY_TEMPLATES = [
  {
    key: 'a_share_momentum',
    name: 'A 股日线动量轮动',
    category: '动量趋势',
    difficulty: '入门',
    description: '每周选择 20 日动量最强的 A 股标的，按等权方式调仓；使用沪深 300 基准和 A 股成本。',
    tags: ['A股', '日线', '动量'],
    code: `"""A 股日线动量轮动模板。"""
LOOKBACK = 20
TOP_N = 5

def initialize(context):
    set_benchmark("000300.SH")
    set_option("avoid_future_data", True)
    set_order_cost(open_tax=0.0, close_tax=0.0005, commission=0.0003, min_commission=5.0)
    set_slippage(0.001)
    run_weekly(rebalance)

def handle_data(context, data):
    record(held=len(context.portfolio.positions))

def rebalance(context):
    ranked = []
    for symbol in context.universe:
        closes = history(symbol, LOOKBACK + 1, "1d", "close")
        if len(closes) < LOOKBACK + 1 or float(closes[0]) <= 0:
            continue
        ranked.append(((float(closes[-1]) / float(closes[0])) - 1.0, symbol))
    targets = [item[1] for item in sorted(ranked, reverse=True)[:TOP_N]]
    for symbol in list(context.portfolio.positions):
        if symbol not in targets:
            order_target_percent(symbol, 0.0)
    weight = 1.0 / len(targets) if targets else 0.0
    for symbol in targets:
        order_target_percent(symbol, weight)
`,
    defaultConfig: { asset_class: 'stock', timeframe: '1d', capital: '1000000CNY' },
  },
  {
    key: 'a_share_mean_reversion',
    name: 'A 股五日超跌反弹',
    category: '均值回归',
    difficulty: '进阶',
    description: '在 A 股候选池中选择五日跌幅较大的标的，并通过日线调度和等权上限控制风险。',
    tags: ['A股', '日线', '均值回归'],
    code: `"""A 股五日超跌反弹模板。"""
LOOKBACK = 5
TOP_N = 5

def initialize(context):
    set_benchmark("000300.SH")
    set_option("avoid_future_data", True)
    set_order_cost(open_tax=0.0, close_tax=0.0005, commission=0.0003, min_commission=5.0)
    set_slippage(0.001)
    run_daily(rebalance)

def handle_data(context, data):
    record(held=len(context.portfolio.positions))

def rebalance(context):
    ranked = []
    for symbol in context.universe:
        closes = history(symbol, LOOKBACK + 1, "1d", "close")
        if len(closes) < LOOKBACK + 1 or float(closes[0]) <= 0:
            continue
        ranked.append(((float(closes[-1]) / float(closes[0])) - 1.0, symbol))
    targets = [item[1] for item in sorted(ranked)[:TOP_N]]
    for symbol in list(context.portfolio.positions):
        if symbol not in targets:
            order_target_percent(symbol, 0.0)
    weight = 1.0 / len(targets) if targets else 0.0
    for symbol in targets:
        order_target_percent(symbol, weight)
`,
    defaultConfig: { asset_class: 'stock', timeframe: '1d', capital: '1000000CNY' },
  },
  {
    key: 'empty',
    name: 'A 股空白策略模板',
    category: '自定义',
    difficulty: '自定义',
    description: '从 stockpro.v1 安全策略契约开始，使用日线、人民币和 A 股交易规则。',
    tags: ['A股', 'stockpro.v1', '日线'],
    code: `"""A 股自定义策略。"""

def initialize(context):
    set_benchmark("000300.SH")
    set_option("avoid_future_data", True)
    set_order_cost(open_tax=0.0, close_tax=0.0005, commission=0.0003, min_commission=5.0)
    set_slippage(0.001)

def handle_data(context, data):
    record(held=len(context.portfolio.positions))
`,
    defaultConfig: { asset_class: 'stock', timeframe: '1d', capital: '1000000CNY' },
  },
];

const EMPTY_STRATEGY_TEMPLATE = STRATEGY_TEMPLATES.find(t => t.key === 'empty')!;
const STRATEGY_PAGE_SIZE = 18;

type PageView = 'list' | 'editor' | 'detail';
type ListTab = 'my' | 'plaza';
type StrategyStatusFilter = 'all' | 'running' | 'paused' | 'not_started';
type StrategyAssetClass = 'stock' | 'etf';
type StrategyAssetFilter = 'all' | StrategyAssetClass;
type StrategyTypeFilter = 'all' | 'momentum' | 'mean_reversion' | 'multi_factor' | 'event' | 'other';
type StrategyTimeframeFilter = 'all' | '1d';
type StrategyCapitalFilter = 'all' | '1000000CNY';

const STATUS_FILTERS: Array<{
  value: StrategyStatusFilter;
  label: string;
}> = [
  { value: 'all', label: '全部' },
  { value: 'running', label: '运行中' },
  { value: 'paused', label: '暂停' },
  { value: 'not_started', label: '未启动' },
];

const ASSET_FILTERS: Array<{
  value: StrategyAssetFilter;
  label: string;
}> = [
  { value: 'all', label: '全部' },
  { value: 'stock', label: '股票' },
  { value: 'etf', label: 'ETF' },
];

const STRATEGY_TYPE_FILTERS: Array<{
  value: StrategyTypeFilter;
  label: string;
}> = [
  { value: 'all', label: '全部' },
  { value: 'momentum', label: '动量趋势' },
  { value: 'mean_reversion', label: '均值回归' },
  { value: 'multi_factor', label: '多因子' },
  { value: 'event', label: '事件驱动' },
  { value: 'other', label: '其他' },
];

const STRATEGY_TIMEFRAME_FILTERS: Array<{
  value: StrategyTimeframeFilter;
  label: string;
}> = [
  { value: 'all', label: '全部' },
  { value: '1d', label: '1D' },
];

const STRATEGY_CAPITAL_FILTERS: Array<{
  value: StrategyCapitalFilter;
  label: string;
}> = [
  { value: 'all', label: '全部' },
  { value: '1000000CNY', label: '100万' },
];

const MISSING_SELECTION_LOGIC = '该策略尚未补充核心标的说明。';
const MISSING_TRADING_LOGIC = '该策略尚未补充交易逻辑说明。';

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function readTextField(record: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) {
      return value.trim();
    }
  }
  return '';
}

function getStrategyLogicSummary(strategy: StrategyType | null): {
  selectionLogic: string;
  tradingLogic: string;
} {
  const config = isRecord(strategy?.config) ? strategy.config : {};
  const nested = isRecord(config.logicSummary) ? config.logicSummary : {};

  return {
    selectionLogic:
      readTextField(config, ['selectionLogic', 'selection_logic']) ||
      readTextField(nested, ['selection', 'selectionLogic', 'selection_logic']) ||
      MISSING_SELECTION_LOGIC,
    tradingLogic:
      readTextField(config, ['tradingLogic', 'trading_logic']) ||
      readTextField(nested, ['trading', 'tradingLogic', 'trading_logic']) ||
      MISSING_TRADING_LOGIC,
  };
}

function getStrategyConfigArray(config: Record<string, unknown>, keys: string[]): string[] {
  for (const key of keys) {
    const value = config[key];
    if (Array.isArray(value)) {
      return value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0);
    }
  }
  return [];
}

function inferStrategyAssetClass(strategy: StrategyType): StrategyAssetClass {
  const config = isRecord(strategy.config) ? strategy.config : {};
  return readTextField(config, ['assetClass', 'asset_class']).toLowerCase() === 'etf' ? 'etf' : 'stock';
}

function strategyNameColorClass(assetClass: StrategyAssetClass): string {
  return assetClass === 'etf' ? 'text-cyan-300' : 'text-yellow-300';
}

// ============================================
// 主组件
// ============================================
export default function Strategy() {
  const navigate = useNavigate();
  const { isAdmin } = useAuth();
  const canWriteStrategy = isAdmin;
  const canUseAiStrategy = false;
  const [strategies, setStrategies] = useState<StrategyType[]>([]);
  const [isLoadingStrategies, setIsLoadingStrategies] = useState(false);
  const [strategyListError, setStrategyListError] = useState<string | null>(null);
  const [strategyPage, setStrategyPage] = useState(1);
  const [strategyTotal, setStrategyTotal] = useState(0);
  const [strategyPages, setStrategyPages] = useState(1);
  const [strategyRefreshToken, setStrategyRefreshToken] = useState(0);
  const [strategyStatusCounts, setStrategyStatusCounts] = useState<Record<StrategyStatusFilter, number>>({
    all: 0,
    running: 0,
    paused: 0,
    not_started: 0,
  });
  const [strategyAssetCounts, setStrategyAssetCounts] = useState<Record<StrategyAssetFilter, number>>({
    all: 0,
    stock: 0,
    etf: 0,
  });
  const [strategyTypeCounts, setStrategyTypeCounts] = useState<Record<StrategyTypeFilter, number>>({
    all: 0,
    momentum: 0,
    mean_reversion: 0,
    multi_factor: 0,
    event: 0,
    other: 0,
  });
  const [strategyTimeframeCounts, setStrategyTimeframeCounts] = useState<Record<StrategyTimeframeFilter, number>>({
    all: 0,
    '1d': 0,
  });
  const [strategyCapitalCounts, setStrategyCapitalCounts] = useState<Record<StrategyCapitalFilter, number>>({
    all: 0,
    '1000000CNY': 0,
  });
  const [selectedStrategy, setSelectedStrategy] = useState<StrategyType | null>(null);

  // 页面视图
  const [view, setView] = useState<PageView>('list');
  const [listTab, setListTab] = useState<ListTab>('my');
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<StrategyStatusFilter>('all');
  const [assetFilter, setAssetFilter] = useState<StrategyAssetFilter>('all');
  const [strategyTypeFilter, setStrategyTypeFilter] = useState<StrategyTypeFilter>('all');
  const [strategyTimeframeFilter, setStrategyTimeframeFilter] = useState<StrategyTimeframeFilter>('all');
  const [strategyCapitalFilter, setStrategyCapitalFilter] = useState<StrategyCapitalFilter>('all');

  // 创建/编辑模式
  const [editMode, setEditMode] = useState<'create' | 'edit'>('create');
  const [editingStrategy, setEditingStrategy] = useState<StrategyType | null>(null);

  // 编辑器表单
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    scriptContent: EMPTY_STRATEGY_TEMPLATE.code,
    exchange: 'CN',
    symbols: '600519.SH',
    config: JSON.stringify(EMPTY_STRATEGY_TEMPLATE.defaultConfig, null, 2),
  });

  // 状态
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // AI 写策略
  const [showAiGen, setShowAiGen] = useState(false);
  const [aiPrompt, setAiPrompt] = useState('');
  const [aiSymbol, setAiSymbol] = useState('600519.SH');
  const [aiTimeframe, setAiTimeframe] = useState('1d');
  const [aiGenerating, setAiGenerating] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ id: number; name: string } | null>(null);
  const [deleteBlockedOpen, setDeleteBlockedOpen] = useState(false);
  const [logicSummaryOpen, setLogicSummaryOpen] = useState(false);

  const normalizedSearchQuery = searchQuery.trim().toLowerCase();

  const refreshStrategyPage = useCallback(() => {
    setStrategyRefreshToken((value) => value + 1);
  }, []);

  useEffect(() => {
    setStrategyPage(1);
  }, [
    statusFilter,
    assetFilter,
    strategyTypeFilter,
    strategyTimeframeFilter,
    strategyCapitalFilter,
    normalizedSearchQuery,
  ]);

  useEffect(() => {
    if (listTab !== 'my') return;
    let cancelled = false;
    setIsLoadingStrategies(true);
    setStrategyListError(null);
    strategyApi.getPage({
      page: strategyPage,
      perPage: STRATEGY_PAGE_SIZE,
      status: statusFilter,
      assetClass: assetFilter,
      strategyType: strategyTypeFilter,
      timeframe: strategyTimeframeFilter,
      capital: strategyCapitalFilter,
      search: normalizedSearchQuery,
    })
      .then((result) => {
        if (cancelled) return;
        setStrategies(result.items);
        setStrategyTotal(result.total);
        setStrategyPage(result.page);
        setStrategyPages(result.pages);
        setStrategyStatusCounts({
          all: result.statusCounts?.all ?? 0,
          running: result.statusCounts?.running ?? 0,
          paused: result.statusCounts?.paused ?? 0,
          not_started: result.statusCounts?.not_started ?? result.statusCounts?.notStarted ?? 0,
        });
        setStrategyAssetCounts({
          all: result.assetCounts?.all ?? 0,
          stock: result.assetCounts?.stock ?? 0,
          etf: result.assetCounts?.etf ?? 0,
        });
        setStrategyTypeCounts({
          all: result.typeCounts?.all ?? 0,
          momentum: result.typeCounts?.momentum ?? 0,
          mean_reversion: result.typeCounts?.meanReversion ?? result.typeCounts?.mean_reversion ?? 0,
          multi_factor: result.typeCounts?.multiFactor ?? result.typeCounts?.multi_factor ?? 0,
          event: result.typeCounts?.event ?? 0,
          other: result.typeCounts?.other ?? 0,
        });
        setStrategyTimeframeCounts({
          all: result.timeframeCounts?.all ?? 0,
          '1d': result.timeframeCounts?.['1d'] ?? 0,
        });
        setStrategyCapitalCounts({
          all: result.capitalCounts?.all ?? 0,
          '1000000CNY': result.capitalCounts?.['1000000CNY'] ?? 0,
        });
      })
      .catch((err: any) => {
        if (cancelled) return;
        console.error('Failed to fetch paginated strategies:', err);
        setStrategyListError(err?.response?.data?.detail || err?.message || '策略列表加载失败');
        setStrategies([]);
        setStrategyTotal(0);
        setStrategyPages(1);
      })
      .finally(() => {
        if (!cancelled) setIsLoadingStrategies(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    assetFilter,
    listTab,
    normalizedSearchQuery,
    statusFilter,
    strategyCapitalFilter,
    strategyPage,
    strategyRefreshToken,
    strategyTypeFilter,
    strategyTimeframeFilter,
  ]);

  useEffect(() => {
    setLogicSummaryOpen(false);
  }, [selectedStrategy?.id]);

  // 消息自动关闭
  useEffect(() => {
    if (message) {
      const t = setTimeout(() => setMessage(null), 3000);
      return () => clearTimeout(t);
    }
  }, [message]);

  // ============================================
  // AI 写策略
  // ============================================
  const handleAiGenerate = async () => {
    if (!canWriteStrategy) {
      setMessage({ type: 'error', text: '访客只能查看策略，不能生成或修改策略' });
      return;
    }
    if (!aiPrompt.trim()) return;
    setAiGenerating(true);
    try {
      const res = await agentApi.generateStrategy({
        prompt: aiPrompt,
        symbol: aiSymbol,
        timeframe: aiTimeframe,
      });
      setMessage({ type: 'success', text: `策略 [${res.className}] 已生成！刷新列表可见` });
      setShowAiGen(false);
      setAiPrompt('');
      refreshStrategyPage();
    } catch (err: any) {
      setMessage({ type: 'error', text: 'AI 生成失败: ' + (err?.response?.data?.detail || err.message) });
    } finally {
      setAiGenerating(false);
    }
  };

  // ============================================
  // 操作函数
  // ============================================
  const handleCreateFromTemplate = (template: typeof STRATEGY_TEMPLATES[0]) => {
    if (!canWriteStrategy) {
      setMessage({ type: 'error', text: '访客只能查看策略，不能新建策略' });
      return;
    }
    setEditMode('create');
    setEditingStrategy(null);
    setFormData({
      name: template.name,
      description: template.description,
      scriptContent: template.code,
      exchange: 'CN',
      symbols: '600519.SH',
      config: JSON.stringify(template.defaultConfig, null, 2),
    });
    setView('editor');
  };

  const handleEditStrategy = (strategy: StrategyType) => {
    if (!canWriteStrategy) {
      setMessage({ type: 'error', text: '访客只能查看策略，不能编辑策略' });
      return;
    }
    setEditMode('edit');
    setEditingStrategy(strategy);
    setFormData({
      name: strategy.name,
      description: strategy.description || '',
      scriptContent: strategy.scriptContent || '',
      exchange: strategy.exchange || 'CN',
      symbols: strategy.symbols?.join(', ') || '600519.SH',
      config: JSON.stringify(strategy.config || {}, null, 2),
    });
    setView('editor');
  };

  const handleViewStrategyDetails = (strategy: StrategyType) => {
    setSelectedStrategy(strategy);
    setView('detail');
  };

  const handleSave = async () => {
    if (!canWriteStrategy) {
      setMessage({ type: 'error', text: '访客只能查看策略，不能保存策略' });
      return;
    }
    if (!formData.name.trim()) { setMessage({ type: 'error', text: '请输入策略名称' }); return; }
    if (!formData.scriptContent.trim()) { setMessage({ type: 'error', text: '请输入策略代码' }); return; }

    let configObj = {};
    try { configObj = JSON.parse(formData.config); } catch {
      setMessage({ type: 'error', text: '配置 JSON 格式错误' }); return;
    }

    setSaving(true);
    try {
      if (editMode === 'edit' && editingStrategy) {
        await strategyApi.update(editingStrategy.id, {
          name: formData.name,
          description: formData.description,
          scriptContent: formData.scriptContent,
          exchange: formData.exchange,
          symbols: formData.symbols.split(',').map(s => s.trim()).filter(Boolean),
          config: configObj,
        });
        setMessage({ type: 'success', text: '策略保存成功' });
      } else {
        await strategyApi.create({
          name: formData.name,
          description: formData.description,
          scriptContent: formData.scriptContent,
          exchange: formData.exchange,
          symbols: formData.symbols.split(',').map(s => s.trim()).filter(Boolean),
          config: configObj,
        });
        setMessage({ type: 'success', text: '策略创建成功' });
      }
      refreshStrategyPage();
      setView('list');
    } catch (err: any) {
      setMessage({ type: 'error', text: err.response?.data?.detail || '操作失败' });
    } finally {
      setSaving(false);
    }
  };

  const runDeleteStrategy = async () => {
    if (!canWriteStrategy) {
      setDeleteTarget(null);
      setMessage({ type: 'error', text: '访客只能查看策略，不能归档策略' });
      return;
    }
    if (!deleteTarget) return;
    const { id, name } = deleteTarget;
    const cur = strategies.find((x) => x.id === id);
    if (cur && isStrategyRunningOrPaused(cur.status)) {
      setDeleteTarget(null);
      setDeleteBlockedOpen(true);
      return;
    }
    setDeleteTarget(null);
    try {
      await strategyApi.delete(id);
      setMessage({ type: 'success', text: `策略「${name}」已归档，历史版本仍保留` });
      refreshStrategyPage();
    } catch (err: unknown) {
      const e = err as {
        response?: { data?: { error?: { message?: string }; detail?: string } };
      };
      const msg =
        e?.response?.data?.error?.message ||
        (typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : null) ||
        '归档失败';
      setMessage({ type: 'error', text: msg });
    }
  };

  const visibleStrategies = strategies;

  const filteredTemplates = STRATEGY_TEMPLATES.filter(t =>
    t.name.toLowerCase().includes(normalizedSearchQuery) ||
    t.description.toLowerCase().includes(normalizedSearchQuery) ||
    t.tags.some(tag => tag.includes(normalizedSearchQuery))
  );
  const shouldShowBlockingLoading = isLoadingStrategies && visibleStrategies.length === 0;

  // ============================================
  // 渲染：策略列表页
  // ============================================
  const renderListView = () => (
    <div className="space-y-6">
      {/* 顶部标题 + 操作 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Code2 className="w-6 h-6 text-blue-400" />
          <h1 className="text-2xl font-bold text-white">策略中心</h1>
        </div>
        {canWriteStrategy && (
          <div className="flex items-center gap-2">
            {canUseAiStrategy && <button onClick={() => setShowAiGen(!showAiGen)}
              className={clsx(
                'inline-flex h-11 items-center gap-2 rounded-xl border px-4 text-sm font-semibold transition-colors',
                showAiGen
                  ? 'border-purple-500/45 bg-purple-500/25 text-purple-200'
                  : 'border-purple-500/30 bg-purple-500/[0.12] text-purple-200 hover:border-purple-500/45 hover:bg-purple-500/[0.18] hover:text-purple-100'
              )}>
              <Zap className="w-4 h-4" />AI 写策略
            </button>}
            <button onClick={() => handleCreateFromTemplate(EMPTY_STRATEGY_TEMPLATE)}
              className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-sm font-medium transition-colors">
              <Plus className="w-4 h-4" />新建策略
            </button>
          </div>
        )}
      </div>

      {/* AI 写策略面板 */}
      {showAiGen && canWriteStrategy && canUseAiStrategy && (
        <div className="bg-gradient-to-r from-purple-500/5 to-blue-500/5 border border-purple-500/20 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-3">
            <Zap className="w-4 h-4 text-purple-400" />
            <span className="text-sm font-semibold text-white">用自然语言描述你的策略</span>
            <span className="text-[10px] text-gray-500 ml-auto">AI 将自动生成合规的 BaseStrategy 代码</span>
          </div>
          <textarea
            value={aiPrompt}
            onChange={e => setAiPrompt(e.target.value)}
            placeholder="例: 写一个均值回归策略，当 RSI 跌破 30 且价格跌破布林带下轨时买入，RSI 超过 70 时卖出。加上 2% 止损。"
            rows={3}
            className="w-full bg-crypto-bg border border-crypto-border rounded-lg px-4 py-3 text-sm text-white placeholder-gray-600 focus:border-purple-500 focus:outline-none resize-none"
          />
          <div className="flex items-center gap-3 mt-3">
            <CryptoSelect value={aiSymbol} onChange={e => setAiSymbol(e.target.value)} controlSize="xs" fullWidth={false}>
              {['600519.SH', '000001.SZ', '300750.SZ', '510300.SH'].map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </CryptoSelect>
            <CryptoSelect value={aiTimeframe} onChange={e => setAiTimeframe(e.target.value)} controlSize="xs" fullWidth={false}>
              {['1d'].map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </CryptoSelect>
            <div className="flex-1" />
            <button onClick={() => setShowAiGen(false)}
              className="px-4 py-2 text-xs text-gray-400 hover:text-white transition-colors">
              取消
            </button>
            <button onClick={handleAiGenerate} disabled={aiGenerating || !aiPrompt.trim()}
              className="flex items-center gap-2 px-5 py-2 bg-purple-600 hover:bg-purple-700 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded-lg text-sm font-medium transition-colors">
              {aiGenerating ? <><Loader2 className="w-3.5 h-3.5 animate-spin" />生成中...</> : <><Zap className="w-3.5 h-3.5" />生成策略</>}
            </button>
          </div>
        </div>
      )}

      {/* Tab + 搜索 */}
      <div className="space-y-3">
        <div className="inline-flex w-fit items-center gap-1 rounded-xl border border-crypto-border bg-crypto-card p-1">
          <button onClick={() => setListTab('my')}
            className={clsx('px-4 py-2 rounded-lg text-sm font-medium transition-colors',
              listTab === 'my' ? SELECTED_SEGMENT_CLASS : 'text-gray-500 hover:text-gray-300')}>
            <span className="flex items-center gap-1.5"><Layers className="w-3.5 h-3.5" />我的策略</span>
          </button>
          <button onClick={() => setListTab('plaza')}
            className={clsx('px-4 py-2 rounded-lg text-sm font-medium transition-colors',
              listTab === 'plaza' ? SELECTED_SEGMENT_CLASS : 'text-gray-500 hover:text-gray-300')}>
            <span className="flex items-center gap-1.5"><BookOpen className="w-3.5 h-3.5" />策略广场</span>
          </button>
        </div>
        {listTab === 'my' && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <div className="inline-flex h-11 items-center rounded-xl border border-crypto-border bg-crypto-card p-1">
                {ASSET_FILTERS.map((option) => {
                  const active = assetFilter === option.value;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setAssetFilter(option.value)}
                      aria-pressed={active}
                      className={clsx(
                        'inline-flex h-9 min-w-20 items-center justify-center gap-2 rounded-lg px-3 text-xs font-semibold transition-colors',
                        active
                          ? SELECTED_SEGMENT_CLASS
                          : 'text-gray-500 hover:bg-white/5 hover:text-gray-300',
                      )}
                    >
                      <span>{option.label}</span>
                      <span
                        className={clsx(
                          'rounded-md px-1.5 py-0.5 text-[10px]',
                          active ? SELECTED_SEGMENT_COUNT_CLASS : 'bg-crypto-bg text-gray-500',
                        )}
                      >
                        {strategyAssetCounts[option.value] ?? 0}
                      </span>
                    </button>
                  );
                })}
              </div>
              <div className="inline-flex h-11 items-center rounded-xl border border-crypto-border bg-crypto-card/80 p-1">
                {STATUS_FILTERS.map((option) => {
                  const active = statusFilter === option.value;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setStatusFilter(option.value)}
                      aria-pressed={active}
                      className={clsx(
                        'inline-flex h-9 items-center justify-center gap-2 rounded-lg px-3 text-xs font-semibold transition-colors',
                        active
                          ? SELECTED_SEGMENT_CLASS
                          : 'text-gray-500 hover:bg-white/5 hover:text-gray-300',
                      )}
                    >
                      <span>{option.label}</span>
                      <span
                        className={clsx(
                          'rounded-md px-1.5 py-0.5 text-[10px]',
                          active ? SELECTED_SEGMENT_COUNT_CLASS : 'bg-crypto-bg text-gray-500',
                        )}
                      >
                        {strategyStatusCounts[option.value] ?? 0}
                      </span>
                    </button>
                  );
                })}
              </div>
              <div className="inline-flex h-11 items-center rounded-xl border border-crypto-border bg-crypto-card/80 p-1">
                {STRATEGY_TYPE_FILTERS.map((option) => {
                  const active = strategyTypeFilter === option.value;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setStrategyTypeFilter(option.value)}
                      aria-pressed={active}
                      className={clsx(
                        'inline-flex h-9 items-center justify-center gap-2 rounded-lg px-3 text-xs font-semibold transition-colors',
                        active
                          ? SELECTED_SEGMENT_CLASS
                          : 'text-gray-500 hover:bg-white/5 hover:text-gray-300',
                      )}
                    >
                      <span>{option.label}</span>
                      <span
                        className={clsx(
                          'rounded-md px-1.5 py-0.5 text-[10px]',
                          active ? SELECTED_SEGMENT_COUNT_CLASS : 'bg-crypto-bg text-gray-500',
                        )}
                      >
                        {strategyTypeCounts[option.value] ?? 0}
                      </span>
                    </button>
                  );
                })}
              </div>
              {isLoadingStrategies && visibleStrategies.length > 0 && (
                <div className="inline-flex h-11 items-center gap-2 rounded-xl border border-blue-500/20 bg-blue-500/10 px-3 text-xs font-semibold text-blue-300">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  正在刷新
                </div>
              )}
              <label className="relative flex h-11 w-full min-w-[260px] max-w-md items-center rounded-xl border border-crypto-border bg-crypto-card px-3 text-sm text-gray-400 focus-within:border-blue-500/50 focus-within:ring-1 focus-within:ring-blue-500/20 sm:w-[360px]">
                <Search className="mr-2 h-4 w-4 shrink-0 text-gray-500" />
                <span className="sr-only">搜索策略</span>
                <input
                  type="search"
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  placeholder="搜索策略、标的、周期..."
                  className="min-w-0 flex-1 bg-transparent text-sm font-semibold text-gray-200 placeholder:text-gray-600 focus:outline-none"
                />
              </label>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <div className="inline-flex min-h-11 max-w-full flex-wrap items-center gap-1 rounded-xl border border-crypto-border bg-crypto-card/80 p-1">
                {STRATEGY_TIMEFRAME_FILTERS.map((option) => {
                  const active = strategyTimeframeFilter === option.value;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setStrategyTimeframeFilter(option.value)}
                      aria-pressed={active}
                      className={clsx(
                        'inline-flex h-9 items-center justify-center gap-1.5 rounded-lg px-2.5 text-xs font-semibold transition-colors',
                        active
                          ? SELECTED_SEGMENT_CLASS
                          : 'text-gray-500 hover:bg-white/5 hover:text-gray-300',
                      )}
                    >
                      <span>{option.label}</span>
                      <span
                        className={clsx(
                          'rounded-md px-1.5 py-0.5 text-[10px]',
                          active ? SELECTED_SEGMENT_COUNT_CLASS : 'bg-crypto-bg text-gray-500',
                        )}
                      >
                        {strategyTimeframeCounts[option.value] ?? 0}
                      </span>
                    </button>
                  );
                })}
              </div>
              <div className="inline-flex min-h-11 items-center gap-1 rounded-xl border border-crypto-border bg-crypto-card/80 p-1">
                {STRATEGY_CAPITAL_FILTERS.map((option) => {
                  const active = strategyCapitalFilter === option.value;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setStrategyCapitalFilter(option.value)}
                      aria-pressed={active}
                      className={clsx(
                        'inline-flex h-9 items-center justify-center gap-1.5 rounded-lg px-2.5 text-xs font-semibold transition-colors',
                        active
                          ? SELECTED_SEGMENT_CLASS
                          : 'text-gray-500 hover:bg-white/5 hover:text-gray-300',
                      )}
                    >
                      <span>{option.label}</span>
                      <span
                        className={clsx(
                          'rounded-md px-1.5 py-0.5 text-[10px]',
                          active ? SELECTED_SEGMENT_COUNT_CLASS : 'bg-crypto-bg text-gray-500',
                        )}
                      >
                        {strategyCapitalCounts[option.value] ?? 0}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          </>
        )}
      </div>

      {/* 我的策略 Tab */}
      {listTab === 'my' && (
        <div>
          {shouldShowBlockingLoading ? (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
              {Array.from({ length: 6 }).map((_, idx) => (
                <div key={idx} className="h-48 animate-pulse rounded-xl border border-crypto-border bg-crypto-card">
                  <div className="space-y-4 p-5">
                    <div className="h-4 w-2/3 rounded bg-gray-700/60" />
                    <div className="space-y-2">
                      <div className="h-3 rounded bg-gray-800" />
                      <div className="h-3 w-5/6 rounded bg-gray-800" />
                    </div>
                    <div className="flex gap-2">
                      <div className="h-5 w-12 rounded bg-gray-800" />
                      <div className="h-5 w-14 rounded bg-gray-800" />
                      <div className="h-5 w-10 rounded bg-gray-800" />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : strategyListError ? (
            <div className="bg-crypto-card border border-red-500/20 rounded-xl flex flex-col items-center justify-center py-20">
              <XCircle className="w-16 h-16 text-red-400/60 mb-4" />
              <p className="text-red-200 text-sm mb-1">{strategyListError}</p>
              <button
                type="button"
                onClick={refreshStrategyPage}
                className="mt-3 rounded-lg border border-blue-500/30 bg-blue-500/10 px-4 py-2 text-xs font-semibold text-blue-300 transition-colors hover:bg-blue-500/15"
              >
                重新加载
              </button>
            </div>
          ) : visibleStrategies.length === 0 ? (
            <div className="bg-crypto-card border border-crypto-border rounded-xl flex flex-col items-center justify-center py-20">
              <Code2 className="w-16 h-16 text-gray-700 mb-4" />
              <p className="text-gray-500 text-sm mb-1">当前筛选下无策略</p>
              <p className="text-gray-600 text-xs">切换状态筛选，或从策略广场选择模板开始</p>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                {visibleStrategies.map(s => {
                  const updatedAt = (s as any).updatedAt || (s as any).createdAt;
                  const cfg = s.config || {} as any;
                  const assetClass = inferStrategyAssetClass(s);
                  const riskLevel = cfg.risk_level || cfg.riskLevel;
                  const timeframe = cfg.timeframe;
                  const suitableFor = cfg.suitable_for || cfg.suitableFor;
                  const isRecommended = cfg.recommended;
                  const riskColor = riskLevel === '低' ? 'text-green-400 bg-green-500/10 border-green-500/10'
                    : riskLevel === '中' ? 'text-yellow-400 bg-yellow-500/10 border-yellow-500/10'
                    : riskLevel === '中低' ? 'text-green-300 bg-green-500/10 border-green-500/10'
                    : riskLevel === '中高' ? 'text-orange-400 bg-orange-500/10 border-orange-500/10'
                    : 'text-gray-400 bg-gray-500/10 border-gray-500/10';
                  return (
                    <div key={s.id} className="self-start bg-crypto-card border border-crypto-border rounded-xl overflow-hidden hover:border-gray-600 transition-all group">
                      {/* 卡片头部 */}
                      <div className="p-5 pb-3">
                        <div className="flex items-start justify-between mb-2">
                          <div className="flex items-center gap-2.5 min-w-0">
                            <div className={clsx('w-2 h-2 rounded-full flex-shrink-0 mt-1',
                              s.status === 'running' ? 'bg-green-400 animate-pulse'
                                : s.status === 'paused' ? 'bg-yellow-400'
                                  : s.status === 'error' ? 'bg-red-400' : 'bg-gray-600'
                            )} />
                            <h3 className={clsx('text-sm font-semibold truncate', strategyNameColorClass(assetClass))}>{s.name}</h3>
                          </div>
                          <div className="flex items-center gap-1.5 flex-shrink-0">
                            {isRecommended && (
                              <span className="px-1.5 py-0.5 text-[10px] font-bold bg-green-500/20 text-green-400 rounded-full">推荐</span>
                            )}
                            {canWriteStrategy && (
                              <button
                                onClick={() => {
                                  if (isStrategyRunningOrPaused(s.status)) {
                                    setDeleteBlockedOpen(true);
                                    return;
                                  }
                                  setDeleteTarget({ id: s.id, name: s.name });
                                }}
                                className="opacity-0 group-hover:opacity-100 p-1 text-gray-600 hover:text-red-400 transition-all"
                                title="归档策略">
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            )}
                          </div>
                        </div>
                        <p className="text-xs text-gray-500 line-clamp-2 leading-relaxed ml-[18px] min-h-[2.25rem]">
                          {s.description || '暂无描述'}
                        </p>
                      </div>

                      {/* 标签区域 */}
                      <div className="px-5 pb-3 flex items-center gap-1.5 flex-wrap">
                        {s.exchange && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400/80 border border-blue-500/10">
                            {s.exchange.toUpperCase()}
                          </span>
                        )}
                        {riskLevel && (
                          <span className={clsx('text-[10px] px-1.5 py-0.5 rounded border', riskColor)}>
                            {riskLevel}风险
                          </span>
                        )}
                        {timeframe && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-400/80 border border-purple-500/10">
                            {formatTimeframeLabel(timeframe)}
                          </span>
                        )}
                        {s.symbols?.map(sym => (
                          <span key={sym} className="text-[10px] px-1.5 py-0.5 rounded bg-crypto-bg text-gray-500 border border-crypto-border">
                            {sym.split('/')[0]}
                          </span>
                        ))}
                        {updatedAt && (
                          <span className="text-[10px] text-gray-600 flex items-center gap-0.5 ml-auto">
                            <Clock className="w-3 h-3" />
                            {new Date(updatedAt).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })}
                          </span>
                        )}
                      </div>
                      {suitableFor && (
                        <div className="px-5 pb-3">
                          <span className="text-[10px] text-gray-600 flex items-center gap-1">
                            <Zap className="w-3 h-3" />适合: {suitableFor}
                          </span>
                        </div>
                      )}

                      {/* 底部操作 */}
                      <div className="h-11 border-t border-crypto-border grid grid-cols-2 overflow-hidden">
                        <button
                          type="button"
                          onClick={() => {
                            if (isStrategyRunningOrPaused(s.status)) {
                              navigate(`/live?strategyId=${encodeURIComponent(String(s.id))}`);
                            }
                          }}
                          disabled={!isStrategyRunningOrPaused(s.status)}
                          className={clsx(
                            'h-11 min-w-0 flex items-center justify-center gap-1.5 px-3 text-xs border-r border-crypto-border transition-colors',
                            isStrategyRunningOrPaused(s.status)
                              ? 'text-emerald-400 hover:text-emerald-300 hover:bg-emerald-500/10'
                              : 'text-gray-700 cursor-not-allowed',
                          )}
                        >
                          <Activity className="w-3 h-3 shrink-0" />
                          <span className="truncate">实例控制台</span>
                        </button>
                        <button
                          type="button"
                          onClick={() => handleViewStrategyDetails(s)}
                          className={clsx(
                            'h-11 min-w-0 flex items-center justify-center gap-1.5 px-3 text-xs text-gray-400 hover:text-blue-400 hover:bg-blue-500/5 transition-colors',
                          )}
                        >
                          <BookOpen className="w-3 h-3 shrink-0" />
                          <span className="truncate">详情</span>
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
              <div
                aria-label="策略分页"
                className="flex flex-col gap-3 rounded-xl border border-crypto-border bg-crypto-card/70 px-4 py-3 text-sm text-gray-400 sm:flex-row sm:items-center sm:justify-between"
              >
                <span>
                  共 <span className="font-semibold text-gray-200">{strategyTotal}</span> 个策略 · 第{' '}
                  <span className="font-semibold text-gray-200">{strategyPage}</span> / {strategyPages} 页 · 每页{' '}
                  {STRATEGY_PAGE_SIZE}
                </span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setStrategyPage((page) => Math.max(1, page - 1))}
                    disabled={strategyPage <= 1 || isLoadingStrategies}
                    className="rounded-lg border border-crypto-border px-3 py-1.5 text-xs font-semibold text-gray-300 transition-colors hover:border-blue-500/40 hover:text-blue-300 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    上一页
                  </button>
                  <button
                    type="button"
                    onClick={() => setStrategyPage((page) => Math.min(strategyPages, page + 1))}
                    disabled={strategyPage >= strategyPages || isLoadingStrategies}
                    className="rounded-lg border border-crypto-border px-3 py-1.5 text-xs font-semibold text-gray-300 transition-colors hover:border-blue-500/40 hover:text-blue-300 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    下一页
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* 策略广场 Tab - 模板列表 */}
      {listTab === 'plaza' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {filteredTemplates.map(t => (
            <div
              key={t.key}
              className={clsx(
                'bg-crypto-card border border-crypto-border rounded-xl overflow-hidden transition-all group',
                canWriteStrategy ? 'cursor-pointer hover:border-purple-500/40' : 'cursor-default opacity-80',
              )}
              onClick={() => {
                if (canWriteStrategy) handleCreateFromTemplate(t);
              }}
            >
              <div className="p-5 pb-3">
                <div className="flex items-start justify-between mb-2.5">
                  <div className="flex items-center gap-2.5">
                    <div className={clsx('w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0',
                      t.category === '趋势跟踪' ? 'bg-blue-500/15 text-blue-400' :
                      t.category === '套利' ? 'bg-green-500/15 text-green-400' :
                      t.category === '震荡' ? 'bg-yellow-500/15 text-yellow-400' :
                      t.category === '教程' ? 'bg-amber-500/15 text-amber-400' :
                      'bg-gray-500/15 text-gray-400'
                    )}>
                      {t.category === '趋势跟踪' ? <TrendingUp className="w-4 h-4" /> :
                       t.category === '套利' ? <Zap className="w-4 h-4" /> :
                       t.category === '震荡' ? <BarChart3 className="w-4 h-4" /> :
                       t.category === '教程' ? <BookOpen className="w-4 h-4" /> :
                       <Code2 className="w-4 h-4" />}
                    </div>
                    <div>
                      <h3 className="text-sm font-semibold text-white">{t.name}</h3>
                      <span className="text-[10px] text-gray-500">{t.category}</span>
                    </div>
                  </div>
                  <span className={clsx('text-[10px] px-2 py-0.5 rounded-full flex-shrink-0',
                    t.difficulty === '入门' ? 'bg-green-500/15 text-green-400' :
                    t.difficulty === '进阶' ? 'bg-yellow-500/15 text-yellow-400' :
                    'bg-gray-500/15 text-gray-400'
                  )}>
                    {t.difficulty}
                  </span>
                </div>
                <p className="text-xs text-gray-400 leading-relaxed min-h-[2.25rem] line-clamp-2">{t.description}</p>
              </div>
              <div className="px-5 pb-3 flex items-center gap-1.5 flex-wrap">
                {t.tags.map(tag => (
                  <span key={tag} className="text-[10px] px-2 py-0.5 bg-crypto-bg text-gray-500 rounded border border-crypto-border">{tag}</span>
                ))}
              </div>
              <div className="border-t border-crypto-border px-5 py-2.5 flex items-center justify-between">
                <span className="text-[10px] text-gray-600">点击使用此模板</span>
                <ChevronRight className="w-4 h-4 text-gray-600 group-hover:text-purple-400 transition-colors" />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  // ============================================
  // 渲染：策略详情
  // ============================================
  const renderDetailView = () => {
    if (!selectedStrategy) {
      return (
        <div className="flex h-full flex-col items-center justify-center text-sm text-gray-500">
          <Code2 className="mb-3 h-10 w-10 text-gray-700" />
          <p>未选择策略</p>
          <button
            type="button"
            onClick={() => setView('list')}
            className="mt-4 text-blue-400 hover:text-blue-300"
          >
            返回策略列表
          </button>
        </div>
      );
    }

    const config = isRecord(selectedStrategy.config) ? selectedStrategy.config : {};
    const logic = getStrategyLogicSummary(selectedStrategy);
    const tradeSymbols = getStrategyConfigArray(config, ['tradeSymbols', 'trade_symbols']);
    const displaySymbols = tradeSymbols.length > 0 ? tradeSymbols : selectedStrategy.symbols || [];
    const timeframe = readTextField(config, ['timeframe']);
    const assetClass = inferStrategyAssetClass(selectedStrategy);
    const assetClassLabel = assetClass === 'etf' ? 'ETF' : '股票';
    const parameterSections = getStrategyParameterSections(config);

    return (
      <div className="space-y-5">
        <div className="flex items-center justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              onClick={() => setView('list')}
              className="flex items-center gap-1.5 rounded-lg border border-crypto-border bg-crypto-card px-3 py-2 text-sm text-gray-300 transition-colors hover:border-gray-600 hover:text-white"
            >
              <ArrowLeft className="h-4 w-4" />
              返回
            </button>
            <div className="min-w-0">
              <div className="mb-1 flex items-center gap-2">
                <span className={clsx(
                  'rounded-md px-2 py-0.5 text-xs font-semibold',
                  assetClass === 'etf'
                    ? 'bg-cyan-500/15 text-cyan-300'
                    : 'bg-amber-500/15 text-amber-300',
                )}>
                  {assetClassLabel}
                </span>
                {timeframe && <span className="text-xs text-gray-500">{formatTimeframeLabel(timeframe)}</span>}
              </div>
              <h1 className={clsx('truncate text-2xl font-bold', strategyNameColorClass(assetClass))}>{selectedStrategy.name}</h1>
            </div>
          </div>
          {canWriteStrategy && (
            <button
              type="button"
              onClick={() => handleEditStrategy(selectedStrategy)}
              className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-blue-700"
            >
              <Edit3 className="h-4 w-4" />
              编辑策略
            </button>
          )}
        </div>

        <section className="rounded-xl border border-crypto-border bg-crypto-card/80">
          <button
            type="button"
            aria-expanded={logicSummaryOpen}
            onClick={() => setLogicSummaryOpen((value) => !value)}
            className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left transition-colors hover:bg-white/[0.03]"
          >
            <span className="flex min-w-0 items-center gap-2">
              <BookOpen className="h-4 w-4 shrink-0 text-blue-400" />
              <h2 className="truncate text-base font-semibold text-white">核心标的与交易逻辑</h2>
            </span>
            <ChevronDown
              className={clsx('h-4 w-4 shrink-0 text-gray-500 transition-transform', logicSummaryOpen && 'rotate-180 text-gray-300')}
            />
          </button>
          {logicSummaryOpen && (
            <div className="grid gap-5 border-t border-crypto-border px-4 py-4 lg:grid-cols-2">
              <div className="border-l border-blue-500/40 pl-4">
                <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-blue-300">
                  <Layers className="h-4 w-4" />
                  核心标的
                </div>
                <p className="text-sm leading-6 text-gray-300">{logic.selectionLogic}</p>
              </div>
              <div className="border-l border-emerald-500/40 pl-4">
                <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-emerald-300">
                  <BarChart3 className="h-4 w-4" />
                  交易逻辑
                </div>
                <p className="text-sm leading-6 text-gray-300">{logic.tradingLogic}</p>
              </div>
            </div>
          )}
        </section>

        <StrategyParameterSections sections={parameterSections} />

        <section className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
          <div className="rounded-xl border border-crypto-border bg-crypto-card p-5">
            <h2 className="mb-3 text-sm font-semibold text-white">策略描述</h2>
            <p className="text-sm leading-6 text-gray-400">
              {selectedStrategy.description || '暂无描述'}
            </p>
          </div>
          <div className="rounded-xl border border-crypto-border bg-crypto-card p-5">
            <h2 className="mb-3 text-sm font-semibold text-white">交易范围</h2>
            {displaySymbols.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {displaySymbols.map((symbol) => (
                  <span
                    key={symbol}
                    className="rounded-md border border-crypto-border bg-crypto-bg px-2 py-1 text-xs text-gray-300"
                  >
                    {symbol}
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-500">暂无交易范围</p>
            )}
          </div>
        </section>
      </div>
    );
  };

  // ============================================
  // 渲染：策略编辑器
  // ============================================
  const renderEditorView = () => (
    <div className="h-full flex flex-col">
      {/* 编辑器顶部工具栏 */}
      <div className="flex items-center justify-between px-2 py-3 border-b border-crypto-border shrink-0">
        <div className="flex items-center gap-3">
          <button onClick={() => setView('list')}
            className="flex items-center gap-1 text-gray-400 hover:text-white text-sm transition-colors">
            <ArrowLeft className="w-4 h-4" />返回
          </button>
          <div className="w-px h-5 bg-crypto-border" />
          <FileCode className="w-4 h-4 text-blue-400" />
          <span className="text-sm font-medium text-white">{editMode === 'edit' ? '编辑策略' : '新建策略'}</span>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => { navigator.clipboard.writeText(formData.scriptContent); setMessage({ type: 'success', text: '代码已复制' }); }}
            className="flex items-center gap-1 px-3 py-1.5 text-xs text-gray-400 hover:text-white bg-crypto-bg rounded-lg transition-colors">
            <Copy className="w-3 h-3" />复制
          </button>
          <button onClick={handleSave} disabled={saving}
            className="flex items-center gap-1.5 px-5 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50">
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>

      {/* 编辑器主体 */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-4 gap-0 min-h-0 overflow-hidden">
        {/* 左侧：配置面板 */}
        <div className="lg:col-span-1 border-r border-crypto-border overflow-y-auto p-4 space-y-4 bg-crypto-card/50">
          <div>
            <label className="block text-xs text-gray-400 mb-1.5">策略名称 <span className="text-red-400">*</span></label>
            <input type="text" value={formData.name} onChange={e => setFormData({ ...formData, name: e.target.value })}
              placeholder="输入策略名称"
              className="w-full bg-crypto-bg border border-crypto-border rounded-lg px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1.5">策略描述</label>
            <textarea value={formData.description} onChange={e => setFormData({ ...formData, description: e.target.value })}
              placeholder="简要描述策略逻辑..." rows={3}
              className="w-full bg-crypto-bg border border-crypto-border rounded-lg px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none resize-none" />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1.5">市场</label>
            <CryptoSelect value={formData.exchange} onChange={e => setFormData({ ...formData, exchange: e.target.value })}>
              <option value="CN">A 股</option>
            </CryptoSelect>
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1.5">A 股标的（逗号分隔）</label>
            <input type="text" value={formData.symbols} onChange={e => setFormData({ ...formData, symbols: e.target.value })}
              placeholder="600519.SH, 000001.SZ"
              className="w-full bg-crypto-bg border border-crypto-border rounded-lg px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1.5">策略参数 (JSON)</label>
            <textarea value={formData.config} onChange={e => setFormData({ ...formData, config: e.target.value })}
              rows={6}
              className="w-full bg-crypto-bg border border-crypto-border rounded-lg px-3 py-2 text-sm text-white font-mono focus:border-blue-500 focus:outline-none resize-none" />
          </div>

          {/* API 提示 */}
          <div className="p-3 bg-blue-500/10 border border-blue-500/20 rounded-lg">
            <div className="text-[10px] text-blue-400 font-semibold mb-1.5">可用 API</div>
            <div className="text-[10px] text-gray-400 space-y-1 font-mono">
              <div><span className="text-blue-400">history</span>(symbol, count, "1d", field)</div>
              <div><span className="text-blue-400">get_current_data</span>()</div>
              <div><span className="text-green-400">order_target_percent</span>(symbol, weight)</div>
              <div><span className="text-yellow-400">record</span>(metric=value)</div>
              <div><span className="text-gray-500">set_benchmark</span> · <span className="text-gray-500">set_order_cost</span></div>
            </div>
          </div>
        </div>

        {/* 右侧：代码编辑器 */}
        <div className="lg:col-span-3 flex flex-col min-h-0">
          <div className="flex items-center justify-between px-4 py-2 bg-gray-900/50 border-b border-crypto-border shrink-0">
            <div className="flex items-center gap-2 text-xs text-gray-500">
              <FileCode className="w-3.5 h-3.5" />
              <span>strategy.py</span>
            </div>
            <span className="text-[10px] text-gray-600">Python</span>
          </div>
          <textarea
            value={formData.scriptContent}
            onChange={e => setFormData({ ...formData, scriptContent: e.target.value })}
            className="flex-1 w-full bg-gray-950 text-gray-300 font-mono text-sm leading-relaxed px-4 py-3 focus:outline-none resize-none"
            spellCheck={false}
            style={{ tabSize: 4 }}
          />
        </div>
      </div>
    </div>
  );

  // ============================================
  // 主渲染
  // ============================================
  return (
    <div className={clsx('h-full flex flex-col', view === 'editor' ? '' : 'p-6')}>
      {/* 消息提示 */}
      {message && (
        <div className={clsx('fixed top-4 right-4 z-50 px-4 py-3 rounded-xl flex items-center gap-2 shadow-lg',
          message.type === 'success' ? 'bg-green-500/20 text-green-400 border border-green-500/30' : 'bg-red-500/20 text-red-400 border border-red-500/30'
        )}>
          {message.type === 'success' ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
          <span className="text-sm">{message.text}</span>
          <button onClick={() => setMessage(null)} className="ml-2"><X className="w-3.5 h-3.5" /></button>
        </div>
      )}

      {view === 'list' && renderListView()}
      {view === 'editor' && renderEditorView()}
      {view === 'detail' && renderDetailView()}

      <ThemeDialog
        open={deleteBlockedOpen}
        variant="alert"
        title="无法归档"
        content="该策略正在运行或已暂停。请前往「模拟」页面暂停策略后再归档。"
        tone="warning"
        confirmText="我知道了"
        onClose={() => setDeleteBlockedOpen(false)}
      />

      <ThemeDialog
        open={deleteTarget !== null}
        variant="confirm"
        title="归档策略"
        content={
          deleteTarget
            ? `确定要归档策略「${deleteTarget.name}」吗？历史版本和验证记录会继续保留。`
            : ''
        }
        tone="danger"
        confirmText="归档"
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => void runDeleteStrategy()}
      />

      {/* 启动策略请前往「模拟」模块 */}
    </div>
  );
}
