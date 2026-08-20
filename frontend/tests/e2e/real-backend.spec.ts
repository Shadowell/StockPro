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

test('真实一级导航突出策略回测模拟并保留补充入口', async ({ page }) => {
  const token = await login(page.request);
  await page.addInitScript((value) => window.localStorage.setItem('stockpro_admin_token', value), token);
  await page.goto('/strategy', { waitUntil: 'domcontentloaded' });

  const firstLevelLinks = page.getByRole('complementary').locator('nav a');
  await expect(firstLevelLinks).toHaveCount(7);
  await expect(firstLevelLinks).toHaveText([
    /首页/,
    /策略/,
    /回测/,
    /模拟/,
    /行情/,
    /盯盘/,
    /数据/,
  ]);
  await expect(page.getByRole('tab', { name: 'AI 研发' })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole('navigation', { name: '主菜单' }).getByRole('link', { name: 'AI研发' })).toHaveCount(0);
  await page.getByRole('tab', { name: '选股与输入' }).click();
  await expect(page.getByTestId('strategy-research-inputs')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole('heading', { name: '基础条件选股' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '不可变股票池' })).toBeVisible();
});

test('真实首页首次就绪检查只读并提供统一复盘入口', async ({ page }) => {
  const token = await login(page.request);
  const response = await page.request.get('/api/workflow/onboarding-readiness', { headers: { Authorization: `Bearer ${token}` } });
  expect(response.ok()).toBeTruthy();
  const readiness = (await response.json()) as { writes_performed?: unknown; required_total?: unknown };
  expect(readiness.writes_performed).toBe(false);
  expect(Number(readiness.required_total)).toBeGreaterThan(0);
  await page.addInitScript((value) => window.localStorage.setItem('stockpro_admin_token', value), token);
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('onboarding-readiness')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole('link', { name: /统一复盘/ })).toHaveAttribute('href', '/review');
});

test('真实股票池筛选器提供版本化 AND OR 条件配置', async ({ page }) => {
  const token = await login(page.request);
  await page.addInitScript((value) => window.localStorage.setItem('stockpro_admin_token', value), token);
  await page.goto('/pools?tab=screener', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: '基础条件', exact: true }).click();

  await expect(page.getByRole('heading', { name: '多条件筛选' })).toBeVisible({ timeout: 30_000 });
  await page.getByRole('button', { name: '添加筛选条件' }).click();
  await expect(page.getByRole('combobox', { name: '条件字段 1' })).toBeVisible();
  await expect(page.getByRole('button', { name: '全部满足 AND' })).toBeVisible();
  await expect(page.getByRole('button', { name: '任一满足 OR' })).toBeVisible();
});

test('真实行情自选页读取 PostgreSQL 清单且空状态不隐式写入', async ({ page }) => {
  const token = await login(page.request);
  await page.addInitScript((value) => {
    window.localStorage.setItem('stockpro_admin_token', value);
    window.localStorage.setItem('stockpro_auth_profile', JSON.stringify({ role: 'admin', username: 'admin', permissions: ['read', 'write', 'admin'] }));
  }, token);
  await page.goto('/market?tab=watchlist', { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('market-watchlist')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText('清单存 PostgreSQL；行情字段直接读取现有缓存，不复制价格。')).toBeVisible();
  await expect(page.getByText('尚未添加自选证券')).toBeVisible({ timeout: 30_000 });
});

test('真实行情指数与回测因子验证入口归属明确', async ({ page }) => {
  const token = await login(page.request);
  await page.addInitScript((value) => window.localStorage.setItem('stockpro_admin_token', value), token);
  await page.goto('/market?tab=indices', { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('market-indices-panel')).toBeVisible({ timeout: 30_000 });
  await page.goto('/backtest', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('button', { name: '因子验证' })).toBeVisible({ timeout: 30_000 });
  await page.getByRole('button', { name: '因子验证' }).click();
  await expect(page).toHaveURL(/\/factors\?tab=single$/);
});

test('真实扩展数据交换页保持隔离暂存空状态', async ({ page }) => {
  const token = await login(page.request);
  await page.addInitScript((value) => {
    window.localStorage.setItem('stockpro_admin_token', value);
    window.localStorage.setItem('stockpro_auth_profile', JSON.stringify({ role: 'admin', username: 'admin', permissions: ['read', 'write', 'admin'] }));
  }, token);
  await page.goto('/data', { waitUntil: 'domcontentloaded' });
  await page.getByRole('tab', { name: '导入导出' }).click();
  await expect(page.getByTestId('extension-data-exchange')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText('仅暂存 · 未映射')).toBeVisible();
  await expect(page.getByText('尚未导入扩展数据')).toBeVisible({ timeout: 30_000 });
});

test('真实回测页从封存快照预览无重叠 Walk-forward 折', async ({ page }) => {
  const token = await login(page.request);
  const configResponse = await page.request.get('/api/backtest/configuration', {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(configResponse.ok()).toBeTruthy();
  const configuration = (await configResponse.json()) as { dataset_snapshots?: unknown[] };
  await page.addInitScript((value) => window.localStorage.setItem('stockpro_admin_token', value), token);
  await page.goto('/backtest', { waitUntil: 'domcontentloaded' });
  if ((configuration.dataset_snapshots ?? []).length === 0) {
    await expect(page.getByRole('button', { name: '无封存快照' })).toBeDisabled({ timeout: 30_000 });
    return;
  }
  await page.getByRole('button', { name: 'Walk-forward 预览' }).click();
  await page.getByRole('button', { name: '生成折叠计划' }).click();

  await expect(page.getByText(/共 \d+ 折 · \d+ 个可用交易日/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText('预览不可晋级模拟盘')).toBeVisible();
  const firstFold = page.getByText('第 1 折').locator('xpath=ancestor::div[contains(@class,"grid")][1]');
  await expect(firstFold).toContainText('训练');
  await expect(firstFold).toContainText('样本外');
});

test('真实 Walk-forward 完成任务展示持久化 OOS 证据', async ({ page }) => {
  const token = await login(page.request);
  const jobsResponse = await page.request.get('/api/backtest/jobs?limit=100', {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(jobsResponse.ok()).toBeTruthy();
  const jobs = ((await jobsResponse.json()) as { items?: Array<{ job_type?: unknown; status?: unknown; result_payload?: unknown }> }).items ?? [];
  const completed = jobs.find((item) => item.job_type === 'walk_forward' && item.status === 'success' && item.result_payload);
  test.skip(!completed, '当前数据库没有已完成的 Walk-forward 验收任务');

  await page.addInitScript((value) => window.localStorage.setItem('stockpro_admin_token', value), token);
  await page.goto('/backtest', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: '折叠结果' }).first().click();

  await expect(page.getByRole('dialog', { name: 'Walk-forward OOS 结果' })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/不可直接晋级模拟盘/)).toBeVisible();
  await expect(page.getByText('第 1 折')).toBeVisible();
  await expect(page.getByText(/lookback=5/)).toBeVisible();
});

test('真实盯盘规则页可只读预览且明确禁止下单', async ({ page }) => {
  const token = await login(page.request);
  const rulesResponse = await page.request.get('/api/watch/rules', { headers: { Authorization: `Bearer ${token}` } });
  expect(rulesResponse.ok()).toBeTruthy();
  const rules = ((await rulesResponse.json()) as { items?: Array<{ name?: unknown }> }).items ?? [];
  const hasAcceptanceRule = rules.some((item) => item.name === '验收 · 价格观察闭环');
  await page.addInitScript((value) => {
    window.localStorage.setItem('stockpro_admin_token', value);
    window.localStorage.setItem('stockpro_auth_profile', JSON.stringify({ role: 'admin', username: 'admin', permissions: ['read', 'write', 'admin'] }));
  }, token);
  await page.goto('/watch?tab=rules', { waitUntil: 'domcontentloaded' });

  await expect(page.getByTestId('watch-rule-workbench')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText('规则只生成站内告警，不创建订单、不修改模拟盘。')).toBeVisible();
  if (!hasAcceptanceRule) {
    await expect(page.getByText('尚未创建观察规则')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId('watch-rule-card')).toHaveCount(0);
    return;
  }
  const acceptanceRule = page.getByTestId('watch-rule-card').filter({ hasText: '验收 · 价格观察闭环' });
  await expect(acceptanceRule).toBeVisible({ timeout: 30_000 });
  await acceptanceRule.getByRole('button', { name: '只读预览' }).click();
  await expect(page.getByTestId('watch-rule-result')).toContainText('命中 1 条', { timeout: 30_000 });
  await expect(page.getByTestId('watch-rule-result')).toContainText('新增告警 0 条');
  await expect(page.getByTestId('watch-rule-result')).toContainText('创建订单 0 条');
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
  await expect(page.getByTestId('strategy-card').first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText('策略目录读取超时，已停止等待。请稍后重试。')).toHaveCount(0);
  await page.getByRole('tab', { name: /策略广场/ }).click();
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

test('真实 Strategy Watch Monitor 默认隔离业务对象并保留审计证据', async ({ page }) => {
  const token = await login(page.request);
  const headers = { Authorization: `Bearer ${token}` };
  const [strategyBusinessResp, strategyAuditResp, watchBusinessResp, watchAuditResp, monitorBusinessResp, monitorAuditResp] = await Promise.all([
    page.request.get('/api/strategy/list?scope=business', { headers }),
    page.request.get('/api/strategy/list?scope=audit', { headers }),
    page.request.get('/api/watch/context?scope=business', { headers }),
    page.request.get('/api/watch/context?scope=audit', { headers }),
    page.request.get('/api/monitor/health?scope=business', { headers }),
    page.request.get('/api/monitor/health?scope=audit', { headers }),
  ]);
  for (const response of [strategyBusinessResp, strategyAuditResp, watchBusinessResp, watchAuditResp, monitorBusinessResp, monitorAuditResp]) {
    expect(response.ok()).toBeTruthy();
  }

  const strategyBusiness = (await strategyBusinessResp.json()) as Array<{ name?: unknown; data_purpose?: unknown }>;
  const strategyAudit = (await strategyAuditResp.json()) as Array<{ name?: unknown; data_purpose?: unknown }>;
  const watchBusiness = (await watchBusinessResp.json()) as {
    scope?: unknown;
    instances?: Array<{ name?: unknown; data_purpose?: unknown }>;
    coverage?: Record<string, number>;
  };
  const watchAudit = (await watchAuditResp.json()) as {
    scope?: unknown;
    instances?: Array<{ name?: unknown; data_purpose?: unknown }>;
    coverage?: Record<string, number>;
  };
  const monitorBusiness = (await monitorBusinessResp.json()) as {
    scope?: unknown;
    strategy_health?: Array<{ name?: unknown; data_purpose?: unknown }>;
  };
  const monitorAudit = (await monitorAuditResp.json()) as {
    scope?: unknown;
    strategy_health?: Array<{ name?: unknown; data_purpose?: unknown }>;
  };

  expect(strategyBusiness.every((item) => item.data_purpose === 'user')).toBeTruthy();
  expect((watchBusiness.instances ?? []).every((item) => item.data_purpose === 'user')).toBeTruthy();
  expect((monitorBusiness.strategy_health ?? []).every((item) => item.data_purpose === 'user')).toBeTruthy();
  expect(watchBusiness.scope).toBe('business');
  expect(watchAudit.scope).toBe('audit');
  expect(monitorBusiness.scope).toBe('business');
  expect(monitorAudit.scope).toBe('audit');
  expect(strategyAudit.length).toBeGreaterThanOrEqual(strategyBusiness.length);
  expect(Number(watchAudit.coverage?.instances ?? 0)).toBeGreaterThanOrEqual(Number(watchBusiness.coverage?.instances ?? 0));
  expect((monitorAudit.strategy_health ?? []).length).toBeGreaterThanOrEqual((monitorBusiness.strategy_health ?? []).length);

  const acceptanceStrategies = strategyAudit.filter((item) => item.data_purpose === 'acceptance');
  const acceptanceInstances = (watchAudit.instances ?? []).filter((item) => item.data_purpose === 'acceptance');
  expect(acceptanceStrategies.length + acceptanceInstances.length).toBeGreaterThan(0);

  await page.addInitScript((value) => window.localStorage.setItem('stockpro_admin_token', value), token);
  await page.goto('/strategy', { waitUntil: 'networkidle' });
  await expect(page.getByRole('tab', { name: /审计证据/ })).toBeVisible();
  await page.getByRole('tab', { name: /审计证据/ }).click();
  await expect(page.getByTestId('strategy-audit-scope')).toBeVisible();
  if (acceptanceStrategies[0]?.name) {
    await expect(page.getByTestId('strategy-audit-scope')).toContainText(String(acceptanceStrategies[0].name));
  }

  await page.goto('/watch', { waitUntil: 'networkidle' });
  await expect(page.getByTestId('data-scope-control')).toContainText('业务视图');
  await page.getByRole('button', { name: '审计视图' }).click();
  await expect(page.getByTestId('data-scope-control')).toContainText('不改变原始记录');

  await page.goto('/monitor', { waitUntil: 'networkidle' });
  await expect(page.getByTestId('data-scope-control')).toContainText('业务视图');
  await page.getByRole('button', { name: '审计视图' }).click();
  await expect(page.getByTestId('data-scope-control')).toContainText('验收与种子证据');
});

test('真实主阅读层使用业务标签且诊断仍可追溯原值', async ({ page }) => {
  const token = await login(page.request);
  await page.addInitScript((value) => window.localStorage.setItem('stockpro_admin_token', value), token);
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await page.goto('/review?date=2025-01-02&tab=market', { waitUntil: 'domcontentloaded' });
  await expect(page.getByText('市场证据 · 盘后', { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText('全A · 已发布', { exact: true })).toBeVisible();
  const reviewDiagnostics = page.getByRole('group', { name: '时间线诊断原值' }).first();
  await reviewDiagnostics.getByText('查看诊断原值', { exact: true }).click();
  await expect(reviewDiagnostics.getByText('市场证据 · post_close', { exact: true })).toBeVisible();

  await page.goto('/monitor?tab=data', { waitUntil: 'domcontentloaded' });
  const serviceDiagnostics = page.getByRole('group', { name: '服务诊断原值' }).first();
  await expect(serviceDiagnostics).toBeVisible();
  await serviceDiagnostics.getByText('查看诊断原值', { exact: true }).click();
  await expect(serviceDiagnostics.getByText(/paper_(feed|runtime)/)).toBeVisible();
  await expect(page.getByText(/模拟(行情|运行)服务/, { exact: true }).first()).toBeVisible();

  await page.goto('/pools', { waitUntil: 'domcontentloaded' });
  const poolEvidence = page.getByRole('heading', { name: '输入绑定与证据状态' }).locator('xpath=ancestor::section[1]');
  const poolDiagnostics = poolEvidence.getByRole('group', { name: '输入绑定诊断原值' });
  if (await poolDiagnostics.count()) {
    await expect(poolEvidence.getByText('研究数据快照已绑定 · 历史股票范围已绑定')).toBeVisible();
    await poolDiagnostics.getByText('查看诊断原值', { exact: true }).click();
    await expect(poolDiagnostics.getByText(/Dataset #\d+/)).toBeVisible();
  } else {
    await expect(page.getByText('还没选中股票池')).toBeVisible();
  }

  expect(pageErrors, pageErrors.join('\n')).toEqual([]);
});

test('真实股票池快照区分当前有效与历史研究并隔离验收对象', async ({ page }) => {
  const token = await login(page.request);
  const headers = { Authorization: `Bearer ${token}` };
  const response = await page.request.get('/api/pool-snapshots', { headers });
  expect(response.ok()).toBeTruthy();
  const snapshots = ((await response.json()) as {
    items?: Array<{
      id?: unknown;
      pool_name?: unknown;
      data_purpose?: unknown;
      member_count?: unknown;
      valid_until?: unknown;
    }>;
  }).items ?? [];
  expect(
    snapshots
      .filter((item) => Number(item.member_count) > 0)
      .every((item) => /^\d{4}-\d{2}-\d{2}$/.test(String(item.valid_until ?? '')))
  ).toBeTruthy();

  const businessSnapshots = snapshots.filter(
    (item) => !item.data_purpose || item.data_purpose === 'user'
  );
  const auditSnapshots = snapshots.filter(
    (item) => item.data_purpose === 'acceptance' || item.data_purpose === 'seed'
  );

  await page.addInitScript((value) => window.localStorage.setItem('stockpro_admin_token', value), token);
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.goto('/pools?tab=snapshots', { waitUntil: 'domcontentloaded' });
  const table = page.getByTestId('pool-snapshot-table');
  await expect(table).toBeVisible();
  await expect(page.getByText('正在加载股票池规则与封存快照…')).toHaveCount(0, {
    timeout: 60_000,
  });
  await expect(table.locator('tbody tr')).toHaveCount(businessSnapshots.length);
  for (const snapshot of auditSnapshots) {
    await expect(table.getByText(String(snapshot.pool_name), { exact: true })).toHaveCount(0);
  }
  for (const snapshot of businessSnapshots) {
    const availability = page.getByTestId(`pool-snapshot-availability-${snapshot.id}`);
    const expired = String(snapshot.valid_until) < new Date().toISOString().slice(0, 10);
    await expect(availability).toContainText(expired ? '历史快照' : '当前有效快照');
  }
  expect(pageErrors, pageErrors.join('\n')).toEqual([]);
});

test('真实百因子目录展示独立成熟度分母与研究门禁', async ({ page }) => {
  const token = await login(page.request);
  const response = await page.request.get('/api/factors/research/library', {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(response.ok()).toBeTruthy();
  const factors = ((await response.json()) as { items?: unknown[] }).items ?? [];
  expect(factors).toHaveLength(100);

  await page.addInitScript((value) => window.localStorage.setItem('stockpro_admin_token', value), token);
  await page.goto('/factors', { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('factor-stage-defined')).toContainText('100', { timeout: 30_000 });
  await expect(page.getByTestId('factor-stage-computed')).toBeVisible();
  await expect(page.getByTestId('factor-stage-evaluated')).toBeVisible();
  await expect(page.getByTestId('factor-stage-eligible')).toBeVisible();
  for (const id of ['factor-check-cross-sectional', 'factor-check-time-series', 'factor-check-out-of-sample', 'factor-check-leakage']) {
    await expect(page.getByTestId(id)).toBeVisible();
  }
});

test('真实完整回测展示八类证据、研究门禁且收盘信号不会同日成交', async ({ page }) => {
  test.setTimeout(120_000);
  const token = await login(page.request);
  const headers = { Authorization: `Bearer ${token}` };
  const runsResp = await page.request.get('/api/backtest/runs?limit=100', { headers });
  expect(runsResp.ok()).toBeTruthy();
  const runs = ((await runsResp.json()) as { items?: Array<{ id?: unknown; status?: unknown; run_mode?: unknown; promotion_gate_complete?: unknown }> }).items ?? [];
  expect(runs.filter((item) => item.promotion_gate_complete === true).every((item) => item.status === 'success' && item.run_mode === 'full')).toBeTruthy();
  const run = runs.find((item) => item.status === 'success' && item.run_mode === 'full');
  test.skip(!run, '本地 PG 尚无成功的完整回测');
  const runId = String(run?.id ?? '');

  const detailResp = await page.request.get(`/api/backtest/runs/${runId}`, { headers });
  const metricsResp = await page.request.get(`/api/backtest/runs/${runId}/metrics`, { headers });
  const ordersResp = await page.request.get(`/api/backtest/runs/${runId}/orders`, { headers });
  expect(detailResp.ok()).toBeTruthy();
  expect(metricsResp.ok()).toBeTruthy();
  expect(ordersResp.ok()).toBeTruthy();
  const detail = (await detailResp.json()) as { promotion_gate_complete?: unknown; promotion_checks?: Array<{ check_code?: unknown; status?: unknown }> };
  if (detail.promotion_gate_complete === true) {
    expect((detail.promotion_checks ?? []).filter((item) => item.status === 'passed')).toHaveLength(11);
  }
  const metrics = ((await metricsResp.json()) as { items?: unknown[] }).items ?? [];
  const orders = ((await ordersResp.json()) as { items?: Array<{ signal_at?: unknown; filled_at?: unknown }> }).items ?? [];
  expect(metrics.length).toBeGreaterThanOrEqual(41);
  expect(orders.filter((item) => item.filled_at).every((item) => String(item.filled_at).slice(0, 10) > String(item.signal_at).slice(0, 10))).toBeTruthy();

  await page.addInitScript((value) => window.localStorage.setItem('stockpro_admin_token', value), token);
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.goto(`/backtest/${runId}`, { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('tab', { name: '总览' })).toBeVisible({ timeout: 60_000 });
  for (const tab of ['总览', '绩效指标', '持仓', '交易', '订单', '日志', '代码与参数', '归因']) {
    await expect(page.getByRole('tab', { name: tab })).toBeVisible();
  }
  await expect(page.getByText('可复现实验凭证')).toBeVisible();
  await expect(page.getByRole('heading', { name: '研究晋级门禁' })).toBeVisible();
  for (const label of ['训练区间', '验证区间', '样本外区间', '成本证据', '容量约束', '基准证据']) {
    await expect(page.getByText(label, { exact: true })).toBeVisible();
  }
  if (detail.promotion_gate_complete === true) {
    await expect(page.getByText('Paper Eligible', { exact: true })).toBeVisible();
  } else {
    await expect(page.getByText('Paper Eligible', { exact: true })).toHaveCount(0);
  }
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
  await expect(page.getByRole('heading', { name: '行情' })).toBeVisible();
  await expect(page.getByText('连板天梯')).toBeVisible();
  await page.goto('/pools?tab=snapshots', { waitUntil: 'networkidle' });
  await expect(page.getByRole('heading', { name: '股票池' })).toBeVisible();
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
    page.request.get('/api/watch/context?scope=audit', { headers }),
    page.request.get('/api/monitor/health?scope=audit', { headers }),
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
  const watch = (await watchResp.json()) as {
    alerts?: Array<{ paper_instance_id?: unknown }>;
    instances?: Array<{ id?: unknown }>;
    orders?: Array<{ paper_instance_id?: unknown }>;
    trades?: Array<{ paper_instance_id?: unknown }>;
    risk_events?: Array<{ paper_instance_id?: unknown }>;
    source_updated_at?: unknown;
    response_generated_at?: unknown;
  };
  expect((watch.instances ?? []).some((item) => String(item.id) === instanceId)).toBeTruthy();
  expect((watch.alerts ?? []).some((item) => String(item.paper_instance_id) === instanceId)).toBeTruthy();
  expect((watch.orders ?? []).some((item) => String(item.paper_instance_id) === instanceId)).toBeTruthy();
  expect((watch.trades ?? []).some((item) => String(item.paper_instance_id) === instanceId)).toBeTruthy();
  expect((watch.risk_events ?? []).some((item) => String(item.paper_instance_id) === instanceId)).toBeTruthy();
  expect(typeof watch.source_updated_at).toBe('string');
  expect(typeof watch.response_generated_at).toBe('string');
  const health = (await healthResp.json()) as {
    status?: unknown;
    strategy_instances?: unknown[];
    strategy_health?: Array<{ id?: unknown; health_state?: unknown; data_purpose?: unknown }>;
    services?: unknown[];
    source_updated_at?: unknown;
    response_generated_at?: unknown;
  };
  expect(['healthy', 'warning', 'critical']).toContain(String(health.status));
  expect(Array.isArray(health.strategy_instances)).toBeTruthy();
  const instanceHealth = (health.strategy_health ?? []).find((item) => String(item.id) === instanceId);
  expect(instanceHealth).toBeTruthy();
  expect(['fresh', 'stale', 'missing', 'failed', 'stopped', 'draft']).toContain(String(instanceHealth?.health_state));
  expect(['user', 'acceptance', 'seed']).toContain(String(instanceHealth?.data_purpose));
  expect(typeof health.source_updated_at).toBe('string');
  expect(typeof health.response_generated_at).toBe('string');

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
  await page.goto('/review?date=2025-01-02&tab=logs', { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('daily-review-workbench')).toBeVisible({ timeout: 30_000 });
  for (const title of ['指数快照', '市场宽度', '情绪指标', '涨停生态', '人气榜', '板块资金']) {
    await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
  }
  await expect(page.getByRole('heading', { name: '交易日时间线' })).toBeVisible();
  await expect(page.getByText('复盘已封存，不可修改')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(String(review.source_manifest_hash))).toHaveCount(0);
  await expect(page.getByText('查看关联记录 →').first()).toBeVisible();

  const firstLevelLinks = page.getByRole('complementary').locator('nav a');
  await expect(firstLevelLinks).toHaveCount(7);
  await expect(firstLevelLinks).toHaveText([
    /首页/,
    /策略/,
    /回测/,
    /模拟/,
    /行情/,
    /盯盘/,
    /数据/,
  ]);
  expect(pageErrors, pageErrors.join('\n')).toEqual([]);
});

test('十二个主要页面通过真实后端只读加载且共享可信状态壳', async ({ page }) => {
  const token = await login(page.request);
  await page.addInitScript((value) => window.localStorage.setItem('stockpro_admin_token', value), token);
  await page.setViewportSize({ width: 1440, height: 960 });
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  const pages = [
    ['/', '市场大盘'],
    ['/market', '行情'],
    ['/pools', '股票池'],
    ['/factors', '因子研究'],
    ['/strategy', '策略中心'],
    ['/backtest', '回测实例控制台'],
    ['/ai-lab', 'AI研发'],
    ['/paper', '模拟盘'],
    ['/watch', '盯盘'],
    ['/monitor', '监控中心'],
    ['/review', '复盘中心'],
    ['/data', '数据管理中心'],
  ] as const;

  for (const [path, title] of pages) {
    const response = await page.goto(path, { waitUntil: 'domcontentloaded' });
    expect(response?.ok(), `${path} document should load`).toBeTruthy();
    await expect(page.getByRole('heading', { name: title }).first()).toBeVisible();
    await expect(page.getByRole('navigation', { name: '主菜单' })).toBeVisible();
  }
  expect(pageErrors, pageErrors.join('\n')).toEqual([]);
});

test('首页未登录进入登录页', async ({ page }) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (err) => pageErrors.push(err.message));

  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page).toHaveURL(/\/admin-login/);
  expect(pageErrors, pageErrors.join('\n')).toEqual([]);
});
