// 生成 README 展示素材：8 张截图（docs/assets/showcase/*.png）与 2 组 GIF 帧。
// 用本机已完成的真实报告（DeepSeek deepseek-flash 运行结果）：宁德时代 c6529fb2（首次研究一次跑完）、紫金矿业 0515255b（含追问与续跑）。
// 先启动 scripts/start-app.ps1；用法：node scripts/capture-showcase.mjs docs/assets/showcase <临时帧目录>，再运行 build-showcase-gifs.py。
// Playwright 路径同其他网页检查脚本，可用 PLAYWRIGHT_MODULE_PATH / CHROME_PATH 覆盖。
import { createRequire } from 'node:module'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'))
const [out, frames] = process.argv.slice(2)
const CATL = 'c6529fb2-db48-4834-a092-73cad009a4f8', ZIJIN = '0515255b-74aa-424e-abbf-7ed1a7d57a8d'
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1.5 })
const page = await context.newPage()
const open = async (task) => { await page.goto('http://127.0.0.1:5173/?task=' + task); await page.waitForTimeout(5000) }
const button = (name) => page.getByRole('button', { name }).first()
const ensure = async (shown, hidden) => { if (await button(hidden).isVisible().catch(() => false)) { await button(hidden).click(); await page.waitForTimeout(800) } }
const shot = (name) => page.screenshot({ path: path.join(out, name) })

// 01 工作台：设置 + 报告 + 对话三栏（紫金矿业）
await open(ZIJIN)
await ensure(null, /展开研究设置/)
await shot('01-workbench.png')
// 09 预兆：设置栏的四个预兆 + 报告里的预兆覆盖（两张局部图，由 build-showcase-gifs.py 拼成 09-omens.png）
if (await button(/展开研究设置/).isVisible().catch(() => false)) { await button(/展开研究设置/).click(); await page.waitForTimeout(800) }
if (!(await page.getByText('研究预兆').first().isVisible().catch(() => false))) { await page.getByText(/研究偏好与预兆/).first().click(); await page.waitForTimeout(1000) }
const omenGroup = page.getByText('研究预兆').filter({ hasText: '可多选' }).first().locator('xpath=ancestor::fieldset[1]')
await omenGroup.evaluate((el) => el.scrollIntoView({ block: 'center' })); await page.waitForTimeout(600)
await omenGroup.screenshot({ path: path.join(frames || out, 'omen-picker.png') })
await ensure(null, /收起研究设置/)
const coverage = page.locator('summary', { hasText: '研究预兆覆盖' }).first()
await coverage.evaluate((el) => { el.parentElement.open = true; el.parentElement.scrollIntoView({ block: 'start' }) }); await page.waitForTimeout(800)
await coverage.locator('xpath=..').screenshot({ path: path.join(frames || out, 'omen-coverage.png') })
await coverage.evaluate((el) => { el.parentElement.open = false })
await page.evaluate(() => window.scrollTo(0, 0))
// 05 对话：放大对话，显示真实补查回答与“只读到部分正文”的如实说明
await ensure(null, /收起研究设置/)
await button(/放大对话/).click(); await page.waitForTimeout(1200)
await shot('05-followup-chat.png')
await button(/还原|缩小|退出放大|放大对话/).click().catch(() => {}); await page.waitForTimeout(800)

// 宁德时代：一次跑完的真实报告
await open(CATL)
await ensure(null, /收起研究设置/)
await shot('02-report.png')
// 07 记忆与偏好
await ensure(null, /展开研究设置/)
const memory = page.locator('section[aria-label="研究记忆与偏好"]')
await memory.locator('summary, button').first().click().catch(() => {}); await page.waitForTimeout(1000)
await memory.evaluate((el) => { let p = el.parentElement; while (p && !(p.scrollHeight > p.clientHeight + 10)) p = p.parentElement; (p || document.scrollingElement).scrollBy(0, el.getBoundingClientRect().top - 60) }); await page.waitForTimeout(800)
await shot('07-memory.png')
await ensure(null, /收起研究设置/)
// 在报告的滚动容器里把元素滚到距顶部 above 像素处
const scrollTo = async (locator, above = 100) => { await locator.scrollIntoViewIfNeeded(); await locator.evaluate((el, above) => {
  let p = el.parentElement; while (p && !(p.scrollHeight > p.clientHeight + 10 && getComputedStyle(p).overflowY !== 'visible')) p = p.parentElement
  const box = el.getBoundingClientRect(); (p || document.scrollingElement).scrollBy(0, box.top - above) }, above); await page.waitForTimeout(800) }
await scrollTo(page.locator('section[aria-label="财务表图"]').first(), 95)
await shot('03-financial-charts.png')
await scrollTo(page.getByText('核对产品收入金额与占比').first(), 520)
await shot('04-business-mix.png')
await scrollTo(page.getByRole('heading', { name: '本次资料来源' }), 95)
await page.screenshot({ path: path.join(out, '08-sources.png'), clip: { x: 0, y: 0, width: 1440, height: 593 } })  // 只要来源列表
// 06 过程记录：完整工具调用时间线
await button(/过程记录/).click(); await page.waitForTimeout(1200)
await page.getByText('查看完整研究过程与工具记录').first().click().catch(() => {}); await page.waitForTimeout(2000)
await shot('06-process.png')
await button(/关闭/).click(); await page.waitForTimeout(600)

  // ---- GIF 帧（1 倍像素，鼠标滚轮滚动，像真人浏览）----
  if (frames) {
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage()
  const b = (name) => page.getByRole('button', { name }).first()
  let n = 0, dir = 'a'
  const frame = async (hold = 1) => { for (let i = 0; i < hold; i++) await page.screenshot({ path: path.join(frames, dir, String(n++).padStart(4, '0') + '.png') }) }
  const wheel = async (x, y, steps, dy) => { await page.mouse.move(x, y); for (let i = 0; i < steps; i++) { await page.mouse.wheel(0, dy); await page.waitForTimeout(180); await frame() } }
  for (const d of ['a', 'b']) { await fs.rm(path.join(frames, d), { recursive: true, force: true }); await fs.mkdir(path.join(frames, d), { recursive: true }) }

  // A：宁德时代报告——标题与结论 → 财务图（来源 AKShare）→ 年度/上半年切换 → 业务结构与毛利率
  await page.goto('http://127.0.0.1:5173/?task=c6529fb2-db48-4834-a092-73cad009a4f8'); await page.waitForTimeout(5000)
  if (await b(/收起研究设置/).isVisible().catch(() => false)) { await b(/收起研究设置/).click(); await page.waitForTimeout(600) }
  await frame(8)
  await wheel(640, 500, 10, 220)
  const fin = page.locator('section[aria-label="财务表图"]').first()
  await fin.evaluate((el) => el.scrollIntoView({ block: 'start' })); await page.waitForTimeout(600); await frame(6)
  await wheel(640, 500, 4, 160)
  await b('上半年').click().catch(() => {}); await page.waitForTimeout(800); await frame(7)
  await b('年度').click().catch(() => {}); await page.waitForTimeout(800); await frame(4)
  const biz = page.getByText('核对产品收入金额与占比').first()
  await biz.evaluate((el) => el.scrollIntoView({ block: 'center' })); await page.waitForTimeout(600); await frame(3)
  await wheel(640, 500, 4, -150); await frame(4)
  await wheel(640, 500, 4, 150); await frame(8)

  // B：紫金矿业——报告+对话 → 放大对话并滚动阅读补查回答 → 过程记录（7 次运行、255 次调用）→ 版本与对话分支
  n = 0; dir = 'b'
  await page.goto('http://127.0.0.1:5173/?task=0515255b-74aa-424e-abbf-7ed1a7d57a8d'); await page.waitForTimeout(5000)
  await frame(8)
  await b(/放大对话/).click(); await page.waitForTimeout(1000); await frame(5)
  await wheel(640, 450, 8, 200); await frame(4)
  await b(/并排查看/).click().catch(() => {}); await page.waitForTimeout(800); await frame(3)
  await b(/过程记录/).click(); await page.waitForTimeout(1000); await frame(3)
  await page.getByText('查看完整研究过程与工具记录').first().click().catch(() => {}); await page.waitForTimeout(1500); await frame(6)
  await wheel(640, 450, 6, 200); await frame(4)
  await b(/关闭/).click(); await page.waitForTimeout(600)
  await b(/选项/).click(); await page.waitForTimeout(800); await frame(8)
}
await browser.close()
