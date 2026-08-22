import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { build } from '../frontend/node_modules/esbuild/lib/main.js';

const ROOT = path.resolve(import.meta.dirname, '..');

async function loadPreferredStrategyModule() {
  const tempDir = await mkdtemp(path.join(os.tmpdir(), 'bitpro-preferred-strategy-'));
  const outfile = path.join(tempDir, 'preferred-strategy.mjs');
  let buildError = null;

  try {
    await build({
      entryPoints: [path.join(ROOT, 'frontend/src/pages/liveTrading/preferredStrategy.ts')],
      outfile,
      bundle: true,
      format: 'esm',
      platform: 'node',
    });
  } catch (error) {
    buildError = error;
  }

  assert.equal(buildError, null, 'preferredStrategy module should be buildable');
  const module = await import(`${path.toNamespacedPath(outfile)}?v=${Date.now()}`);
  return { module, cleanup: () => rm(tempDir, { recursive: true, force: true }) };
}

test('automatic preferred strategy can be dismissed and restored', async () => {
  const { module, cleanup } = await loadPreferredStrategyModule();

  try {
    const automaticIds = new Set(['paper:auto']);
    const dismissedIds = new Set();
    const favoriteIds = new Set(['paper:auto']);

    const dismissed = module.togglePreferredStrategy({
      instanceId: 'paper:auto',
      automaticIds,
      dismissedAutomaticIds: dismissedIds,
      favoriteIds,
    });
    assert.deepEqual([...dismissed.favoriteIds], []);
    assert.deepEqual([...dismissed.dismissedAutomaticIds], ['paper:auto']);

    const restored = module.togglePreferredStrategy({
      instanceId: 'paper:auto',
      automaticIds,
      dismissedAutomaticIds: dismissed.dismissedAutomaticIds,
      favoriteIds: dismissed.favoriteIds,
    });
    assert.deepEqual([...restored.favoriteIds], []);
    assert.deepEqual([...restored.dismissedAutomaticIds], []);
  } finally {
    await cleanup();
  }
});

test('manual preferred strategy still toggles independently', async () => {
  const { module, cleanup } = await loadPreferredStrategyModule();

  try {
    const added = module.togglePreferredStrategy({
      instanceId: 'paper:manual',
      automaticIds: new Set(),
      dismissedAutomaticIds: new Set(),
      favoriteIds: new Set(),
    });
    assert.deepEqual([...added.favoriteIds], ['paper:manual']);
    assert.deepEqual([...added.dismissedAutomaticIds], []);

    const removed = module.togglePreferredStrategy({
      instanceId: 'paper:manual',
      automaticIds: new Set(),
      dismissedAutomaticIds: added.dismissedAutomaticIds,
      favoriteIds: added.favoriteIds,
    });
    assert.deepEqual([...removed.favoriteIds], []);
    assert.deepEqual([...removed.dismissedAutomaticIds], []);
  } finally {
    await cleanup();
  }
});
