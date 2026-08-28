import { chromium } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const SHOT = '/Users/jie.feng/Dev/Github/Private/StockPro/.gstack/qa-reports/screenshots/2026-08-17';
const BASE = 'http://127.0.0.1:4444';
const OUT = '/Users/jie.feng/Dev/Github/Private/StockPro/.gstack/qa-reports/visual-2026-08-17.jsonl';

const PAGES = [
  ['/', 'home'],
  ['/market?tab=structure', 'market-structure'],
  ['/market?tab=sectors', 'market-sectors'],
  ['/market?tab=sentiment', 'market-sentiment'],
  ['/market?tab=events', 'market-events'],
  ['/market?tab=calendar', 'market-calendar'],
  ['/market?tab=stock', 'market-stock'],
  ['/pools?tab=mine', 'pools-mine'],
  ['/pools?tab=screener', 'pools-screener'],
  ['/factors', 'factors'],
  ['/strategy', 'strategy'],
  ['/backtest', 'backtest'],
  ['/paper', 'paper'],
  ['/watch?tab=signals', 'watch-signals'],
  ['/monitor?tab=overview', 'monitor-overview'],
  ['/review?tab=market', 'review-market'],
  ['/data', 'data'],
  ['/data/processing', 'data-processing'],
  ['/ai-lab', 'ai-lab'],
];

const PROBE = `(() => {
  const metrics = [...document.querySelectorAll('.font-mono.font-bold.tabular-nums, .bp-metric-card__value, [class*="MetricValue"]')];
  const tones = metrics.slice(0, 60).map((el) => ({
    text: (el.textContent || '').trim().slice(0, 40),
    cls: String(el.className || '').slice(0, 160),
    color: getComputedStyle(el).color,
  }));
  const whiteish = tones.filter((t) => {
    const m = t.color.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
    if (!m) return false;
    return +m[1] > 235 && +m[2] > 235 && +m[3] > 235;
  });
  const nearWhite = tones.filter((t) => {
    const m = t.color.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
    if (!m) return false;
    return +m[1] > 210 && +m[2] > 210 && +m[3] > 210;
  });
  const h1 = document.querySelector('h1');
  const rail = document.querySelector('[data-testid="research-desk-rail"], [class*="research-desk"], [aria-label*="研究台"]');
  return {
    url: location.href,
    title: (h1?.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 140),
    hasOperator: !!document.querySelector('[data-operator-page]'),
    operator: document.querySelector('[data-operator-page]')?.getAttribute('data-operator-page') || null,
    headingCount: document.querySelectorAll('h1,h2').length,
    metricCount: metrics.length,
    whiteishCount: whiteish.length,
    nearWhiteCount: nearWhite.length,
    whiteish: whiteish.slice(0, 8),
    nearWhite: nearWhite.slice(0, 8),
    overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth + 4,
    scrollW: document.documentElement.scrollWidth,
    clientW: document.documentElement.clientWidth,
    bodySnippet: (document.body?.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 220),
    hasRail: !!rail,
    sessionGate: /正在校验访问会话/.test(document.body?.innerText || ''),
  };
})()`;

await mkdir(SHOT, { recursive: true });
await writeFile(OUT, '');

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const consoleErrors = [];
page.on('pageerror', (err) => consoleErrors.push(String(err)));
page.on('console', (msg) => {
  if (msg.type() === 'error') consoleErrors.push(msg.text());
});

await page.goto(`${BASE}/admin-login`, { waitUntil: 'domcontentloaded' });
await page.getByLabel('密码').fill('stockpro123');
await page.getByRole('button', { name: '登录' }).click();
await page.waitForURL((url) => !url.pathname.includes('admin-login'), { timeout: 20000 });
await page.waitForFunction(() => !/正在校验访问会话/.test(document.body?.innerText || ''), { timeout: 20000 }).catch(() => {});
await page.waitForTimeout(800);

for (const [route, slug] of PAGES) {
  consoleErrors.length = 0;
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !/正在校验访问会话/.test(document.body?.innerText || ''), { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(1200);
  const probe = await page.evaluate(PROBE);
  await page.screenshot({ path: path.join(SHOT, `${slug}.png`), fullPage: false });
  const rec = { slug, route, probe, errors: [...consoleErrors].slice(0, 8) };
  await writeFile(OUT, JSON.stringify(rec, null, 0) + '\n', { flag: 'a' });
  console.log(
    `${slug} title=${JSON.stringify(probe.title)} metrics=${probe.metricCount} white=${probe.whiteishCount} near=${probe.nearWhiteCount} overflow=${probe.overflowX} op=${probe.hasOperator} gate=${probe.sessionGate} errs=${consoleErrors.length}`,
  );
}

await page.setViewportSize({ width: 390, height: 844 });
for (const [route, slug] of [['/', 'home-mobile'], ['/market?tab=sentiment', 'sentiment-mobile'], ['/strategy', 'strategy-mobile']]) {
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  const probe = await page.evaluate(PROBE);
  await page.screenshot({ path: path.join(SHOT, `${slug}.png`), fullPage: false });
  await writeFile(OUT, JSON.stringify({ slug, route, probe, errors: [] }) + '\n', { flag: 'a' });
  console.log(`mobile ${slug} overflow=${probe.overflowX} title=${JSON.stringify(probe.title)}`);
}

await browser.close();
console.log('DONE', SHOT);
