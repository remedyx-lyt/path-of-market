// Chrome实际读取已完成研究；不创建付费任务，故障场景使用隔离响应。
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import fs from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'

const require=createRequire(import.meta.url)
const {chromium}=require(process.env.PLAYWRIGHT_MODULE_PATH || path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'))
const root=path.resolve(import.meta.dirname,'..')
const output=path.join(root,'.runtime/qa/financial-research')
await fs.mkdir(output,{recursive:true})
const job=JSON.parse(await fs.readFile(path.join(root,'storage/runs/financial-report-live.json'),'utf8'))
assert.equal(job.status,'completed')
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true})
const page=await browser.newPage({viewport:{width:1440,height:1100}})
const errors=[], posts=[], checks=[]
page.on('pageerror',(e)=>errors.push(e.message))
page.on('request',(r)=>{if(r.method()==='POST')posts.push(r.url())})
const url=`http://127.0.0.1:5173/?task=${job.taskId}`
try {
  await page.goto(url)
  await page.getByText('真实研究 · 已完成',{exact:true}).waitFor({timeout:20000})
  assert.equal(await page.locator('.financial-chart').count(),4)
  assert.equal(posts.length,0)
  assert.ok(await page.locator('.report-skill').textContent().then((t)=>t.includes('anthropics/financial-services')))
  checks.push('real completed report, loaded Skill and four annual chart types without new model task')
  assert.ok(await page.locator('.financial-table').textContent().then((t)=>t.includes('382.40') && t.includes('122.64%') && t.includes('60.25%')))
  assert.ok(await page.locator('.financial-table a').count()>10)
  await page.getByRole('button',{name:'上半年',exact:true}).click()
  assert.equal(await page.locator('.financial-chart').count(),4)
  assert.ok(await page.locator('.financial-table').textContent().then((t)=>t.includes('417.78') && t.includes('182.49%') && t.includes('-44.08%') && !t.includes('2024年度')))
  await page.locator('.financial-section').screenshot({path:path.join(output,'half-year-charts.png')})
  checks.push('same-period half-year comparison, negative cash-flow growth and clickable source cells')
  await page.getByRole('button',{name:'年度',exact:true}).click()
  await page.locator('.financial-section').screenshot({path:path.join(output,'annual-charts.png')})
  const bounds=await page.locator('.research-preview--agent').boundingBox()
  assert.ok(bounds.width>600)
  assert.ok(await page.locator('.report-nav a').count()>5)
  assert.ok(await page.locator('.report-prose p').count()>10)
  checks.push('wider white report, section navigation and real paragraph structure')
  await page.locator('.visual-readings summary').click()
  assert.ok(await page.locator('.visual-readings').textContent().then((t)=>t.includes('PDF第8页') && t.includes('只检查以上页面')))
  checks.push('visual evidence is explicit and separate from full-text coverage')
  await page.getByRole('button',{name:'实际价格（元）'}).click()
  await page.getByRole('slider',{name:'选择交易日'}).press('ArrowLeft')
  assert.ok(await page.locator('.chart-cursor').textContent().then((t)=>t.includes('实际价格')))
  checks.push('original market chart modes and cursor remain functional')
  for(const width of [1440,768,375,320]) {
    await page.setViewportSize({width,height:1000})
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`overflow at ${width}`)
    await page.screenshot({path:path.join(output,`report-${width}.png`),fullPage:width>=768})
  }
  checks.push('four widths without page overflow; data table scroll stays contained')
  const broken=structuredClone(job);broken.report.financialData.datasets[0].rows[0].values.revenue='invalid'
  await page.route(`**/api/research/jobs/${job.taskId}`,route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(broken)}))
  await page.goto(url)
  await page.getByRole('alert').waitFor()
  assert.equal(await page.locator('.financial-chart').count(),0)
  checks.push('invalid numeric dataset rejected before plotting')
  await page.unrouteAll()
  await page.goto('http://127.0.0.1:5173/')
  await page.getByRole('radio',{name:'演示报告',exact:true}).check()
  await page.getByRole('button',{name:'填入示例'}).click()
  await page.getByRole('button',{name:'生成演示报告'}).click()
  await page.getByText('演示报告 · MOCK',{exact:true}).waitFor()
  checks.push('original actual Java/Python mock report still works')
  assert.deepEqual(errors,[])
  checks.push('no browser exceptions')
  console.log(JSON.stringify({passed:checks.length,checks,taskId:job.taskId},null,2))
} finally {
  await fs.writeFile(path.join(output,'summary.json'),JSON.stringify({passed:checks.length,checks,errors,taskId:job.taskId},null,2))
  await browser.close()
}
