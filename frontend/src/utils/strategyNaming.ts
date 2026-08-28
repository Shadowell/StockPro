const CANONICAL_PATTERN =
  /^\[(A股|ETF)\]\[(日线|60分|30分|15分|5分)\]\[([^\]]{2,12})\] (\S(?:.*\S)?)$/;

const PREFIX = /^(?:Paper|模拟盘|模拟)\s*[-·/]?\s*/i;
const SUFFIX = /(?:\s*[-·/]\s*(?:Paper|模拟盘|封存回放模拟盘|100万|1,?000,?000(?:CNY)?))+$/i;
const SPRINT = /^Sprint\s*\d+\s+/i;
const DATE = /\s+\d{4}-\d{2}-\d{2}\b/;
const TRAILING_PUNCT = /[。．.]+$/;
const FORBIDDEN = /paper|sprint|e2e_|test probe|minimal research|research chain|验收|100万|模拟盘/i;

const ALIASES: Record<string, string> = {
  'StockPro minimal research chain': '[A股][日线][动量] 最小研究链',
  全链路交易日: '[A股][日线][事件] 交易日全链路',
  参与率拒单: '[A股][日线][事件] 参与率拒单',
  五日回放: '[A股][日线][事件] 五日回放',
  多因子风险预算: '[A股][日线][多因子] 风险预算',
  A股多股动量模板: '[A股][日线][动量] 多股模板',
  'MA5 Reference': '[A股][日线][趋势] MA5参考',
};

export const STRATEGY_NAME_EXAMPLE = '[A股][日线][打板] 首板放量隔日T';
export const STRATEGY_NAME_RULE = '[市场][周期][风格] 策略简称';
export const STRATEGY_NAME_HINT =
  `命名：${STRATEGY_NAME_RULE}，例如 ${STRATEGY_NAME_EXAMPLE}。不要写 Paper、模拟盘、资金、Sprint、验收或日期。`;

function collapse(value: string): string {
  return String(value || '').trim().replace(/\s+/g, ' ');
}

function aliasLookup(text: string): string | undefined {
  if (ALIASES[text]) return ALIASES[text];
  const withoutAcceptance = text.replace(/验收$/, '').trim();
  if (withoutAcceptance !== text && ALIASES[withoutAcceptance]) {
    return ALIASES[withoutAcceptance];
  }
  return undefined;
}

export function normalizeStrategyName(raw: string): string {
  let text = collapse(raw);
  if (!text) return '';
  let previous = '';
  while (text !== previous) {
    previous = text;
    text = text.replace(PREFIX, '').replace(SUFFIX, '').replace(DATE, '').replace(TRAILING_PUNCT, '');
    text = collapse(text);
  }
  const aliased = aliasLookup(text);
  if (aliased) return aliased;
  const unsprinted = collapse(text.replace(SPRINT, ''));
  if (unsprinted && unsprinted !== text) {
    const mapped = aliasLookup(unsprinted);
    if (mapped) return mapped;
    if (isValidStrategyName(unsprinted)) return unsprinted;
  }
  return text;
}

export function isValidStrategyName(name: string): boolean {
  const match = CANONICAL_PATTERN.exec(name);
  if (!match) return false;
  if (FORBIDDEN.test(name) || DATE.test(` ${name}`)) return false;
  return match[4].length <= 40;
}

export function formatStrategyDisplayName(raw: string, fallback = ''): string {
  const cleaned = normalizeStrategyName(raw);
  if (isValidStrategyName(cleaned)) return cleaned;
  return cleaned || fallback || collapse(raw);
}

export function strategyNameError(raw: string): string | null {
  const cleaned = normalizeStrategyName(raw);
  if (!cleaned) return '请输入策略名称';
  if (!isValidStrategyName(cleaned)) return STRATEGY_NAME_HINT;
  return null;
}
