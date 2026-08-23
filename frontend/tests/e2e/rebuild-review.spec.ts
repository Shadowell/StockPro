import { expect, test } from '@playwright/test'

test('daily review reads sealed A-share evidence without assembling', async ({ page }) => {
  await page.route('**/api/auth/me', route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({auth_enabled:false,authenticated:true,role:'admin',permissions:['admin']})}))
  await page.route('**/api/review/dates*', route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({items:['2025-01-02'],total:1})}))
  await page.route('**/api/review?*', route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({items:[{id:'review-1',trade_date:'2025-01-02',status:'sealed'}],total:1})}))
  await page.route('**/api/review/2025-01-02', route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({review:{id:'review-1',trade_date:'2025-01-02',status:'sealed',summary:'市场震荡',next_day_plan:'控制仓位'},trade_date:'2025-01-02',status:'sealed',items:[{id:1,occurred_at:'2025-01-02T15:00:00Z',category:'strategy',title:'策略信号',source_object_type:'strategy_signal',source_object_id:'signal-1'}],metrics:[{id:1,metric_code:'paper_nav:paper-1',metric_value:1.05,unit:'ratio'}],counts:{strategy:1},source_manifest_hash:'hash-1',writes_performed:false})}))
  const writes:string[]=[];page.on('request',request=>{if(['POST','PUT','DELETE'].includes(request.method()))writes.push(request.url())})
  await page.goto('/review')
  await expect(page.getByRole('heading',{name:'交易日复盘'})).toBeVisible()
  await expect(page.getByRole('heading',{name:'复盘结论'})).toBeVisible()
  await expect(page.getByRole('heading',{name:'证据时间线'})).toBeVisible()
  await expect(page.getByText('sealed',{exact:true}).first()).toBeVisible()
  expect(writes).toEqual([])
  await expect(page.getByText(/小时级|永续|USDT/)).toHaveCount(0)
})
