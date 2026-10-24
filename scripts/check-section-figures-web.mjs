// 实际已完成研究的浏览器检查；不会创建付费任务。
import assert from 'node:assert/strict'
import {createRequire} from 'node:module'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
const require=createRequire(import.meta.url)
const {chromium}=require(path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'))
const root=path.resolve(import.meta.dirname,'..'), output=path.join(root,'.runtime/qa/section-figures')
await fs.mkdir(output,{recursive:true})
const job=JSON.parse(await fs.readFile(path.join(root,'storage/runs/section-figures-live.json'),'utf8'))
assert.equal(job.status,'completed')
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true})
const page=await browser.newPage({viewport:{width:1440,height:1050}})
const errors=[],posts=[],checks=[]
page.on('pageerror',(e)=>errors.push(e.message))
page.on('request',(r)=>{if(r.method()==='POST')posts.push(r.url())})
const url=`http://127.0.0.1:5173/?task=${job.taskId}`
try {
  await page.goto(url)
  await page.getByText('真实研究 · 已完成',{exact:true}).waitFor({timeout:20000})
  assert.equal(posts.length,0)
  await page.locator('.method-usage summary').click()
  assert.ok(await page.locator('.method-usage').textContent().then((t)=>t.includes('已结合方法计划复核报告')))
  assert.ok(job.report.methodUsage.references.some((r)=>r.characters>30000))
  checks.push('related original methods fully processed, adjustable plan and actual report review recorded')
  assert.ok(await page.locator('.business-chart').count()>=2)
  assert.ok(await page.locator('.financial-chart').count()>=6)
  assert.ok(await page.locator('.report-section:has(.section-visuals figure)').count()>=4)
  assert.ok(await page.locator('.evidence-diagram').count()>0)
  checks.push('model-chosen figures distributed across business, financial and qualitative analysis')
  const business=page.locator('.business-figures').first()
  await business.locator('details').first().locator('summary').click()
  assert.ok(await business.locator('.business-table').first().textContent().then((t)=>t.includes('97.95%') || t.includes('90.58%')))
  assert.ok(await business.locator('a[href*="#page="]').count()>1)
  await business.screenshot({path:path.join(output,'business-annual.png')})
  const half=business.getByRole('button',{name:'上半年',exact:true})
  if(await half.count()) { await half.click();assert.ok(await business.textContent().then((t)=>t.includes('2026上半年')));await business.screenshot({path:path.join(output,'business-half.png')}) }
  checks.push('business proportions use actual total, original source links and independent periods')
  const research=page.locator('.report-section').filter({has:page.locator('figure[aria-label*="研发"]')}).first()
  assert.ok(await research.count()>0)
  await research.screenshot({path:path.join(output,'research-investment.png')})
  checks.push('research investment figures exist in an analytical section')
  await page.getByRole('button',{name:'实际价格（元）',exact:true}).click()
  await page.getByRole('slider',{name:'选择交易日'}).press('ArrowLeft')
  checks.push('existing market interaction retained')
  for(const width of [1440,768,375,320]) {
    await page.setViewportSize({width,height:1050})
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`overflow at ${width}`)
    await business.scrollIntoViewIfNeeded()
    await page.screenshot({path:path.join(output,`business-${width}.png`)})
  }
  checks.push('desktop and three smaller widths without page overflow')
  const broken=structuredClone(job);broken.report.businessData.datasets[0].rows[0].items[0].share=999
  await page.route(`**/api/research/jobs/${job.taskId}`,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(broken)}))
  await page.goto(url);await page.getByRole('alert').waitFor()
  assert.equal(await page.locator('.business-chart').count(),0)
  checks.push('invalid proportions rejected before rendering')
  await page.unrouteAll()
  const unsafe=structuredClone(job),diagram=unsafe.report.figurePlan.find((f)=>f.diagram).diagram
  diagram.nodes[0].label='<img src=x onerror=alert(1)>'
  await page.route(`**/api/research/jobs/${job.taskId}`,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(unsafe)}))
  await page.goto(url);await page.getByText('真实研究 · 已完成',{exact:true}).waitFor()
  assert.equal(await page.locator('.evidence-diagram img').count(),0)
  assert.ok(await page.locator('.evidence-diagram').allTextContents().then((texts)=>texts.join('').includes('<img src=x')))
  checks.push('model diagram text escaped, no arbitrary HTML or drawing code')
  await page.unrouteAll()
  const old=JSON.parse(await fs.readFile(path.join(root,'storage/runs/financial-report-live.json'),'utf8'))
  await page.route(`**/api/research/jobs/${old.taskId}`,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(old)}))
  await page.goto(`http://127.0.0.1:5173/?task=${old.taskId}`);await page.getByText('真实研究 · 已完成',{exact:true}).waitFor()
  assert.equal(await page.locator('.financial-chart').count(),4)
  checks.push('previous report without new fields remains readable')
  await page.unrouteAll()
  await page.goto('http://127.0.0.1:5173/')
  await page.getByRole('radio',{name:'演示报告',exact:true}).check();await page.getByRole('button',{name:'填入示例'}).click();await page.getByRole('button',{name:'生成演示报告'}).click()
  await page.getByText('演示报告 · MOCK',{exact:true}).waitFor()
  assert.deepEqual(errors,[])
  checks.push('actual mock roundtrip retained and no browser exceptions')
  console.log(JSON.stringify({passed:checks.length,checks,taskId:job.taskId},null,2))
} finally {
  await fs.writeFile(path.join(output,'summary.json'),JSON.stringify({passed:checks.length,checks,errors,taskId:job.taskId},null,2))
  await browser.close()
}
