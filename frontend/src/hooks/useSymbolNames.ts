import { useEffect, useMemo, useState } from 'react';
import { lookupSymbolNames } from '../api/client';
import { normalizeSymbolCode } from '../utils/symbolDisplay';

/** Batch-resolve Chinese names for numbered A-share symbols. */
export function useSymbolNames(symbols: Array<string | null | undefined>) {
  const key = useMemo(() => {
    const normalized = Array.from(
      new Set(
        symbols
          .map((item) => normalizeSymbolCode(item))
          .filter(Boolean),
      ),
    ).sort();
    return normalized.join(',');
  }, [symbols]);

  const [names, setNames] = useState<Record<string, string>>({});

  useEffect(() => {
    let active = true;
    const list = key ? key.split(',') : [];
    if (!list.length) {
      setNames({});
      return () => {
        active = false;
      };
    }
    void lookupSymbolNames(list)
      .then((resolved) => {
        if (active) setNames(resolved);
      })
      .catch(() => {
        if (active) setNames({});
      });
    return () => {
      active = false;
    };
  }, [key]);

  return names;
}
