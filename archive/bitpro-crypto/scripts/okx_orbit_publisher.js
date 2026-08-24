#!/usr/bin/env node
/*
 * Server-local OKX Orbit web publisher.
 *
 * Input: JSON on stdin with { action: "status" | "publish", content, candidate }.
 * Output: one JSON object on stdout.
 *
 * This intentionally uses a persistent browser profile so the operator can log
 * in once through OKX web QR login. OKX does not expose a documented Orbit
 * posting API, so selectors are conservative and failure is explicit.
 */

const fs = require('fs');
const path = require('path');

async function readStdin() {
  return await new Promise((resolve) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => { data += chunk; });
    process.stdin.on('end', () => resolve(data));
  });
}

function emit(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function clearProxyEnvironment() {
  if (process.env.BITPRO_ORBIT_USE_SYSTEM_PROXY === '1') return;
  for (const key of ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']) {
    delete process.env[key];
  }
  process.env.NO_PROXY = '*';
  process.env.no_proxy = '*';
}

function requirePlaywright() {
  const candidates = [
    process.env.BITPRO_PLAYWRIGHT_NODE_PATH,
    path.resolve(__dirname, '..', 'node_modules', 'playwright'),
    '/opt/bitpro/node_modules/playwright',
    '/opt/bitpro/tmp/playwright-test/node_modules/playwright',
  ].filter(Boolean);

  for (const candidate of candidates) {
    try {
      return require(candidate);
    } catch (error) {
      // Try next candidate.
    }
  }

  try {
    return require('playwright');
  } catch (error) {
    throw new Error(
      'Playwright 未安装。请在服务器安装 playwright，或设置 BITPRO_PLAYWRIGHT_NODE_PATH 指向 playwright 包。'
    );
  }
}

async function pageText(page) {
  return await page.locator('body').innerText({ timeout: 5000 }).catch(() => '');
}

async function isLoggedIn(page) {
  const url = page.url();
  const text = await pageText(page);
  if (/account\/login/.test(url)) return false;
  if (/登录\/注册|登录|Log in|Sign in/.test(text) && /扫码|二维码|password|邮箱|手机号/i.test(text)) {
    return false;
  }
  return true;
}

async function clickByText(page, patterns) {
  const handles = await page.locator('button, [role="button"], a, div, span').elementHandles();
  for (const handle of handles) {
    const text = ((await handle.innerText().catch(() => '')) || '').trim();
    if (!text) continue;
    if (patterns.some((pattern) => pattern.test(text))) {
      await handle.click({ timeout: 3000 }).catch(() => null);
      return true;
    }
  }
  return false;
}

async function fillComposer(page, content) {
  const textbox = page.locator('textarea, [contenteditable="true"], [role="textbox"]').first();
  await textbox.waitFor({ timeout: 12000 });
  const tagName = await textbox.evaluate((node) => node.tagName.toLowerCase()).catch(() => '');
  if (tagName === 'textarea') {
    await textbox.fill(content);
  } else {
    await textbox.click();
    await page.keyboard.insertText(content);
  }
}

async function main() {
  clearProxyEnvironment();
  const raw = await readStdin();
  const payload = raw ? JSON.parse(raw) : {};
  const action = payload.action || 'status';
  const { chromium } = requirePlaywright();
  const profileDir = process.env.BITPRO_ORBIT_PROFILE_DIR || '/opt/bitpro/data/orbit-playwright-profile';
  const baseUrl = process.env.BITPRO_ORBIT_URL || 'https://www.okx.com/zh-hans/orbit/feed';

  fs.mkdirSync(profileDir, { recursive: true });
  const context = await chromium.launchPersistentContext(profileDir, {
    headless: process.env.BITPRO_ORBIT_HEADLESS !== '0',
    viewport: { width: 1440, height: 1100 },
    args: ['--no-proxy-server', '--proxy-server=direct://', '--proxy-bypass-list=*'],
  });
  const page = context.pages()[0] || await context.newPage();

  try {
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await page.waitForTimeout(2500);
    const loggedIn = await isLoggedIn(page);
    if (action === 'status') {
      emit({ status: loggedIn ? 'ready' : 'login_required', available: true, logged_in: loggedIn, url: page.url() });
      return;
    }

    if (!loggedIn) {
      emit({
        status: 'login_required',
        available: true,
        logged_in: false,
        url: page.url(),
        error: 'OKX Orbit Web 未登录。请先在服务器持久化浏览器会话中扫码登录。',
      });
      return;
    }

    const opened = await clickByText(page, [/发帖/, /发布/, /^Post$/i, /Write/i]);
    if (!opened) {
      throw new Error('未找到 OKX Orbit 发帖入口，可能是页面结构或账号权限变化');
    }
    await page.waitForTimeout(1000);
    await fillComposer(page, String(payload.content || ''));
    const published = await clickByText(page, [/^发布$/, /^Post$/i, /发送/, /Publish/i]);
    if (!published) {
      throw new Error('未找到 OKX Orbit 发布按钮');
    }
    await page.waitForTimeout(3000);
    emit({ status: 'submitted', available: true, logged_in: true, url: page.url() });
  } finally {
    await context.close();
  }
}

main().catch((error) => {
  emit({ status: 'failed', available: false, error: error && error.message ? error.message : String(error) });
  process.exit(1);
});
