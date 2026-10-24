# M1-4：预兆策略、Skill 使用、token 优化与代码整理

更新：2026-10-24（Australia/Sydney）。本轮按用户要求依次完成三件事：先整理代码，再降低 token 用量，最后实现 M1-4；期间用户补充“不选预兆也要用上 Skill，选了预兆研究能力更强”，一并实现。

**状态：已完成。** 代码与离线验收由云端会话完成；本机会话补完 C7/C10，并完成真实模型验收（A、B、C 全部 completed），过程中发现并修复的问题见“八、真实验收”。

## 一、代码整理（行为不变）

| 问题 | 处理 | 位置 |
| --- | --- | --- |
| `AgentRunner` 一个类 689 行，什么都做 | 拆成 5 个部分，各自拥有一块运行状态；主文件只剩循环、预算、模型调用、工具分派、上下文 | `apps/agent/app/services/agent_runner.py` 及 `runner_*.py` |
| “调用模型→解析→修复一次→写缓存”复制了 5 处 | 抽成 `ask_json` 与 `DerivedCache` | `apps/agent/app/services/model_json.py` |
| 方法计划用 `assert` 校验（`python -O` 会跳过） | 改为 Pydantic `MethodPlan` / `MethodCheck` | `apps/agent/app/schemas/agent.py` |
| `except Exception` 吞掉错误、日志没有堆栈 | `logger.exception` 写入服务日志（`.runtime/logs/agent.err.log`），网页仍只显示受控错误 | `agent_runner.py` 的 `run()` |
| 一长串 `if name == ...` 分派工具 | 分派表 `dispatch()` | `agent_runner.py` |
| 视觉模型名单写死在代码里 | `ModelSettings.vision_models`，可用 `DEEPSEEK_VISION_MODELS` 覆盖 | `app/core/config.py`、`.env.example` |
| 风格不统一 | `ruff format` 统一格式，`ruff check` 清掉未使用导入等；配置在 `apps/agent/ruff.toml` | 格式化只改排版，已逐文件比对语法树确认 |
| 只有自写检查脚本 | 新增 `apps/agent/tests/`（标准库 unittest，无需新依赖） | 见“验收” |
| 文档里工具数量互相矛盾 | 统一为“六个逻辑工具 / 八个底层工具” | README、architecture、research-runtime-plan 等 |

拆分后的结构：

| 文件 | 负责 | 拥有的状态 |
| --- | --- | --- |
| `services/agent_runner.py` | 主循环 `run()`、`finish()`、`run_tool_call()`、`model()`、`dispatch()`、`context()` | 消息、步数、预算、发现的资料 |
| `services/runner_reading.py` | 来源登记、full 分批阅读、page/search 回查 | `sources`、`coverage`、`notes` |
| `services/runner_evidence.py` | 原页视觉核对、正文取数、财务/业务底稿 | `financial_points`、`segment_points`、`visual_readings` 等 |
| `services/runner_methods.py` | 选方法、形成研究计划、计划缓存与失败降级 | `method_usage` |
| `services/runner_omens.py` | 预兆规格进入上下文/写作要求，覆盖自检 | （读取请求与计划） |
| `services/runner_report.py` | 程序核查、写作、复核、最终报告结构 | `review_outcome` |
| `services/runtime.py` | `RunLimits`、`BudgetStop`、`now()` | — |
| `core/omens.py` | 四个预兆的结构化规格、Skill 目录、按问题/预兆选方法 | — |

前端整理（`api/research.ts` 改用 zod、`ResearchWorkspace` 改 `useReducer`）与 `context()` 的结构化投影（`ToolView`）当时未做，已在之后的本机会话补完，见 [handoff-2026-10-24-m1-4.md](handoff-2026-10-24-m1-4.md)“本机核对与补做”。

## 二、token 用量

依据 DeepSeek 官方文档：上下文缓存自动开启，只有与先前请求**开头完全相同**的部分计为命中；`deepseek-flash` 命中价格约为未命中的 1/50（[KV 缓存](https://api-docs.deepseek.com/guides/kv_cache)、[定价](https://api-docs.deepseek.com/quick_start/pricing)）。所以“总 token”大不等于“花钱多”，真正要压的是**未命中部分**和**轮次**。以前代码丢掉了命中/未命中字段，65 万 token 里多少是便宜的缓存部分并不知道。

上次真实案例：24 次调用中输入约 62.5 万、输出只有 2.2 万；钱主要花在每轮把整段上下文重发（约 12 轮决策，其中 7 轮是一次只回查 1～2 页）。

本轮改动（详细理由见 `agent-design-decisions.md`）：

1. 记录 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`，网页“模型用量”显示缓存命中率。
2. 写作阶段沿用研究阶段的系统提示和历史，并带同一组工具定义（`tool_choice=none`），提示开头一致可命中缓存；供应商不接受时自动退回旧方式。
3. **阅读笔记与研究问题无关**：同一份年报换问题不再整本重读。旧缓存（键里含问题）仍能找到并自动转存。
4. 已读完的资料再次 full 不重复回传全部笔记。
5. `read_document` 的 page 模式可一次回查 1～5 页（`pages`），提示允许同一轮并行调用互不依赖的工具。
6. 每轮底稿精简：实际案例数据下每轮约 21k → 12k 字符（−43%）。
7. 复核无需修改时只回 `{"unchanged":true}`，不再整篇重写。
8. 方法参考固定顺序并放在任务之前，同一任务的方法计划缓存复用。

用旧代码与新代码回放同一场景的模拟结果（三份约 210 页年报、行情、14 页回查、写作与复核；按 DeepSeek 前缀规则计算未命中字符；文字是合成的，数值看相对变化，不是账单）：

| 场景 | 旧代码未命中 | 新代码未命中 | 说明 |
| --- | --- | --- | --- |
| 首次研究一家公司 | 757k | 734k | 新代码多了一次方法计划（+50k）仍略降；首轮大头是读年报本身（578k），全文阅读规则要求如此 |
| 首次研究 + 回查批量化 | — | 731k | 决策 11→6 轮，总输入 1.29M→1.04M（−19%） |
| 写作一次 | 77k | **1k** | −98% |
| 同一公司换一个问题 | 712k | **68k** | **−90%**，调用 46→14 次 |

真实效果以 `check-omens-live.py` 的案例 A 为准：它与上次 647,664 tokens 的案例是完全相同的任务，可直接对比。另外 DeepSeek 工作日 UTC 01:00–04:00、06:00–10:00（悉尼时间约 12:00–15:00、17:00–21:00）为高峰价，其余时段半价。

## 三、Skill 使用：不选预兆也能用上，选了预兆更强

`app/core/omens.py` 的 `select_methods(request)` 决定研究前完整读取哪些原版方法：

| 层 | 规则 | 方法 |
| --- | --- | --- |
| 基础（总是） | 每次研究 | 公司研究框架 task1、质量检查清单、thesis-tracker；做财务图时加图表选择 task4 |
| 问题意图 | 问题/偏好里的词 | 业绩/经营→earnings-analysis workflow；竞争/护城河→competitive-analysis；行业/周期→sector-overview；催化/展望/产能→catalyst-calendar；预期/前瞻→earnings-preview；机会/线索→idea-generation；估值→valuation-methodologies（只作方法参考） |
| 预兆叠加 | 所选预兆 | 崇高→competitive-analysis + earnings best-practices；远古→sector-overview；机遇→catalyst-calendar + earnings-preview；深渊回响→valuation-methodologies |

另外主循环开头附一份 Skill 目录（14 项，中文一句话用途与本应用可用程度），模型可用 `read_research_skill` 按需读取；实际按需读取记录在 `methodUsage.onDemandReads` 并显示在网页。方法计划现在每次研究都会运行（以前只在包含财务时运行）；计划格式失败不再中止研究，而是记录 `plan_failed` 并在报告局限中注明。

## 四、M1-4 预兆策略

四个预兆的完整规格（目标、资料偏好、工具提示、必需章节、关键问题、自检、禁止事项、可程序检查的关键要素、当前工具缺口）从 `report-omens.md` 结构化到 `app/core/omens.py`，按设计文档的五个阶段生效：

1. **规划**：方法计划中每个所选预兆至少 2 项带 `omen` 标记的专属检查，否则让模型修正。
2. **资料**：主循环开头的 `omen_research_specs` 给出资料偏好与工具提示，例如远古可查更早年报、取更长行情区间；深渊回响回查风险/应收/商誉/诉讼；机遇回查经营计划/产能/订单。
3. **分析与生成**：写作要求列出每个预兆的章节、关键问题、自检与禁止事项；章节用 `omens` 字段标记；报告带 `omenCoverage` 自评。多预兆报告每个预兆多给 2500 输出 token。
4. **自检**：程序要求每个所选预兆至少有一个带来源的标记章节（否则退回修正），并检查关键要素（如机遇须有“保守”情景、深渊回响须有“假设”“最坏”“监控”），缺了记入未覆盖项。
5. **输出**：`omenCoverage` 合并模型自评、程序核查与能力缺口；`covered` 只代表“现有工具与已读资料范围内”。新闻、政策、行业历史数据等需要 M2-7 公开信息工具的资料一律列为工具缺口。

最低验收案例与对应：

| 案例 | 程序行为 | 离线测试 |
| --- | --- | --- |
| 不同问题/预兆触发不同动作 | 方法、计划检查、工具提示随问题和预兆变化；模型的实际工具选择需真实验收 | `test_case1_*`、`test_question_intent_*` |
| 资料冲突触发补查 | 底稿列出 `conflicts` 并要求查原页/补查；未解决的冲突进入报告局限 | `test_case2_*` |
| 缺证据明确缺口 | 覆盖自评缺项、程序检查缺项与工具缺口分别列出，`covered=false` | `test_case3_*` |
| 达到限制能停止 | 步数/时间/token/上下文预算停止，保留部分结果，预兆标为未完成 | `test_case4_*` 及原有循环检查 |

网页：报告上方新增“研究预兆覆盖”面板，章节标题下显示所属预兆，“研究主线与方法”列出每份方法被选中的原因，执行记录显示缓存命中率。前端校验器同时修复了一个兼容问题：方法计划失败（`plan` 为空）的报告以前会被判为格式不正确。

## 五、验收

本轮在开发环境中运行（Python 3.13 + 已有 pydantic/pypdf，没有 FastAPI；用户本机为 Python 3.14 和完整依赖）：

- 新增 `apps/agent/tests/` 36 项全部通过：Skill 选择 11 项、预兆 9 项、token 相关 10 项、部件 6 项。
- 原有检查：循环 16 项、财务 13 项、图表与方法 19 项全部通过；工具 12 项中 11 项通过，剩下 1 项是 FastAPI HTTP 检查，开发环境装不了 FastAPI，需要在本机运行。
- 原有测试的修改：方法计划现在每次研究都会运行，因此两个测试里的假模型增加了对这次调用的应答；`test_18` 期望的调用序列多一次方法计划。其余断言未改。
- 上游 36 个 Skill 文件哈希全部与固定版本一致。
- 前端：TypeScript 严格模式类型检查新旧代码都是 0 错误（使用本地类型定义替代 node_modules）；用离线运行产生的真实报告对象渲染报告组件并截图核对；前端校验器接受新报告与计划失败的报告。

最简单：双击项目根目录的 `run-m1-4-acceptance.cmd`，它按下面顺序执行（离线检查失败就停止，不会花模型费用），全部输出写入 `.runtime/m1-4-acceptance.log`。也可以手动运行（项目根目录 PowerShell）：

```powershell
# 1) 离线：新测试 + 原有检查（不调用模型）
.\apps\agent\.venv\Scripts\python.exe -m unittest discover -s apps\agent\tests -t apps\agent\tests
.\apps\agent\.venv\Scripts\python.exe .\scripts\check-agent-loop.py
.\apps\agent\.venv\Scripts\python.exe .\scripts\check-report-figures.py
.\apps\agent\.venv\Scripts\python.exe .\scripts\check-financial-research.py
.\apps\agent\.venv\Scripts\python.exe .\scripts\check-tools.py
Set-Location apps\web; npm.cmd run build; Set-Location ..\..

# 2) 重启三服务加载新代码
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-app.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-app.ps1

# 3) 真实验收（会产生模型费用；可先只跑 A）
.\apps\agent\.venv\Scripts\python.exe .\scripts\check-omens-live.py --live --cases A
.\apps\agent\.venv\Scripts\python.exe .\scripts\check-omens-live.py --live --cases B,C
```

真实验收三个案例：A 与上次完全相同的任务（直接对比 token），B 不选预兆的竞争/行业问题（验证按问题选 Skill、阅读笔记跨问题复用），C 远古+机遇（验证不同预兆的不同取证动作与覆盖自评）。结果写入 `storage/runs/m1-4-omens-live.json`。

## 六、工具清单（数量不变）

模型可见六个逻辑工具：`find_documents`（找官方定期报告）、`read_document`（full 完整分批阅读；page 可用 `pages` 一次回查 1～5 页；search 关键词回查）、`get_market_data`（日线与区间指标）、`inspect_document_pages`（查看 1～3 页原页图片）、`read_research_skill`（读原版方法）、`extract_report_data`（从已通读页提取有原文依据的数值）。底层注册八个：`resolve_company`、`find_documents`、`fetch_document`、`search_document`、`read_document`、`read_document_batch`、`get_market_data`、`render_document_pages`。

## 七、边界

- 预兆覆盖是“结构与关键要素由程序核对、内容由模型自评并复核”，不是独立研究质量审计。
- 远古/机遇所需的行业历史、新闻、政策、一致预期数据需要 M2-7；本次只依据公司自身多年披露与行情，并列为缺口。
- 写作请求“带工具定义 + 禁止调用 + JSON”的组合未在 DeepSeek 文档中明示支持，已加自动回退；真实运行会显示是否触发回退（事件 `report_drafting_fallback`）。
- 任务仍只保存在 Python 进程内；会话 JSONL、侧栏聊天、长报告分章等仍在 M2。

## 八、真实验收（2026-10-24，本机）

命令：`scripts/check-omens-live.py --live`；三服务经网页代理→Java→Python；模型 `deepseek-flash`；研究对象中际旭创，截止日 2026-10-23。完整任务 JSON 在 `storage/runs/m1-4-omens-live*.json`（不进 Git）。

### 第一轮发现的问题与修复

| 现象 | 根因 | 修复 |
| --- | --- | --- |
| 案例 A 第一次失败：`MODEL_TIMEOUT` | 写作一次输出整篇报告（多预兆时 1.2 万 token 以上，约 69 秒），而所有调用统一 60 秒上限 | 写作与复核单独上限 `LLM_REPORT_TIMEOUT_SECONDS`（默认 180，60–600）；研究轮次仍 60 秒 |
| 写好的报告因“同一图表放进多个章节”被退回整篇重写 | 机械规则也触发整篇重写 | 程序保留第一次出现、去掉后面的重复（`figure_duplicates_removed`） |
| 报告写到 13–14 节被退回 | 预兆的“应覆盖章节”被理解成各占一节 | 写作要求写明全部章节合计不超过 12 节 |
| 案例 B 只留部分结果：`context_budget` | 额外通读 2023 年报并做 12 次多页回查，越过程序自设的 16 万字符上限后直接停止 | 接近上限（预留 3.2 万字符）时停止取证、转入写作（`context_wrapup`），参照 Pi 的 reserveTokens；补不了的证据写入报告局限 |
| 案例 C 三次写作都因格式超限被退回（图层级多余 citations、引用 14 条 > 12、节点引用 4 条 > 3） | 机械超限触发整篇重写，3 次后中止 | `normalize_report()`：引用去重并截到上限、去掉多余字段（`report_normalized`）；用 C 的 3 份失败草稿验证，整理后均通过 schema |
| 案例 C 行情一直取不到 | 远古预兆提示写“可取 5 年”，行情工具上限约 3 年；参数错误只回“未通过校验”，模型连试 5 次 | 参数错误回传具体原因；提示改为单次不超过约 3 年（年限放宽见任务板 F8） |

### 最终结果（全部 `completed`，`PASS M1-4 真实验收`）

| 案例 | 任务 | 调用 | token | 缓存命中 | 说明 |
| --- | --- | --- | --- | --- | --- |
| A 崇高+深渊回响（与上次同一任务） | e73232db | 14 | 430,902 | 62.5% | 上次同任务 647,664 tokens / 24 次调用，本次少 33%；阅读缓存复用 25 批；写作一次被退回（13 节） |
| B 不选预兆，竞争与行业问题 | e8bf164a | 28 | 617,392 | 52.5% | 按问题选上 competitive-analysis、sector-overview；新通读 2023 年报；接近上下文上限后收尾写作 |
| C 远古+机遇 | 111db574 | 14 | 401,193 | 60.6% | 用最终代码运行；收尾写作、格式整理与图表去重各一次，写作一次通过；工具动作与 A 不同（查更早年度、催化/展望回查） |

A、B 跑于最后一组修复（收尾时缺口记入局限、参数报错详情、收尾提示措辞）之前，C 跑于全部修复之后。写作请求“带工具定义 + `tool_choice=none` + JSON”被 DeepSeek 接受，三次均未触发回退。第一次写作请求的缓存命中低（例：9,472/63,940），之后同类写作请求命中恢复，说明 `tool_choice` 改变了提示开头的渲染；总体命中率仍在 52%–63%。

### 验收后用户反馈

报告与图表偏少、产能/产量/销量等经营数据没有表图、资产负债表缺负债（根因：把母公司报表“负债合计”当作合并口径）、上下文上限过小、预兆名不应出现在正文、行业研究等，已记入 `task-board.md` 的“用户优先补充（三）”F1–F9，按用户指示另行实施。
