import { useEffect, useMemo, useState } from 'react';
import { lookupSymbolNames } from '../api/client';
import { normalizeSymbolCode } from '../utils/symbolDisplay';

const cache = new Map<string, string>();

export function useSymbolNames(symbols: Array<string | null | undefined>) {
  const normalized = useMemo(() => Array.from(new Set(symbols.map(normalizeSymbolCode).filter(Boolean))).sort(), [symbols]);
  const key = normalized.join(',');
  const [names, setNames] = useState<Record<string, string>>(() => Object.fromEntries(normalized.flatMap((symbol) => cache.has(symbol) ? [[symbol, cache.get(symbol)!]] : [])));

  useEffect(() => {
    let active = true;
    const missing = normalized.filter((symbol) => !cache.has(symbol));
    const publish = () => setNames(Object.fromEntries(normalized.flatMap((symbol) => cache.has(symbol) ? [[symbol, cache.get(symbol)!]] : [])));
    if (!missing.length) {
      publish();
      return () => { active = false; };
    }
    void lookupSymbolNames(missing).then((resolved) => {
      Object.entries(resolved).forEach(([symbol, name]) => {
        if (name) cache.set(normalizeSymbolCode(symbol), name);
      });
      if (active) publish();
    }).catch(() => { if (active) publish(); });
    return () => { active = false; };
  }, [key]);

  return names;
}
