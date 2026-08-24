const DOTTED = /^(\d{6})\.(SH|SZ|BJ)$/i
const PREFIXED = /^(SH|SZ|BJ)[_./-]?(\d{6})$/i

export function formatAshareSymbol(symbol: string | null | undefined): string {
  const raw = String(symbol || '').trim()
  if (!raw) return '—'
  const dotted = raw.match(DOTTED)
  if (dotted) return `${dotted[1]}.${dotted[2].toUpperCase()}`
  const prefixed = raw.match(PREFIXED)
  if (prefixed) return `${prefixed[2]}.${prefixed[1].toUpperCase()}`
  return raw
}
