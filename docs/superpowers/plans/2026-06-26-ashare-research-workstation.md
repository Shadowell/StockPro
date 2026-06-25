# A-Share Research Workstation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every StockPro page a usable, professional A-share research or execution surface with visible data readiness and executable trading constraints.

**Architecture:** Add small shared contracts first: page readiness metadata, data freshness display, and A-share constraint policy. Then wire those contracts into research, strategy, backtest, paper, monitor, and data pages with test-first slices. Backend validation follows the same policy so visible guardrails become executable checks.

**Tech Stack:** React 18, TypeScript, Vite, Playwright, FastAPI, Python unittest, Postgres repositories.

---

## File Structure

- Create: `frontend/src/lib/pageReadiness.ts` - route metadata and required page anchors.
- Create: `frontend/src/components/DataReadinessBadge.tsx` - compact source/freshness/status badge.
- Create: `frontend/src/lib/ashareConstraints.ts` - frontend policy for T+1, 100-share lots, limit-up/down, suspension, ST and board filters.
- Create: `backend/app/services/ashare_constraints.py` - backend equivalent policy and validation result types.
- Create: `backend/tests/test_ashare_constraints.py` - backend unit tests for lots, T+1, limit-up/down, suspension.
- Modify: `frontend/tests/e2e/app.spec.ts` - expand cross-page readiness, freshness, and constraint tests.
- Modify: `frontend/src/pages/Strategy.tsx` - display and use constraint policy before save/run.
- Modify: `frontend/src/pages/Backtest.tsx` - block/warn when data or constraints fail.
- Modify: `frontend/src/pages/Paper.tsx` - run pre-trade checks before starting paper instance.
- Modify: `frontend/src/pages/Monitor.tsx` - show alert states from risk checks.
- Modify: `frontend/src/pages/Dashboard.tsx`, `MarketOverview.tsx`, `SentimentAnalysis.tsx`, `AIStockAnalysis.tsx`, `FactorLibrary.tsx`, `DataCenter.tsx` - add data readiness badges where data is used.
- Modify: `docs/spec.md`, `docs/progress.md`, and active contract docs as each slice lands.

---

### Task 1: Page Readiness Registry

**Files:**
- Create: `frontend/src/lib/pageReadiness.ts`
- Modify: `frontend/tests/e2e/app.spec.ts`

- [ ] **Step 1: Write the failing test**

Add this test to `frontend/tests/e2e/app.spec.ts`:

```ts
import { PRIMARY_PAGE_READINESS } from '../../src/lib/pageReadiness';

test('primary page readiness registry matches rendered routes', async ({ page }) => {
  await loginAsAdmin(page);
  await page.setViewportSize({ width: 1440, height: 960 });

  for (const item of PRIMARY_PAGE_READINESS) {
    await page.goto(item.path);
    await expect(page.getByTestId('stockpro-ai-topbar').getByRole('heading', { name: item.title })).toBeVisible();
    for (const anchor of item.requiredAnchors) {
      await expect(page.getByText(anchor).first(), `${item.path} missing ${anchor}`).toBeVisible();
    }
  }
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd frontend
npm run test:e2e:mock -- --grep "primary page readiness registry"
```

Expected: FAIL because `frontend/src/lib/pageReadiness.ts` does not exist.

- [ ] **Step 3: Create the registry**

Create `frontend/src/lib/pageReadiness.ts`:

```ts
export type PageReadiness = {
  path: string;
  title: string;
  requiredAnchors: string[];
  domain: 'research' | 'strategy' | 'execution' | 'admin';
};

export const PRIMARY_PAGE_READINESS: PageReadiness[] = [
  { path: '/', title: '实时大盘', domain: 'research', requiredAnchors: ['市场指数', '短线指标', '热门板块'] },
  { path: '/market', title: '市场概览', domain: 'research', requiredAnchors: ['行情终端', 'K线图表', '个股分析'] },
  { path: '/research/overview', title: '市场概览', domain: 'research', requiredAnchors: ['市场概览与分析', '热门概念板块', '连板梯队'] },
  { path: '/sentiment', title: '市场情绪', domain: 'research', requiredAnchors: ['市场情绪指数', '上涨家数', '板块资金流向'] },
  { path: '/news', title: '消息中心', domain: 'research', requiredAnchors: ['7x24 实时快讯', '异动 / 并购重组 / 利好 / 利空'] },
  { path: '/ai', title: '智能选股', domain: 'research', requiredAnchors: ['AI 智能分析', '技术面、基本面、消息面'] },
  { path: '/factors', title: '因子研究', domain: 'research', requiredAnchors: ['因子总数', '因子定义', '因子排名'] },
  { path: '/calendar', title: '交易日历', domain: 'research', requiredAnchors: ['交易日历', '近期', '本月'] },
  { path: '/strategy', title: '策略开发', domain: 'strategy', requiredAnchors: ['策略中心', 'A股策略约束', '100股整数手'] },
  { path: '/backtest', title: '回测中心', domain: 'strategy', requiredAnchors: ['回测实例控制台', 'A股回测约束', '涨跌停 / 停牌'] },
  { path: '/review', title: '复盘中心', domain: 'research', requiredAnchors: ['今日盘面复盘', '板块轮动', '连板梯队'] },
  { path: '/paper', title: '模拟/实盘交易', domain: 'execution', requiredAnchors: ['策略实例控制台', '实盘前置约束', 'T+1 / 100股'] },
  { path: '/monitor', title: '运行风控', domain: 'execution', requiredAnchors: ['监控中心', '运行风控检查', '涨跌停风险'] },
  { path: '/data', title: '管理后台', domain: 'admin', requiredAnchors: ['数据管理中心', '同步覆盖矩阵', 'A股数据维护面板'] },
  { path: '/data/processing', title: '管理后台', domain: 'admin', requiredAnchors: ['数据资产', '生产任务', '质量治理'] },
];
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd frontend
npm run test:e2e:mock -- --grep "primary page readiness registry"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/pageReadiness.ts frontend/tests/e2e/app.spec.ts
git commit -m "test: centralize primary page readiness coverage"
```

---

### Task 2: Data Readiness Badge

**Files:**
- Create: `frontend/src/components/DataReadinessBadge.tsx`
- Modify: `frontend/src/pages/Dashboard.tsx`
- Modify: `frontend/src/pages/MarketOverview.tsx`
- Modify: `frontend/src/pages/SentimentAnalysis.tsx`
- Modify: `frontend/src/pages/AIStockAnalysis.tsx`
- Modify: `frontend/tests/e2e/app.spec.ts`

- [ ] **Step 1: Write the failing test**

Add assertions to the cross-page readiness test:

```ts
const freshnessPages = ['/', '/research/overview', '/sentiment', '/ai'];
for (const path of freshnessPages) {
  await page.goto(path);
  await expect(page.getByText('数据状态').first(), `${path} missing 数据状态`).toBeVisible();
}
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd frontend
npm run test:e2e:mock -- --grep "数据状态"
```

Expected: FAIL because most pages do not render a shared `数据状态` badge.

- [ ] **Step 3: Create the component**

Create `frontend/src/components/DataReadinessBadge.tsx`:

```tsx
type DataReadinessBadgeProps = {
  source: string;
  updatedAt?: string | null;
  status?: 'fresh' | 'stale' | 'empty' | 'blocked';
  issue?: string;
};

const statusText = {
  fresh: '可用',
  stale: '需刷新',
  empty: '暂无数据',
  blocked: '阻塞',
};

export function DataReadinessBadge({ source, updatedAt, status = 'fresh', issue }: DataReadinessBadgeProps) {
  return (
    <div className="inline-flex min-w-0 items-center gap-2 rounded-lg border border-crypto-border bg-crypto-card px-3 py-1.5 text-xs text-slate-400">
      <span className="font-black text-slate-300">数据状态</span>
      <span>{source}</span>
      <span className="text-slate-600">/</span>
      <span>{statusText[status]}</span>
      {updatedAt ? <span className="truncate text-slate-500">{updatedAt}</span> : null}
      {issue ? <span className="truncate text-amber-300">{issue}</span> : null}
    </div>
  );
}
```

- [ ] **Step 4: Wire the component into pages**

Add this import to each touched page:

```ts
import { DataReadinessBadge } from '../components/DataReadinessBadge';
```

Render examples:

```tsx
<DataReadinessBadge source="market_indices_realtime" updatedAt={overview?.last_update} />
<DataReadinessBadge source="daily_concept_sectors" status={hotConcepts.length ? 'fresh' : 'empty'} />
<DataReadinessBadge source="ai_analysis_inputs" status={result ? 'fresh' : 'empty'} issue={!result ? '等待输入股票' : undefined} />
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```bash
cd frontend
npm run test:e2e:mock -- --grep "primary pages expose|数据状态"
npm run check
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DataReadinessBadge.tsx frontend/src/pages frontend/tests/e2e/app.spec.ts
git commit -m "feat: show data readiness across research pages"
```

---

### Task 3: Shared A-Share Constraint Policy

**Files:**
- Create: `frontend/src/lib/ashareConstraints.ts`
- Create: `frontend/tests/e2e/ashare-constraints.spec.ts`
- Create: `backend/app/services/ashare_constraints.py`
- Create: `backend/tests/test_ashare_constraints.py`

- [ ] **Step 1: Write frontend failing tests**

Create `frontend/tests/e2e/ashare-constraints.spec.ts`:

```ts
import { expect, test } from '@playwright/test';
import { normalizeAshareOrder, validateAshareTrade } from '../../src/lib/ashareConstraints';

test.describe('ashareConstraints', () => {
  test('rounds buy quantity down to 100-share lots', () => {
    expect(normalizeAshareOrder({ side: 'buy', quantity: 235 }).quantity).toBe(200);
  });

  test('blocks same-day sell for T+1 restricted position', () => {
    const result = validateAshareTrade({
      side: 'sell',
      quantity: 100,
      availableToday: 0,
      isSuspended: false,
      atLimitPrice: false,
    });
    expect(result.ok).toBe(false);
    expect(result.reasons).toContain('T+1持仓不可卖出');
  });
});
```

- [ ] **Step 2: Run frontend test to verify it fails**

Run:

```bash
cd frontend
npx playwright test tests/e2e/ashare-constraints.spec.ts
```

Expected: FAIL because `ashareConstraints.ts` does not exist.

- [ ] **Step 3: Implement frontend policy**

Create `frontend/src/lib/ashareConstraints.ts`:

```ts
type OrderInput = {
  side: 'buy' | 'sell';
  quantity: number;
  availableToday?: number;
  isSuspended?: boolean;
  atLimitPrice?: boolean;
};

export function normalizeAshareOrder(input: OrderInput) {
  const lotQuantity = Math.floor(Math.max(0, input.quantity) / 100) * 100;
  return { ...input, quantity: lotQuantity };
}

export function validateAshareTrade(input: OrderInput): { ok: boolean; reasons: string[] } {
  const normalized = normalizeAshareOrder(input);
  const reasons: string[] = [];
  if (normalized.quantity <= 0) reasons.push('委托数量必须不少于100股');
  if (input.isSuspended) reasons.push('停牌标的不可交易');
  if (input.atLimitPrice) reasons.push('涨跌停附近成交风险高');
  if (input.side === 'sell' && (input.availableToday ?? normalized.quantity) < normalized.quantity) {
    reasons.push('T+1持仓不可卖出');
  }
  return { ok: reasons.length === 0, reasons };
}
```

- [ ] **Step 4: Write backend failing tests**

Create `backend/tests/test_ashare_constraints.py`:

```python
import unittest

from app.services.ashare_constraints import validate_ashare_order


class AshareConstraintTests(unittest.TestCase):
    def test_rounds_quantity_to_lot_size(self):
        result = validate_ashare_order(side="buy", quantity=235)
        self.assertEqual(result.normalized_quantity, 200)

    def test_blocks_t1_sell_when_no_available_position(self):
        result = validate_ashare_order(side="sell", quantity=100, available_today=0)
        self.assertFalse(result.ok)
        self.assertIn("T+1持仓不可卖出", result.reasons)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5: Run backend test to verify it fails**

Run:

```bash
cd backend
source venv/bin/activate
python -m unittest tests.test_ashare_constraints
```

Expected: FAIL because `app.services.ashare_constraints` does not exist.

- [ ] **Step 6: Implement backend policy**

Create `backend/app/services/ashare_constraints.py`:

```python
from dataclasses import dataclass, field


@dataclass
class AshareOrderValidation:
    ok: bool
    normalized_quantity: int
    reasons: list[str] = field(default_factory=list)


def validate_ashare_order(
    *,
    side: str,
    quantity: int,
    available_today: int | None = None,
    is_suspended: bool = False,
    at_limit_price: bool = False,
) -> AshareOrderValidation:
    normalized_quantity = max(0, int(quantity)) // 100 * 100
    reasons: list[str] = []
    if normalized_quantity <= 0:
        reasons.append("委托数量必须不少于100股")
    if is_suspended:
        reasons.append("停牌标的不可交易")
    if at_limit_price:
        reasons.append("涨跌停附近成交风险高")
    if side == "sell" and (available_today if available_today is not None else normalized_quantity) < normalized_quantity:
        reasons.append("T+1持仓不可卖出")
    return AshareOrderValidation(ok=not reasons, normalized_quantity=normalized_quantity, reasons=reasons)
```

- [ ] **Step 7: Run tests to verify they pass**

Run:

```bash
cd frontend
npx playwright test tests/e2e/ashare-constraints.spec.ts
cd ../backend
source venv/bin/activate
python -m unittest tests.test_ashare_constraints
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/ashareConstraints.ts frontend/tests/e2e/ashare-constraints.spec.ts backend/app/services/ashare_constraints.py backend/tests/test_ashare_constraints.py
git commit -m "feat: add shared A-share constraint policy"
```

---

### Task 4: Enforce Constraints In Strategy, Backtest, And Paper

**Files:**
- Modify: `frontend/src/pages/Strategy.tsx`
- Modify: `frontend/src/pages/Backtest.tsx`
- Modify: `frontend/src/pages/Paper.tsx`
- Modify: `backend/app/api.py` or active route modules that handle backtest/paper actions
- Modify: `frontend/tests/e2e/app.spec.ts`
- Modify: `backend/tests/test_ashare_constraints.py`

- [ ] **Step 1: Write failing E2E expectations**

Add to `frontend/tests/e2e/app.spec.ts`:

```ts
test('strategy and execution pages surface executable A-share validation', async ({ page }) => {
  await loginAsAdmin(page);

  await page.goto('/strategy');
  await expect(page.getByText('策略校验')).toBeVisible();
  await expect(page.getByText('T+1持仓规则')).toBeVisible();

  await page.goto('/backtest');
  await expect(page.getByText('数据覆盖校验')).toBeVisible();
  await expect(page.getByText('成本模型')).toBeVisible();

  await page.goto('/paper');
  await expect(page.getByText('预交易检查')).toBeVisible();
  await expect(page.getByText('PaperBroker隔离')).toBeVisible();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd frontend
npm run test:e2e:mock -- --grep "executable A-share validation"
```

Expected: FAIL until the pages expose the validation sections.

- [ ] **Step 3: Implement page sections**

Use the policy from Task 3 and render validation summaries:

```tsx
const sampleValidation = validateAshareTrade({
  side: 'buy',
  quantity: 100,
  isSuspended: false,
  atLimitPrice: false,
});
```

Render:

```tsx
<section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
  <h2 className="text-sm font-black text-white">策略校验</h2>
  <div className="mt-2 text-xs text-slate-500">
    {sampleValidation.ok ? '已通过 A股交易制度基础检查' : sampleValidation.reasons.join(' / ')}
  </div>
</section>
```

- [ ] **Step 4: Add backend validation to action paths**

Call `validate_ashare_order()` in the paper/backtest execution path before creating simulated orders. Return a 400 response with `reasons` if validation fails.

```python
validation = validate_ashare_order(side=side, quantity=quantity, available_today=available_today)
if not validation.ok:
    raise HTTPException(status_code=400, detail={"reasons": validation.reasons})
```

- [ ] **Step 5: Run tests**

Run:

```bash
cd frontend
npm run test:e2e:mock -- --grep "executable A-share validation"
cd ../backend
source venv/bin/activate
python -m unittest tests.test_ashare_constraints
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Strategy.tsx frontend/src/pages/Backtest.tsx frontend/src/pages/Paper.tsx backend/app backend/tests frontend/tests/e2e/app.spec.ts
git commit -m "feat: enforce A-share checks in strategy execution flow"
```

---

### Task 5: Research-To-Candidate Handoff

**Files:**
- Create: `frontend/src/lib/researchCandidates.ts`
- Modify: `frontend/src/pages/MarketOverview.tsx`
- Modify: `frontend/src/pages/AIStockAnalysis.tsx`
- Modify: `frontend/src/pages/FactorLibrary.tsx`
- Modify: `frontend/src/pages/Strategy.tsx`
- Modify: `frontend/tests/e2e/app.spec.ts`

- [ ] **Step 1: Write failing E2E handoff test**

Add:

```ts
test('research pages can promote a stock into strategy candidates', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/research/overview');
  await expect(page.getByText('加入候选池').first()).toBeVisible();

  await page.getByText('加入候选池').first().click();
  await page.goto('/strategy');
  await expect(page.getByText('研究候选池')).toBeVisible();
  await expect(page.getByText(/低空经济|浦发银行/).first()).toBeVisible();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd frontend
npm run test:e2e:mock -- --grep "promote a stock"
```

Expected: FAIL because candidate promotion is not implemented.

- [ ] **Step 3: Implement local candidate store**

Create `frontend/src/lib/researchCandidates.ts`:

```ts
export type ResearchCandidate = {
  symbol: string;
  name: string;
  source: 'concept' | 'ai' | 'factor' | 'news';
  reason: string;
  createdAt: string;
};

const KEY = 'stockpro_research_candidates';

export function listResearchCandidates(): ResearchCandidate[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? JSON.parse(raw) as ResearchCandidate[] : [];
  } catch {
    return [];
  }
}

export function addResearchCandidate(candidate: ResearchCandidate) {
  const current = listResearchCandidates();
  const next = [candidate, ...current.filter((item) => item.symbol !== candidate.symbol)].slice(0, 50);
  window.localStorage.setItem(KEY, JSON.stringify(next));
  return next;
}
```

- [ ] **Step 4: Wire add buttons and Strategy view**

In research pages, call:

```tsx
addResearchCandidate({
  symbol: stock.code,
  name: stock.name,
  source: 'concept',
  reason: selectedConcept,
  createdAt: new Date().toISOString(),
});
```

In `Strategy.tsx`, render:

```tsx
<section className="rounded-xl border border-crypto-border bg-crypto-card p-4">
  <h2 className="text-sm font-black text-white">研究候选池</h2>
  {listResearchCandidates().map((item) => (
    <div key={item.symbol} className="mt-2 text-xs text-slate-300">{item.name} · {item.reason}</div>
  ))}
</section>
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```bash
cd frontend
npm run test:e2e:mock -- --grep "promote a stock"
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/researchCandidates.ts frontend/src/pages/MarketOverview.tsx frontend/src/pages/AIStockAnalysis.tsx frontend/src/pages/FactorLibrary.tsx frontend/src/pages/Strategy.tsx frontend/tests/e2e/app.spec.ts
git commit -m "feat: add research candidate handoff"
```

---

### Task 6: Final Verification And Documentation

**Files:**
- Modify: `docs/spec.md`
- Modify: `docs/progress.md`
- Modify: `docs/ashare-research-roadmap.md`
- Modify: `docs/qa/2026-06-26-ashare-page-audit.md`

- [ ] **Step 1: Run full checks**

Run:

```bash
cd frontend
npm run check
npm run lint
npm run test:e2e:mock
cd ..
./scripts/check.sh
```

Expected: all commands pass. Existing lint warnings are acceptable only if they are documented and unchanged.

- [ ] **Step 2: Update spec**

Add this acceptance statement to `docs/spec.md`:

```md
## Page Professionalism Acceptance

Every primary page must expose its role in the A-share workflow, show data readiness for data-driven panels, and either enforce or clearly mark A-share constraints: T+1, 100-share lots, limit-up/down, suspension, ST/universe filtering, cost model, trading sessions, and broker isolation.
```

- [ ] **Step 3: Update progress**

Add:

```md
## Verification Evidence (YYYY-MM-DD)

- `npm run check` from `frontend/` (pass).
- `npm run lint` from `frontend/` (pass, warnings documented).
- `npm run test:e2e:mock` from `frontend/` (pass).
- `./scripts/check.sh` (pass).
```

- [ ] **Step 4: Commit**

```bash
git add docs/spec.md docs/progress.md docs/ashare-research-roadmap.md docs/qa/2026-06-26-ashare-page-audit.md
git commit -m "docs: document A-share research workstation roadmap"
```

---

## Self-Review

- Spec coverage: pages, data readiness, A-share constraints, research handoff, backtest, paper trading, monitor, and docs are covered by Tasks 1-6.
- Placeholder scan: no task relies on a vague future implementation; each task includes concrete file paths, snippets, commands, and expected results.
- Type consistency: `PageReadiness`, `DataReadinessBadge`, `validateAshareTrade`, `validate_ashare_order`, and `ResearchCandidate` names are used consistently across tasks.
