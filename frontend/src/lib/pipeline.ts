export const PIPELINE_STRATEGY_NAME = '多因子风险预算';

export const PIPELINE_FACTOR_CODES = [
  'momentum_20d',
  'reversal_3d',
  'volatility_20d',
  'amihud_5d',
] as const;

export const PIPELINE_STAGE_ROLE: Record<string, string> = {
  data: '封存研究数据与行情覆盖，给因子计算和回测提供不可变输入。',
  market: '读封存市场证据，确认交易日、涨停生态和板块结构后再选股。',
  factors: '计算并评价动量 / 短反转 / 低波 / Amihud，再交给股票池截取。',
  pools: '把因子截面收成可复现宇宙，供回测和模拟锁定同一批标的。',
  strategy: '维护同一条 A股多因子策略：周度再平衡 + 日度熔断。',
  backtest: '用封存快照回放固定策略版本，产出可晋级的回测证据。',
  paper: '只跑已晋级版本，记录模拟委托与成交，不碰真实资金。',
  watch: '观察同一实例的信号、委托、成交和待确认风险。',
  monitor: '看实例心跳、回撤、数据健康和风险通知。',
  review: '收盘后汇总市场、持仓、成交与结论，写下一日计划。',
  'ai-lab': 'AI 只辅助写假设和代码，结果必须先过回测与模拟准入。',
};
