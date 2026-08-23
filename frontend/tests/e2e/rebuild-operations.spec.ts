import { expect, test } from '@playwright/test'

test('signal order trade alert and review keep one Paper lineage', async ({ page }) => {
  await page.route('**/api/auth/me',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({auth_enabled:false,authenticated:true,role:'admin',permissions:['admin']})}))
  const paperId='paper-lineage-1';const signal={id:'signal-1',paper_instance_id:paperId,strategy_version_id:'strategy-1',symbol:'SZ_000001',signal_type:'buy',status:'new',signal_time:'2026-08-21T10:00:00Z',evidence:{}}
  await page.route('**/api/signals?*',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({items:[signal],total:1,scope:'audit'})}))
  await page.route('**/api/watch/alerts*',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({items:[],total:0})}))
  await page.route('**/api/monitor/summary*',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({overall_status:'warning',services:[],data:{},strategy_health:[{id:paperId,name:'A股模拟',lifecycle_status:'running',health_state:'stale'}],active_alerts:[],notifications:[],source_label:'PostgreSQL',source_updated_at:null})}))
  await page.goto('/signals')
  const id=await page.getByTestId('signal-row').getAttribute('data-paper-instance-id')
  expect(id).toBe(paperId)
  await page.getByTestId('signal-row').click()
  await expect(page.getByText(paperId).first()).toBeVisible()
  await page.goto('/monitor')
  await expect(page.locator(`[data-paper-instance-id="${paperId}"]`)).toBeVisible()
  await expect(page.locator(`[data-paper-instance-id="${paperId}"]`)).toContainText('running')
  await expect(page.locator(`[data-paper-instance-id="${paperId}"]`)).toContainText('stale')
})
