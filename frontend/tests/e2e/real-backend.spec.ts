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

test('首页未登录进入登录页', async ({ page }) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (err) => pageErrors.push(err.message));

  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page).toHaveURL(/\/admin-login/);
  expect(pageErrors, pageErrors.join('\n')).toEqual([]);
});
