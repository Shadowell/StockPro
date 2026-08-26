import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { pathToFileURL } from 'node:url';

import { build } from '../frontend/node_modules/esbuild/lib/main.js';

const ROOT = path.resolve(import.meta.dirname, '..');

async function loadSymbolSearchModule() {
  const outputDir = await mkdtemp(path.join(tmpdir(), 'bitpro-symbol-search-'));
  const outputFile = path.join(outputDir, 'symbol-search.mjs');

  await build({
    entryPoints: [path.join(ROOT, 'frontend/src/components/SymbolSearch.tsx')],
    outfile: outputFile,
    bundle: true,
    format: 'esm',
    platform: 'node',
  });

  const module = await import(pathToFileURL(outputFile).href);
  return { module, outputDir };
}

test('合约搜索支持不带分隔符的交易所常用写法', async () => {
  const { module, outputDir } = await loadSymbolSearchModule();
  try {
    assert.equal(typeof module.matchesSymbolSearch, 'function');
    assert.equal(module.matchesSymbolSearch('KAITO/USDT:USDT', 'KAITOUSDT'), true);
  } finally {
    await rm(outputDir, { recursive: true, force: true });
  }
});
