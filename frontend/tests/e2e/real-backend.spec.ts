import { test, expect } from '@playwright/test';

const runRealBackendSuite =
  process.env.MOCK_API === 'false' || process.env.E2E_REAL_BACKEND === '1';

test.skip(
  !runRealBackendSuite,
  'This suite requires real backend mode. Set MOCK_API=false.'
);

test.describe.configure({ mode: 'serial' });

test('后端健康接口可访问', async ({ request }) => {
  const resp = await request.get('/api/v1/health/health');
  expect(resp.ok()).toBeTruthy();

  const data = (await resp.json()) as { status?: unknown };
  expect(typeof data).toBe('object');
  expect(['healthy', 'success', 'warning']).toContain(String(data.status ?? ''));
});

test('股票搜索接口返回数组', async ({ request }) => {
  const resp = await request.get('/api/v1/stocks/search?q=6&limit=5');
  expect(resp.ok()).toBeTruthy();

  const data = (await resp.json()) as unknown;
  expect(Array.isArray(data)).toBeTruthy();
});

test('市场概览接口返回关键结构', async ({ request }) => {
  const resp = await request.get('/api/v1/market/overview');
  expect(resp.ok()).toBeTruthy();

  const data = (await resp.json()) as {
    indices?: unknown;
    sentiment?: {
      score?: unknown;
      status?: unknown;
      advancing?: unknown;
      declining?: unknown;
      unchanged?: unknown;
    };
    volume?: {
      amount?: unknown;
      ratio?: unknown;
    };
    is_open?: unknown;
    last_update?: unknown;
  };

  expect(Array.isArray(data.indices)).toBeTruthy();
  expect(typeof data.sentiment).toBe('object');
  expect(typeof data.sentiment?.score).toBe('number');
  expect(typeof data.sentiment?.status).toBe('string');
  expect(typeof data.sentiment?.advancing).toBe('number');
  expect(typeof data.sentiment?.declining).toBe('number');
  expect(typeof data.sentiment?.unchanged).toBe('number');
  expect(typeof data.volume).toBe('object');
  expect(typeof data.volume?.amount).toBe('number');
  expect(typeof data.volume?.ratio).toBe('number');
  expect(typeof data.is_open).toBe('boolean');
  expect(typeof data.last_update).toBe('string');
});

test('SQL 查询接口可执行且拦截非 SELECT', async ({ request }) => {
  const selectResp = await request.post('/api/v1/database/query', {
    data: {
      query: 'SELECT name FROM sqlite_master WHERE type = "table" ORDER BY name LIMIT 5',
    },
  });
  expect(selectResp.ok()).toBeTruthy();
  const selectData = (await selectResp.json()) as {
    columns?: unknown;
    rows?: unknown;
    rowCount?: unknown;
  };
  expect(Array.isArray(selectData.columns)).toBeTruthy();
  expect(Array.isArray(selectData.rows)).toBeTruthy();
  expect(typeof selectData.rowCount).toBe('number');
  expect((selectData.columns as string[]).includes('name')).toBeTruthy();

  const rejectResp = await request.post('/api/v1/database/query', {
    data: {
      query: 'DELETE FROM stock_history',
    },
  });
  expect(rejectResp.status()).toBe(400);
});

test('DataDev 任务 CRUD + 运行 + 日志可用', async ({ request }) => {
  const taskName = `e2e_datadev_${Date.now()}`;
  const createResp = await request.post('/api/v1/data-dev/tasks', {
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
    const listResp = await request.get('/api/v1/data-dev/tasks');
    expect(listResp.ok()).toBeTruthy();
    const tasks = (await listResp.json()) as Array<{ id?: unknown; name?: unknown }>;
    expect(tasks.some((item) => Number(item.id) === taskId)).toBeTruthy();

    const updateResp = await request.put(`/api/v1/data-dev/tasks/${taskId}`, {
      data: {
        name: taskName,
        description: 'updated by playwright',
        sql_content: 'CREATE TABLE IF NOT EXISTS e2e_temp_table (id INTEGER PRIMARY KEY)',
        cron_expression: '0 19 * * *',
        enabled: false,
      },
    });
    expect(updateResp.ok()).toBeTruthy();

    const runResp = await request.post(`/api/v1/data-dev/tasks/${taskId}/run`);
    expect(runResp.ok()).toBeTruthy();

    const logsResp = await request.get(`/api/v1/data-dev/tasks/${taskId}/logs?limit=10`);
    expect(logsResp.ok()).toBeTruthy();
    const logs = (await logsResp.json()) as Array<{ status?: unknown }>;
    expect(logs.length).toBeGreaterThan(0);
    expect(logs.some((log) => ['success', 'failed', 'running'].includes(String(log.status ?? '')))).toBeTruthy();
  } finally {
    const deleteResp = await request.delete(`/api/v1/data-dev/tasks/${taskId}`);
    expect(deleteResp.ok()).toBeTruthy();
  }
});

test('后台任务状态接口可访问', async ({ request }) => {
  const adminPassword = process.env.E2E_ADMIN_PASSWORD || process.env.ADMIN_PASSWORD;
  test.skip(!adminPassword, 'Set E2E_ADMIN_PASSWORD or ADMIN_PASSWORD to test protected admin APIs.');

  const loginResp = await request.post('/api/v1/auth/admin/login', {
    data: {
      username: process.env.E2E_ADMIN_USERNAME || process.env.ADMIN_USERNAME || 'admin',
      password: adminPassword,
    },
  });
  expect(loginResp.ok()).toBeTruthy();
  const loginData = (await loginResp.json()) as { access_token?: unknown };
  expect(typeof loginData.access_token).toBe('string');

  const resp = await request.get('/api/v1/admin/task-status', {
    headers: {
      Authorization: `Bearer ${loginData.access_token}`,
    },
  });
  expect(resp.ok()).toBeTruthy();

  const data = (await resp.json()) as {
    is_running?: unknown;
    total?: unknown;
    processed?: unknown;
    message?: unknown;
  };
  expect(typeof data).toBe('object');
  expect(typeof data.is_running).toBe('boolean');
});

test('首页基础渲染正常', async ({ page }) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (err) => pageErrors.push(err.message));

  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('header h2')).toContainText(/实时大盘|Dashboard/, { timeout: 15000 });

  expect(pageErrors, pageErrors.join('\n')).toEqual([]);
});
