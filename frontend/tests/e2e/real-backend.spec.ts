import { APIRequestContext, expect, test } from '@playwright/test';

const runRealBackendSuite =
  process.env.MOCK_API === 'false' || process.env.E2E_REAL_BACKEND === '1';

test.skip(
  !runRealBackendSuite,
  'This suite requires real backend mode. Set MOCK_API=false.'
);

test.describe.configure({ mode: 'serial' });

async function login(request: APIRequestContext) {
  const adminPassword = process.env.E2E_ADMIN_PASSWORD || process.env.ADMIN_PASSWORD;
  test.skip(!adminPassword, 'Set E2E_ADMIN_PASSWORD or ADMIN_PASSWORD to test protected APIs.');

  const loginResp = await request.post('/api/auth/admin/login', {
    data: {
      username: process.env.E2E_ADMIN_USERNAME || process.env.ADMIN_USERNAME || 'admin',
      password: adminPassword,
    },
  });
  expect(loginResp.ok()).toBeTruthy();

  const loginData = (await loginResp.json()) as { access_token?: unknown };
  expect(typeof loginData.access_token).toBe('string');
  return String(loginData.access_token);
}

test('公共健康接口可访问', async ({ request }) => {
  const resp = await request.get('/api/health/health');
  expect(resp.ok()).toBeTruthy();

  const data = (await resp.json()) as { status?: unknown };
  expect(typeof data).toBe('object');
  expect(['healthy', 'success', 'warning']).toContain(String(data.status ?? ''));
});

test('业务接口未登录返回 401', async ({ request }) => {
  const resp = await request.get('/api/market/overview');
  expect(resp.status()).toBe(401);
});

test('登录后市场和数据库接口可访问', async ({ request }) => {
  const token = await login(request);
  const headers = { Authorization: `Bearer ${token}` };

  const marketResp = await request.get('/api/market/overview', { headers });
  expect(marketResp.ok()).toBeTruthy();
  const marketData = (await marketResp.json()) as { indices?: unknown; sentiment?: unknown; volume?: unknown };
  expect(Array.isArray(marketData.indices)).toBeTruthy();
  expect(typeof marketData.sentiment).toBe('object');
  expect(typeof marketData.volume).toBe('object');

  const queryResp = await request.post('/api/database/query', {
    headers,
    data: {
      query: "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name LIMIT 5",
    },
  });
  expect(queryResp.ok()).toBeTruthy();
  const queryData = (await queryResp.json()) as { columns?: unknown; rows?: unknown; rowCount?: unknown };
  expect(Array.isArray(queryData.columns)).toBeTruthy();
  expect(Array.isArray(queryData.rows)).toBeTruthy();
  expect(typeof queryData.rowCount).toBe('number');

  const rejectResp = await request.post('/api/database/query', {
    headers,
    data: { query: 'DELETE FROM stock_history' },
  });
  expect(rejectResp.status()).toBe(400);
});

test('DataDev 任务 CRUD + 运行 + 日志可用', async ({ request }) => {
  const token = await login(request);
  const headers = { Authorization: `Bearer ${token}` };
  const taskName = `e2e_datadev_${Date.now()}`;

  const createResp = await request.post('/api/data-dev/tasks', {
    headers,
    data: {
      name: taskName,
      description: 'created by playwright real-backend test',
      sql_content: 'CREATE TABLE IF NOT EXISTS e2e_temp_table (id INTEGER PRIMARY KEY)',
      cron_expression: '0 19 * * *',
      enabled: false,
    },
  });

  expect(createResp.ok()).toBeTruthy();
  const createData = (await createResp.json()) as { id?: unknown };
  const taskId = Number(createData.id);
  expect(Number.isInteger(taskId)).toBeTruthy();
  expect(taskId > 0).toBeTruthy();

  try {
    const listResp = await request.get('/api/data-dev/tasks', { headers });
    expect(listResp.ok()).toBeTruthy();
    const tasks = (await listResp.json()) as Array<{ id?: unknown; name?: unknown }>;
    expect(tasks.some((item) => Number(item.id) === taskId)).toBeTruthy();

    const updateResp = await request.put(`/api/data-dev/tasks/${taskId}`, {
      headers,
      data: {
        name: taskName,
        description: 'updated by playwright',
        sql_content: 'CREATE TABLE IF NOT EXISTS e2e_temp_table (id INTEGER PRIMARY KEY)',
        cron_expression: '0 19 * * *',
        enabled: false,
      },
    });
    expect(updateResp.ok()).toBeTruthy();

    const runResp = await request.post(`/api/data-dev/tasks/${taskId}/run`, { headers });
    expect(runResp.ok()).toBeTruthy();

    const logsResp = await request.get(`/api/data-dev/tasks/${taskId}/logs?limit=10`, { headers });
    expect(logsResp.ok()).toBeTruthy();
    const logs = (await logsResp.json()) as Array<{ status?: unknown }>;
    expect(logs.some((log) => ['success', 'failed', 'running'].includes(String(log.status ?? '')))).toBeTruthy();
  } finally {
    const deleteResp = await request.delete(`/api/data-dev/tasks/${taskId}`, { headers });
    expect(deleteResp.ok()).toBeTruthy();
  }
});

test('真实 Strategy API v1 可保存普通 Python 并从封存快照快速回放', async ({ request }) => {
  const token = await login(request);
  const headers = { Authorization: `Bearer ${token}` };

  const snapshotsResp = await request.get('/api/data/snapshots?limit=50', { headers });
  expect(snapshotsResp.ok()).toBeTruthy();
  const snapshots = ((await snapshotsResp.json()) as { items?: Array<{ id?: unknown; status?: unknown }> }).items ?? [];
  const sealedSnapshots = snapshots.filter((item) => item.status === 'sealed' && Number(item.id) > 0);
  expect(sealedSnapshots.length).toBeGreaterThan(0);

  let datasetSnapshotId = 0;
  let symbol = '';
  let startDate = '';
  let endDate = '';
  for (const snapshot of sealedSnapshots) {
    const candidateId = Number(snapshot.id);
    const barsResp = await request.get(`/api/data/snapshots/${candidateId}/daily-bars?limit=200`, { headers });
    if (!barsResp.ok()) continue;
    const bars = ((await barsResp.json()) as { items?: Array<{ symbol?: unknown; trade_date?: unknown }> }).items ?? [];
    if (bars.length < 2) continue;
    const candidateSymbol = String(bars[0].symbol ?? '');
    const symbolRows = bars.filter((item) => String(item.symbol ?? '') === candidateSymbol);
    if (symbolRows.length < 2) continue;
    const dates = symbolRows.map((item) => String(item.trade_date ?? '').slice(0, 10)).sort();
    datasetSnapshotId = candidateId;
    symbol = candidateSymbol;
    startDate = dates[0];
    endDate = dates[dates.length - 1];
    break;
  }
  expect(datasetSnapshotId).toBeGreaterThan(0);
  expect(symbol).not.toBe('');

  const strategyResp = await request.post('/api/strategy', {
    headers,
    data: {
      name: `e2e_strategy_v1_${Date.now()}`,
      description: 'Playwright real-backend lifecycle contract',
      script_content: `def initialize(context):
    set_option("avoid_future_data", True)

def handle_data(context, data):
    for security in context.universe:
        order_target_percent(security, 0.1)
        record(security=security, target=0.1)
`,
    },
  });
  expect(strategyResp.ok()).toBeTruthy();
  const strategyData = (await strategyResp.json()) as {
    strategy_version?: { id?: unknown; strategy_api_version?: unknown; validation_status?: unknown };
    validation?: { valid?: unknown };
  };
  expect(strategyData.validation?.valid).toBe(true);
  expect(strategyData.strategy_version?.strategy_api_version).toBe('stockpro.v1');
  expect(strategyData.strategy_version?.validation_status).toBe('valid');
  const versionId = String(strategyData.strategy_version?.id ?? '');
  expect(versionId).not.toBe('');

  const replayResp = await request.post(`/api/strategy/versions/${versionId}/quick-run`, {
    headers,
    data: { dataset_snapshot_id: datasetSnapshotId, start_date: startDate, end_date: endDate, symbols: [symbol] },
  });
  expect(replayResp.ok()).toBeTruthy();
  const replay = (await replayResp.json()) as {
    run_id?: unknown; status?: unknown; event_count?: unknown; intent_count?: unknown; record_count?: unknown;
  };
  expect(replay.status).toBe('success');
  expect(Number(replay.event_count)).toBeGreaterThan(0);
  expect(Number(replay.intent_count)).toBeGreaterThan(0);
  expect(Number(replay.record_count)).toBeGreaterThan(0);

  const intentsResp = await request.get(`/api/strategy/replays/${String(replay.run_id)}/intents`, { headers });
  expect(intentsResp.ok()).toBeTruthy();
  const intents = ((await intentsResp.json()) as { items?: Array<{ simulated_at?: unknown; available_at?: unknown }> }).items ?? [];
  expect(intents.length).toBe(Number(replay.intent_count));
  expect(intents.every((item) => item.simulated_at && item.available_at)).toBeTruthy();
});

test('真实策略页面展示生命周期编辑器且无浏览器错误', async ({ page }) => {
  const token = await login(page.request);
  await page.addInitScript((value) => window.localStorage.setItem('stockpro_admin_token', value), token);
  const pageErrors: string[] = [];
  const consoleErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });

  await page.goto('/strategy', { waitUntil: 'networkidle' });
  await expect(page.getByRole('heading', { name: '策略中心' })).toBeVisible();
  await expect(page.getByText('A股标准策略示例')).toBeVisible();
  await expect(page.getByText(/不需要修改框架、路由或重启服务/)).toHaveCount(0);
  await page.getByRole('button', { name: '新建策略' }).click();
  await expect(page.getByRole('heading', { name: 'Python 生命周期策略' })).toBeVisible();
  await expect(page.locator('textarea')).toContainText('def initialize(context):');
  await expect(page.locator('textarea')).not.toContainText('backtrader');
  await expect(page.getByText('等待验证或存在问题')).toHaveCount(0);
  expect(pageErrors, pageErrors.join('\n')).toEqual([]);
  expect(consoleErrors, consoleErrors.join('\n')).toEqual([]);
});

test('真实完整回测展示八类证据且收盘信号不会同日成交', async ({ page }) => {
  const token = await login(page.request);
  const headers = { Authorization: `Bearer ${token}` };
  const runsResp = await page.request.get('/api/backtest/runs?limit=100', { headers });
  expect(runsResp.ok()).toBeTruthy();
  const runs = ((await runsResp.json()) as { items?: Array<{ id?: unknown; status?: unknown; run_mode?: unknown }> }).items ?? [];
  const run = runs.find((item) => item.status === 'success' && item.run_mode === 'full');
  test.skip(!run, '本地 PG 尚无成功的完整回测');
  const runId = String(run?.id ?? '');

  const metricsResp = await page.request.get(`/api/backtest/runs/${runId}/metrics`, { headers });
  const ordersResp = await page.request.get(`/api/backtest/runs/${runId}/orders`, { headers });
  expect(metricsResp.ok()).toBeTruthy();
  expect(ordersResp.ok()).toBeTruthy();
  const metrics = ((await metricsResp.json()) as { items?: unknown[] }).items ?? [];
  const orders = ((await ordersResp.json()) as { items?: Array<{ signal_at?: unknown; filled_at?: unknown }> }).items ?? [];
  expect(metrics.length).toBeGreaterThanOrEqual(41);
  expect(orders.filter((item) => item.filled_at).every((item) => String(item.filled_at).slice(0, 10) > String(item.signal_at).slice(0, 10))).toBeTruthy();

  await page.addInitScript((value) => window.localStorage.setItem('stockpro_admin_token', value), token);
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.goto(`/backtest/${runId}`, { waitUntil: 'networkidle' });
  for (const tab of ['总览', '收益分析', '持仓', '交易', '订单', '日志', '代码与参数', '归因']) {
    await expect(page.getByRole('tab', { name: tab })).toBeVisible();
  }
  await expect(page.getByText('可复现实验凭证')).toBeVisible();
  expect(pageErrors, pageErrors.join('\n')).toEqual([]);
});

test('真实市场研究与股票池快照形成 PG 研究闭环', async ({ page }) => {
  const token = await login(page.request);
  const headers = { Authorization: `Bearer ${token}` };
  const [contextResp, poolsResp, snapshotsResp, configurationResp] = await Promise.all([
    page.request.get('/api/market/research-context', { headers }),
    page.request.get('/api/pools', { headers }),
    page.request.get('/api/pool-snapshots', { headers }),
    page.request.get('/api/backtest/configuration', { headers }),
  ]);
  for (const response of [contextResp, poolsResp, snapshotsResp, configurationResp]) expect(response.ok()).toBeTruthy();
  const context = (await contextResp.json()) as { snapshot?: { id?: unknown }; limit_ecosystem?: { ladder?: unknown[] }; sector_evidence?: { items?: unknown[] } };
  const pools = ((await poolsResp.json()) as { items?: unknown[] }).items ?? [];
  const snapshots = ((await snapshotsResp.json()) as { items?: Array<{ id?: unknown; manifest_hash?: unknown; member_count?: unknown }> }).items ?? [];
  const configuration = (await configurationResp.json()) as { pool_snapshots?: unknown[] };
  expect(Number(context.snapshot?.id)).toBeGreaterThan(0);
  expect(context.limit_ecosystem?.ladder).toHaveLength(5);
  expect((context.sector_evidence?.items ?? []).length).toBeGreaterThan(0);
  expect(pools.length).toBeGreaterThanOrEqual(3);
  expect(snapshots.length).toBeGreaterThanOrEqual(3);
  expect(snapshots.every((item) => Number(item.member_count) > 0 && typeof item.manifest_hash === 'string')).toBeTruthy();
  expect((configuration.pool_snapshots ?? []).length).toBeGreaterThanOrEqual(snapshots.length);

  await page.addInitScript((value) => window.localStorage.setItem('stockpro_admin_token', value), token);
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.goto('/market?tab=sentiment', { waitUntil: 'networkidle' });
  await expect(page.getByRole('heading', { name: '市场研究工作台' })).toBeVisible();
  await expect(page.getByText('连板天梯')).toBeVisible();
  await page.goto('/pools?tab=snapshots', { waitUntil: 'networkidle' });
  await expect(page.getByRole('heading', { name: '股票池研究工作台' })).toBeVisible();
  await expect(page.getByTestId('pool-snapshot-table')).toBeVisible();
  expect(pageErrors, pageErrors.join('\n')).toEqual([]);
});

test('真实 Paper 五日链路在执行观察监控三页共享审计对象', async ({ page }) => {
  const token = await login(page.request);
  const headers = { Authorization: `Bearer ${token}` };
  const instancesResp = await page.request.get('/api/paper/instances', { headers });
  expect(instancesResp.ok()).toBeTruthy();
  const instances = ((await instancesResp.json()) as { items?: Array<{ id?: unknown; name?: unknown; trade_count?: unknown }> }).items ?? [];
  expect(instances.length).toBeGreaterThan(0);
  const accepted = instances.find((item) => String(item.name).includes('五日回放') && Number(item.trade_count) > 0) ?? instances.find((item) => Number(item.trade_count) > 0);
  test.skip(!accepted, '本地 PG 尚无包含成交的 Paper 验收实例');
  const instanceId = String(accepted?.id ?? '');
  const [detailResp, eventsResp, watchResp, healthResp] = await Promise.all([
    page.request.get(`/api/paper/instances/${instanceId}`, { headers }),
    page.request.get(`/api/paper/instances/${instanceId}/events`, { headers }),
    page.request.get('/api/watch/context', { headers }),
    page.request.get('/api/monitor/health', { headers }),
  ]);
  for (const response of [detailResp, eventsResp, watchResp, healthResp]) expect(response.ok()).toBeTruthy();
  const detail = (await detailResp.json()) as {
    cycles?: Array<{ status?: unknown; ledger_difference?: unknown }>;
    orders?: Array<{ signal_id?: unknown; risk_event_id?: unknown; signal_time?: unknown; filled_at?: unknown }>;
    events?: unknown[];
  };
  expect((detail.cycles ?? []).length).toBeGreaterThanOrEqual(2);
  expect((detail.cycles ?? []).every((item) => Number(item.ledger_difference ?? 0) === 0)).toBeTruthy();
  const filled = (detail.orders ?? []).find((item) => item.filled_at);
  expect(filled?.signal_id).toBeTruthy();
  expect(filled?.risk_event_id).toBeTruthy();
  expect(String(filled?.filled_at).slice(0, 10) > String(filled?.signal_time).slice(0, 10)).toBeTruthy();
  const watch = (await watchResp.json()) as { alerts?: Array<{ paper_instance_id?: unknown }>; instances?: Array<{ id?: unknown }> };
  expect((watch.instances ?? []).some((item) => String(item.id) === instanceId)).toBeTruthy();
  expect((watch.alerts ?? []).some((item) => String(item.paper_instance_id) === instanceId)).toBeTruthy();
  const health = (await healthResp.json()) as { status?: unknown; strategy_instances?: unknown[]; services?: unknown[] };
  expect(['healthy', 'warning', 'critical']).toContain(String(health.status));
  expect(Array.isArray(health.strategy_instances)).toBeTruthy();

  await page.addInitScript((value) => window.localStorage.setItem('stockpro_admin_token', value), token);
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.goto(`/paper?tab=orders&instance=${instanceId}`, { waitUntil: 'networkidle' });
  await expect(page.getByTestId('paper-runtime-workbench')).toBeVisible();
  await expect(page.getByText(instanceId).first()).toBeVisible();
  await page.goto('/watch?tab=alerts', { waitUntil: 'networkidle' });
  await expect(page.getByTestId('watch-workbench')).toBeVisible();
  await page.goto('/monitor?tab=risk', { waitUntil: 'networkidle' });
  await expect(page.getByTestId('monitor-workbench')).toBeVisible();
  expect(pageErrors, pageErrors.join('\n')).toEqual([]);
});

test('真实交易日从市场研究贯穿到封存复盘且所有引用可解析', async ({ page }) => {
  const token = await login(page.request);
  const headers = { Authorization: `Bearer ${token}` };
  const reviewResp = await page.request.get('/api/review/2025-01-02', { headers });
  expect(reviewResp.ok()).toBeTruthy();
  const review = (await reviewResp.json()) as {
    status?: unknown;
    source_manifest_hash?: unknown;
    counts?: Record<string, number>;
    items?: Array<{
      category?: unknown;
      source_object_type?: unknown;
      source_object_id?: unknown;
      resolution_status?: unknown;
    }>;
  };
  expect(review.status).toBe('sealed');
  expect(String(review.source_manifest_hash ?? '')).toMatch(/^[a-f0-9]{64}$/);
  const requiredCategories = ['market', 'pool', 'strategy', 'risk', 'order', 'trade', 'performance'];
  for (const category of requiredCategories) {
    expect(Number(review.counts?.[category] ?? 0), `${category} should be present`).toBeGreaterThan(0);
  }
  expect((review.items ?? []).length).toBeGreaterThanOrEqual(7);
  for (const item of review.items ?? []) {
    expect(item.resolution_status).toBe('resolved');
    const type = encodeURIComponent(String(item.source_object_type ?? ''));
    const id = encodeURIComponent(String(item.source_object_id ?? ''));
    const resolvedResp = await page.request.get(`/api/review/objects/${type}/${id}`, { headers });
    expect(resolvedResp.ok(), `${type}:${id} should resolve`).toBeTruthy();
    const resolved = (await resolvedResp.json()) as { status?: unknown; object?: unknown };
    expect(resolved.status).toBe('resolved');
    expect(resolved.object).toBeTruthy();
  }

  await page.addInitScript((value) => window.localStorage.setItem('stockpro_admin_token', value), token);
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.goto('/review?date=2025-01-02&tab=logs', { waitUntil: 'networkidle' });
  await expect(page.getByTestId('daily-review-workbench')).toBeVisible();
  for (const label of ['市场复盘', '股票池复盘', '策略复盘', '交易复盘', '日志']) {
    await expect(page.getByRole('button', { name: label, exact: true })).toBeVisible();
  }
  await expect(page.getByRole('heading', { name: '交易日证据时间线' })).toBeVisible();
  await expect(page.getByText('复盘已封存，不可修改')).toBeVisible();
  await expect(page.getByText(String(review.source_manifest_hash))).toBeVisible();

  const firstLevelLinks = page.getByRole('complementary').locator('nav a');
  await expect(firstLevelLinks).toHaveCount(12);
  expect(pageErrors, pageErrors.join('\n')).toEqual([]);
});

test('首页未登录进入登录页', async ({ page }) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (err) => pageErrors.push(err.message));

  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page).toHaveURL(/\/admin-login/);
  expect(pageErrors, pageErrors.join('\n')).toEqual([]);
});
