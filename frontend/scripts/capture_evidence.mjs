import { chromium } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SHOT = path.resolve(__dirname, '../../.gstack/qa-reports/screenshots/pw');
const BASE = 'http://127.0.0.1:4444';

const PAGES = [
  ['/', 'home'],
  ['/market?tab=sentiment', 'market-sentiment'],
  ['/market?tab=structure', 'market-structure'],
  ['/', 'dashboard-shortline', 'click-shortline'],
  ['/review?tab=market', 'review-market'],
  ['/data', 'data-overview'],
  ['/data/processing', 'data-processing'],
  ['/paper', 'paper'],
  ['/factors', 'factors-library'],
];

const PROBE = `(() => {
  const metrics = [...document.querySelectorAll('.font-mono.font-bold.tabular-nums, .bp-metric-card__value')];
  const tones = metrics.slice(0, 50).map((el) => ({
    text: (el.textContent || '').trim().slice(0, 48),
    cls: String(el.className || ''),
    color: getComputedStyle(el).color,
  }));
  const whiteish = tones.filter((t) => {
    const m = t.color.match(/rgb\\((\\d+),\\s*(\\d+),\\s*(\\d+)\\)/);
    if (!m) return false;
    const r = +m[1], g = +m[2], b = +m[3];
    return r > 235 && g > 235 && b > 235;
  });
  return {
    title: (document.querySelector('h1')?.textContent || '').trim().slice(0, 100),
    hasOperator: !!document.querySelector('[data-operator-page]'),
    metricCount: metrics.length,
    whiteishCount: whiteish.length,
    whiteish: whiteish.slice(0, 6),
    overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth + 4,
  };
})()`;

await mkdir(SHOT, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

await page.goto(`${BASE}/admin-login`, { waitUntil: 'networkidle' });
await page.getByLabel('密码').fill('stockpro123');
await page.getByRole('button', { name: '登录' }).click();
await page.waitForURL((url) => !url.pathname.includes('admin-login'), { timeout: 15000 });
await page.waitForTimeout(2000);

for (const [route, slug, action] of PAGES) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle' });
  if (action === 'click-shortline') {
    const tab = page.getByRole('tab', { name: /短线/ });
    if (await tab.count()) await tab.click();
    await page.waitForTimeout(1500);
  } else {
    await page.waitForTimeout(1200);
  }
  const probe = await page.evaluate(PROBE);
  await page.screenshot({ path: path.join(SHOT, `${slug}.png`), fullPage: false });
  console.log(JSON.stringify({ slug, ...probe }));
}

await browser.close();
console.log('DONE', SHOT);
