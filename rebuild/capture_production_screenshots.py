#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROUTES = [
    ("home", "/"), ("market", "/market"), ("strategy", "/strategy"),
    ("backtest", "/backtest"), ("spread", "/arbitrage"), ("fundamentals", "/onchain"),
    ("paper", "/live"), ("signals", "/signals"), ("watch", "/watch"),
    ("orderflow", "/orderflow"), ("review", "/review"), ("monitor", "/monitor"),
    ("data", "/data"), ("factors", "/factorlab"), ("ai-lab", "/ai-lab"),
    ("arc", "/arc"),
]
VIEWPORTS = [("1440x900", 1440, 900), ("390x844", 390, 844)]

NODE_SCRIPT = r"""
import { chromium } from 'playwright';
const routes = JSON.parse(process.env.CAPTURE_ROUTES);
const viewports = JSON.parse(process.env.CAPTURE_VIEWPORTS);
const base = process.env.CAPTURE_BASE;
const dir = process.env.CAPTURE_OUTPUT;
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext();
const loginPage = await context.newPage();
await loginPage.goto(base + '/');
await loginPage.waitForFunction(() =>
  document.querySelector('[data-testid="main-layout"]') ||
  [...document.querySelectorAll('h1')].some((item) => item.textContent?.includes('登录 StockPro')),
  { timeout: 120000 },
);
if (await loginPage.getByRole('heading', { name: '登录 StockPro' }).isVisible()) {
  await loginPage.getByRole('button', { name: '管理员登录' }).click();
  await loginPage.getByText('管理员账号').locator('..').locator('input').fill(process.env.STOCKPRO_CAPTURE_USERNAME || 'admin');
  await loginPage.getByText('密码', { exact: true }).locator('..').locator('input').fill(process.env.STOCKPRO_CAPTURE_PASSWORD || '');
  await loginPage.getByRole('button', { name: '进入工作台' }).click();
  await loginPage.getByTestId('main-layout').waitFor({ timeout: 120000 });
}
await loginPage.close();
const captures = [];
for (const [viewport, width, height] of viewports) {
  for (const [slug, route] of routes) {
    console.error(`[capture] ${viewport} ${route}`);
    // Use a fresh page for every route so chart instances, timers, and listeners
    // from a previous operator workspace cannot contaminate later captures.
    const page = await context.newPage();
    await page.setViewportSize({ width, height });
    const errors = [];
    const writes = [];
    const onConsole = (message) => { if (message.type() === 'error') errors.push(message.text()); };
    const onRequest = (request) => { if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method())) writes.push(request.url()); };
    page.on('console', onConsole);
    page.on('request', onRequest);
    const started = Date.now();
    await page.goto(base + route);
    await page.getByTestId('main-layout').waitFor({ timeout: 120000 });
    await page.locator('[data-operator-page]').waitFor({ timeout: 120000 });
    // Operator pages intentionally poll health/runtime evidence, so networkidle is
    // not a valid readiness signal. Require the visible loading contract to settle
    // into either real data or an honest empty/error state before capturing.
    await page.waitForTimeout(500);
    await page.waitForFunction(() => {
      if (document.querySelector('.animate-pulse')) return false;
      const pending = /(正在加载|加载中|读取中)/;
      return ![...document.querySelectorAll('body *')].some((element) => {
        if (!pending.test(element.textContent || '')) return false;
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      });
    }, { timeout: 120000 });
    await page.waitForTimeout(300);
    const file = `${slug}-${viewport}.png`;
    await page.screenshot({ path: `${dir}/${file}`, fullPage: true });
    captures.push({ route, viewport, url: page.url(), artifact: file, captured_at: new Date().toISOString(), duration_ms: Date.now() - started, source_updated_at: null, console_errors: errors, writes });
    page.off('console', onConsole);
    page.off('request', onRequest);
    await page.close();
  }
}
await browser.close();
console.log(JSON.stringify(captures));
"""


def capture(base_url: str, sha: str, output: Path, routes: list[tuple[str, str]] | None = None) -> dict:
    selected_routes = routes or ROUTES
    output.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "CAPTURE_ROUTES": json.dumps(selected_routes),
        "CAPTURE_VIEWPORTS": json.dumps(VIEWPORTS),
        "CAPTURE_BASE": base_url.rstrip("/"),
        "CAPTURE_OUTPUT": str(output.resolve()),
    }
    result = subprocess.run(
        ["node", "--input-type=module"], input=NODE_SCRIPT, text=True,
        capture_output=True, cwd=Path(__file__).resolve().parents[1] / "frontend", env=env,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "browser capture failed")
    captures = json.loads(result.stdout)
    return {
        "schema_version": "stockpro.real-ui-capture.current",
        "environment": "local-isolated",
        "mock_api": False,
        "deployed_sha": sha,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "routes": [route for _, route in selected_routes],
        "captures": [{**item, "mock_api": False, "deployed_sha": sha} for item in captures],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only", help="Comma-separated route slugs to recapture and merge")
    args = parser.parse_args()
    selected = ROUTES
    if args.only:
        slugs = {item.strip() for item in args.only.split(",") if item.strip()}
        selected = [item for item in ROUTES if item[0] in slugs]
        if not selected or {item[0] for item in selected} != slugs:
            raise ValueError("--only contains an unknown route slug")
    manifest = capture(args.base_url, args.sha, args.output, selected)
    index_path = args.output / "capture-index.json"
    if args.only and index_path.exists():
        previous = json.loads(index_path.read_text())
        replacements = {(item["route"], item["viewport"]): item for item in manifest["captures"]}
        captures = [replacements.pop((item["route"], item["viewport"]), item) for item in previous["captures"]]
        captures.extend(replacements.values())
        manifest = {**previous, "deployed_sha": args.sha, "captured_at": manifest["captured_at"], "routes": [route for _, route in ROUTES], "captures": captures}
    index_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"captures": len(manifest["captures"]), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
