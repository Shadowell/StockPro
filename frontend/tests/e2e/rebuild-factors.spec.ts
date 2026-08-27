import { expect, test } from '@playwright/test'
import { installFinalFixtures } from './rebuild-final-fixtures'
test('factor lab keeps null-safe A-share evidence without page-load mutations', async ({ page }) => { await installFinalFixtures(page); const writes:string[]=[]; page.on('request',r=>{if(['POST','PUT','PATCH','DELETE'].includes(r.method()))writes.push(r.url())}); await page.goto('/factorlab'); await expect(page.getByRole('heading',{name:'因子库与实验'})).toBeVisible(); await expect(page.getByText(/USDT|OKX|资金费率/)).toHaveCount(0); expect(writes).toEqual([]) })

test('factor lab creates a sealed-evidence task and keeps rejected trial gates', async ({ page }) => {
  await installFinalFixtures(page)
  let requestPayload: Record<string, unknown> | undefined
  const task = { task_id:'task-1',status:'completed',mode:'manual',exchange:'CN',market_type:'stock',symbols:['600519.SH','000001.SZ'],timeframe:'1d',start_ms:1,end_ms:2,factor_instance_ids:['fv:1'],manual_combination_count:1,provider_key:'',model:'',reasoning_effort:'',speed_mode:'',horizon_bars:6,base_cost_bps:20,stress_cost_bps:40,n_splits:5,max_candidates:200,max_runtime_sec:7200,max_no_improvement:50,max_combination_leaves:4,target_accepted_candidates:1,dataset_snapshot_id:'factor-snapshot:1',trial_cursor:1,best_trial_id:null,stop_reason:'hard_gate_failure: fold_count',archived_at:null,created_at:'2026-08-28T00:00:00+08:00',updated_at:'2026-08-28T00:00:00+08:00',orders_created:0,paper_mutated:false }
  const trial = { trial_id:'trial-1',task_id:'task-1',ordinal:1,semantic_hash:'hash',model_type:'equal_weight',feature_ids:['fv:1'],parameters:{source:'sealed_factor_snapshot'},status:'rejected',metrics:{coverage:0,fold_count:0,accepted:false},hard_gate_failures:['coverage','fold_count','cost_return_non_positive'],created_at:'2026-08-28T00:00:00+08:00',orders_created:0,paper_mutated:false }
  await page.route('**/api/v2/factorlab/research/tasks**', async route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() === 'POST' && path.endsWith('/research/tasks')) {
      requestPayload = route.request().postDataJSON() as Record<string, unknown>
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(task)})
    } else if (path.endsWith('/task-1/trials')) {
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify([trial])})
    } else {
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify([])})
    }
  })
  await page.goto('/factorlab')
  await page.getByRole('button',{name:'手动组合'}).click()
  await page.getByRole('button',{name:'启动研究',exact:true}).click()
  await expect(page.getByText('OOS fold 不足')).toBeVisible()
  await expect(page.getByText('20bps 后收益非正')).toBeVisible()
  expect(requestPayload?.market_type).toBe('stock')
  expect(requestPayload?.factor_instance_ids).toEqual(['fv:1'])
})
