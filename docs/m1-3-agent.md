# M1-3：动态研究循环与股票行情

交接更新：2026-10-24（Australia/Sydney），示例研究截止日为 2026-10-23。沿用 React → Java → Python，不替换原有产品架构。本轮按用户要求用中际旭创作真实案例，提前实现一部分行情和表图能力；M2 的会话、侧栏聊天、长报告与通用表图仍待做。

## 这一步做出来什么

用户输入公司、问题和截止日，模型选择查报告、读报告、查行情；程序执行并把结果交回模型，模型据此继续调查或提交报告。网页能看到进度、来源、PDF 页码、阅读覆盖、工具动作、价格曲线和计算表。最终还有一次报告与资料范围、行情口径的一致性复核。

“模型决定下一步”属于 Agent 循环；下载、连续分批阅读、指标计算等有确定规则的部分属于工具内部工作流，两者结合。没有把固定顺序的假动作包装成模型决策，也没有输出模型私有推理。

## 模型能调用的三个工具

| 工具 | 作用 | 主要代码 |
| --- | --- | --- |
| `find_documents` | 根据公司、会计年度、截止日期找完整年报/半年报/一季报/三季报；默认补查截止日当年的最新已披露定期报告 | `apps/agent/app/services/agent_runner.py` 的 `dispatch`；`app/tools/cninfo.py` |
| `read_document` | `full` 默认：自动下载、解析并连续分批读完可提取文字；完成后可用 `page` / `search` 复查 | `agent_runner.py` 的 `read`；`app/tools/documents.py` |
| `get_market_data` | 查询沪深股票日线、不复权价格与同源后复权序列，返回程序计算的变化/回撤/波动/月度数据 | `app/tools/market.py`；`app/tools/registry.py` |

三个模型声明在 `agent_runner.py:declarations`。底层 `registry.py:TOOLS` 共有七个可复用工具：原来的 `resolve_company`、`find_documents`、`fetch_document`、`search_document`、`read_document`、`read_document_batch`，新增 `get_market_data`。

两层同名 `read_document` 的参数不同：模型看到的是完整阅读入口；开发 HTTP 工具入口仍是底层单页原文读取。下载/分页等底层步骤由 Runner 组合，避免让主模型每次自己拼接游标。

Pi 的四个编码工具里，`bash` 能调用很多系统程序；“四个工具”不等于只有四种能力。我们的模型入口现在是三个，也不必为了凑数量添加没有用途的工具。没有向财经网页开放任意 Shell 执行。

## 一次研究如何运行

```text
网页 POST /api/research/jobs
  → Java 转发到 Python POST /research/jobs，立即返回 202 和任务 ID
  → AgentRunner 组装规则、任务、工具定义与历史结果
  → 模型返回 assistant.tool_calls
  → 参数校验 → 工具执行 → role=tool + 原始 tool_call_id 回传
  → 模型补查/阅读/查询行情，或提交结构化报告
  → 来源/覆盖/当前年度资料校验 → 报告一致性复核 → 返回完成/部分结果
网页定期 GET 任务状态 → 展示实际进度与结果
```

模型可根据反馈调整动作；未知工具、参数错误和重复动作返回可理解的错误。每次工具请求保留供应商原始 ID，与结果正确配对；截断的工具参数不执行。事件有 `id`、`parentId`、`sessionId`、`runId`，目前是进程内线性事件，尚无分支操作。

Java 任务接口使用短请求与完整正文等待上限，不用一个 HTTP 请求阻塞整场研究。浏览器只请求 Java；显式“取消并清空”发 DELETE，关闭页面/中止浏览器等待本身不取消后台研究。已发出的供应商请求可能仍完成并计费。

任务链接 `/?task=<UUID>` 可以重新查看同一 Python 进程里保存的结果，不重复调用模型。进程最多保留八个任务、同时运行一个；重启或旧任务被淘汰后链接不可恢复。它不是 M2 的持久化会话。

## 完整阅读与缓存

1. 程序记录发现、下载、提取文字、返回原文与模型处理的范围。
2. `full` 从第一页连续读，单批最多 20 页/26,000 字符，通过游标继续，长页也不会漏段。
3. 每批原文交给模型生成带页码的摘要、事实和缺口；格式/引用校验失败可修正一次，成功后才增加处理覆盖。
4. 主研究循环收到每批的有来源要点，再根据需要回查原文；并非把三份 PDF 一次性塞进主上下文。
5. 阅读缓存按 PDF 哈希、批次原文、研究问题、提示词和模型名生成键，保留原运行 ID/处理时间。复用时保留来源记录，不将缓存读取冒充新的逐页模型调用。

缓存路径为忽略目录 `storage/documents/reading-notes/`；它是派生资料缓存，不是用户画像、会话记忆或 JSONL 历史。文本覆盖完成也不代表图像、扫描页和复杂表格被视觉理解；当前没有 OCR/多模态读图。空文本页会阻止“全文文字完成”的声明。

默认 `includeCurrentPeriod=true` 时，发现资料后自动补查截止日当年的一季报/半年报/三季报，以实际已披露最新一份为必读条件；不能只读前两份年报就忽略当前年度。历史专题可通过 API 显式关闭这个要求。不是要求读完全部搜索候选，未选读与未找到必须区分。

## 行情和表图口径

- `MarketProvider` 优先东方财富，失败尝试腾讯。每次使用同一供应商的不复权与后复权数据，并要求交易日集合一致，不跨源拼接计算。
- 实际价格和 OHLC 使用不复权字段，单位人民币元；图表默认后复权收盘归一到起点 100，可切换实际价格，日期滑块能查看每日数值。
- 区间变化：`(末后复权收盘 / 初后复权收盘 - 1) × 100%`。
- 最大收盘回撤：`min(当日后复权收盘 / 此前最高后复权收盘 - 1) × 100%`，同时给出对应峰值/谷值日期；不是全区间最低价或盘中回撤。
- 年化波动：后复权简单日收益的样本标准差乘 `sqrt(252)`；另算 MA20/MA60、月末变化，区间两端可能是不完整月份。
- 所有日线参与确定性计算；主模型收到指标与月度结果，网页收到全日线画图。不声称模型逐条阅读全部每日记录。
- 行情是公开网站日线，非实时商业授权服务。复权因子按本次供应商返回值，未保存历史时点因子快照，不适用于严格时点回测。没有接基准指数、估值和新闻，不宣称超额收益、价格因果或买卖信号。

## 预算与报告范围

`agent_runner.py:RunLimits` 默认：18 轮主循环、72 次模型调用、1,200 秒、累计 1,200,000 tokens、单次消息序列 160,000 字符。累计 token 按实际用量在后续调用前检查，最后一个在途请求可能让总量超过阈值；不是精确金额硬上限。供应商不返回用量时仍有调用次数和时间边界。

阅读批次输出 `min(1800, LLM_MAX_TOKENS)`；主研究与报告复核当前用 6,500 token 输出预算。原 `/research/model` 保留 M1-1 的配置和短报告约束。因此 `.env` 的 `LLM_MAX_TOKENS` 不是整份研究的总字数。

没有实现自动上下文压缩。达到步数、调用、时间、上下文、用量边界，取消或出错时，保留实际完成范围并标记 partial/failed/cancelled；不伪装完整报告。最终 JSON 引用需对应实际来源及处理过的 PDF 物理页码。最后复核可减少年份、倍数、口径和资料范围错误，不等于独立财务事实审计。

## 中际旭创真实案例

截止日期 2026-10-23；资料由程序在线发现，无手工写死 PDF 链接。

| 原资料 | 披露日期 | PDF 页数 | 模型处理范围 |
| --- | --- | --- | --- |
| [2024 年报](https://static.cninfo.com.cn/finalpage/2025-04-21/1223155483.PDF) | 2025-04-21 | 236 | 全部可提取文字 |
| [2025 年报](https://static.cninfo.com.cn/finalpage/2026-03-31/1225056459.PDF) | 2026-03-31 | 229 | 全部可提取文字 |
| [2026 半年报](https://static.cninfo.com.cn/finalpage/2026-08-22/1225491753.PDF) | 2026-08-22 | 184 | 全部可提取文字 |

共 649 页；实际 PDF 第 8 页主要财务表另做抽样渲染核对，不能将抽样说成逐条独立核验。最终行情采用腾讯，2024-10-23 至 2026-10-23 共 486 个交易日。网页展示真实数据图、指标表、正文、来源、引用、工具与阅读覆盖。

最终任务 ID：`8fc56014-19be-4acb-9120-8b94556f4e6e`；[本机查看](http://127.0.0.1:5173/?task=8fc56014-19be-4acb-9120-8b94556f4e6e)。仅当前服务进程保留；备份为 `storage/runs/m1-3-zjxc-web-live.json` 和聊天工作区 `outputs/`，不提交研究内容。

最终成功运行记录为 7 次模型调用、133,728 tokens，其中 PDF 阅读复用了先前真实运行的缓存。开发期间还有失败/取消/修正运行并产生模型费用，不能把最后七次当作本轮全部调用或成本。没有已知的精确总金额。

## 检查结果与复现

| 检查 | 结果 |
| --- | --- |
| `scripts/check-agent-loop.py` | 16 组：原生协议、阅读覆盖/修正/缓存、当前年度补充、引用、预算/取消、行情与 fallback |
| `scripts/check-job-bridge.py` | 13 组真实 Java HTTP：创建/轮询/取消、坏响应、ID 与状态、错误脱敏、完整正文超时 |
| `scripts/check-agent-web.mjs` | 9 组 Chrome：真实完成结果、图表交互、4 种宽度、错误/取消、旧 mock 与无异常 |
| 既有回归 | 12 组工具、14 组模型隔离、33 次服务请求 + 12 次故障请求全部通过 |
| 构建与运行 | TypeScript/Vite、Java 打包、三服务 4 项基础检查通过 |

以上隔离/浏览器检查自身不新建付费模型任务；中际旭创研究另外实际调用了账户。相关 JSON/截图在 `.runtime/qa/`，已查看图表与手机截图。

离线循环回归：

```powershell
.\apps\agent\.venv\Scripts\python.exe .\scripts\check-agent-loop.py
```

主动重新执行真实案例（会使用模型账户、读取缓存；不是查看已存结果）：

```powershell
.\apps\agent\.venv\Scripts\python.exe .\scripts\check-agent-live.py --live --as-of 2026-10-23
```

使用已有任务继续查看：加 `--resume <taskId>`。该检查脚本把 JSON 备份到 `storage/runs/`；普通网页任务尚无磁盘持久化。`scripts/run-agent-example.py` 另提供带 `--live` 的直接 Python CLI。

## 建议学习代码顺序

1. `apps/agent/app/services/agent_runner.py`：`declarations` → `run` → `dispatch` → `read` → `review`。先看模型和程序如何轮流行动。
2. `apps/agent/app/services/model_client.py`：`complete_turn` 看请求消息和原生工具返回。
3. `apps/agent/app/tools/registry.py`、`cninfo.py`、`documents.py`、`market.py`：工具实际做事的位置。
4. `apps/agent/app/services/research_jobs.py` 与 `api/routes/jobs.py`：任务、事件、轮询与取消。
5. `apps/server/.../client/AgentJobClient.java`、`controller/ResearchJobController.java`：Java 接口和错误边界。
6. `apps/web/src/api/research.ts`、`ResearchWorkspace.tsx`、`ResearchReport.tsx`、`MarketChart.tsx`：请求、进度、报告和图表。

参考来源与采用理由见 [核心设计依据](agent-design-decisions.md)。下一项 M1-4 做预兆策略与完整 Agent 行为验收；JSONL 会话持久化、侧栏聊天、向量 RAG、上下文压缩、通用网页搜索和长报告导出仍在 M2。
