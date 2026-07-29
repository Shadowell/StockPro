const STATUS_LABELS: Record<string, string> = {
  acknowledged: '已确认',
  active: '待处理',
  available: '可用',
  blocked: '已阻止',
  cancelled: '已取消',
  cancelling: '取消中',
  critical: '严重',
  draft: '草稿',
  empty: '暂无数据',
  failed: '失败',
  filled: '已成交',
  fresh: '最新',
  healthy: '正常',
  info: '提示',
  interrupted: '已中断',
  missing: '缺少数据',
  new: '待执行',
  ordered: '已下单',
  closed: '已闭环',
  invalidated: '已作废',
  paused: '已暂停',
  pending: '等待中',
  published: '已发布',
  rejected: '已拒绝',
  resolved: '已解决',
  running: '运行中',
  sealed: '已封存',
  stale: '数据滞后',
  starting: '启动中',
  stopped: '已停止',
  stopping: '停止中',
  success: '成功',
  unavailable: '暂不可用',
  unknown: '状态未知',
  warning: '警告',
};

const SOURCE_LABELS: Record<string, string> = {
  akshare: '备用行情源',
  eastmoney: '东方财富行情',
  market_breadth: '市场宽度',
  postgres: '本地数据库',
  postgresql: '本地数据库',
  'postgresql paper audit evidence': '本地模拟盘审计证据',
  tushare_daily: '日线行情',
  tushare_kpl_list: '开盘啦热度榜',
  tushare_limit_industry: '涨停行业分类',
  tushare_limit_list_d: '涨跌停行情',
  tushare_limit_list_derived: '涨跌停衍生指标',
};

const SOURCE_KIND_LABELS: Record<string, string> = {
  broken: '炸板',
  down: '跌停',
  kpl_list: '热度榜',
  market_breadth: '市场宽度',
  up: '涨停',
};

const CATEGORY_LABELS: Record<string, string> = {
  data: '数据',
  market: '市场',
  order: '订单',
  performance: '账户表现',
  pool: '股票池',
  position: '持仓',
  risk: '风险',
  signal: '信号',
  strategy: '策略',
  system: '系统',
  trade: '成交',
};

const SNAPSHOT_TYPE_LABELS: Record<string, string> = {
  intraday: '盘中',
  post_close: '盘后',
  pre_open: '盘前',
};

const SIDE_LABELS: Record<string, string> = {
  buy: '买入',
  sell: '卖出',
};

const ORDER_TYPE_LABELS: Record<string, string> = {
  limit: '限价',
  market: '市价',
};

const normalize = (value: unknown) => String(value ?? '').trim().toLowerCase();

export function statusLabel(value: unknown, fallback = '状态未知') {
  const key = normalize(value);
  return key ? STATUS_LABELS[key] ?? fallback : fallback;
}

export function sourceLabel(value: unknown, fallback = '数据源已记录') {
  const key = normalize(value);
  return key ? SOURCE_LABELS[key] ?? fallback : fallback;
}

export function sourceKindLabel(value: unknown) {
  const key = normalize(value);
  return SOURCE_KIND_LABELS[key] ?? '数据项';
}

export function categoryLabel(value: unknown) {
  const key = normalize(value);
  return CATEGORY_LABELS[key] ?? '其他';
}

export function snapshotTypeLabel(value: unknown) {
  const key = normalize(value);
  return SNAPSHOT_TYPE_LABELS[key] ?? '未标注';
}

export function sideLabel(value: unknown) {
  const key = normalize(value);
  return SIDE_LABELS[key] ?? '未标注';
}

export function sideToneClass(value: unknown) {
  const key = normalize(value);
  if (key === 'buy') return 'text-up';
  if (key === 'sell') return 'text-down';
  return 'text-gray-300';
}

/** Localize Paper signal reason tokens such as order_target_percent=1.0 */
export function signalReasonLabel(value: unknown) {
  const raw = String(value ?? '').trim();
  if (!raw) return '未标注原因';
  const percent = raw.match(/^order_target_percent\s*=\s*([-+]?[0-9]*\.?[0-9]+)$/i);
  if (percent) {
    const ratio = Number(percent[1]);
    if (Number.isFinite(ratio)) {
      const pct = ratio * 100;
      const pretty = Number.isInteger(pct) ? String(pct) : pct.toFixed(1);
      return `目标仓位 ${pretty}%`;
    }
  }
  const target = raw.match(/^order_target\s*=\s*(.+)$/i);
  if (target) return `目标数量 ${target[1].trim()}`;
  const valueMatch = raw.match(/^order_target_value\s*=\s*(.+)$/i);
  if (valueMatch) return `目标金额 ${valueMatch[1].trim()}`;
  const order = raw.match(/^order\s*=\s*(.+)$/i);
  if (order) return `下单数量 ${order[1].trim()}`;
  return raw;
}

export function formatOperatorTime(value: unknown) {
  const raw = String(value ?? '').trim();
  if (!raw) return '--';
  const stamp = new Date(raw);
  if (Number.isNaN(stamp.getTime())) return raw;
  return stamp.toLocaleString('zh-CN', {
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function orderTypeLabel(value: unknown) {
  const key = normalize(value);
  return ORDER_TYPE_LABELS[key] ?? '未标注';
}
