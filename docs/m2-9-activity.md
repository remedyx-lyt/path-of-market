# M2-9 过程实时可见（活动流）

2026-10-24。用户要求：研究进行时，界面像 Claude Code / Codex 一样看得见 Agent 在做什么（调用哪个工具、参数是什么、正在写哪一部分），最后报告出来；这是展示“这是一个 Agent”的关键。

## 参考依据

| 来源 | 核对内容 | 本项目采用 |
| --- | --- | --- |
| [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code)（MIT）s01 Agent Loop、s02 Tool Use、s05 TodoWrite | 循环中每次工具调用都有可见记录；先列计划再跟踪进度 | 每次模型决定、工具开始/结束都发结构化事件；研究计划以列表展示 |
| [DeepSeek Chat Completion](https://api-docs.deepseek.com/api/create-chat-completion)（2026-10-24 核对） | `stream` 为 data-only SSE、`data: [DONE]` 结束；`stream_options.include_usage` 时最后一块带用量；工具调用首块带 id/type/function | 写作与数据表两步改为流式，边写边识别章节标题/表名；用量照常记账 |

研究计划的完成状态没有像 TodoWrite 那样让模型逐项勾选（那需要新增工具并改变模型行为）；本步用程序维护的**阶段**表示进度，计划只展示。

## 改了什么

**后端：事件更完整**（事件结构本身已符合 JSONL 方向：`id`、`parentId`、`type`、`timestamp`、`sessionId`、`runId`）

| 事件 | 新增字段 | 例子 |
| --- | --- | --- |
| `phase_changed` | `phase` | methods → research → writing → tables → review → done；核查不通过回到 research |
| `tool_started` | `label`、`summary` | 阅读资料：回查 2025年年度报告 第13、25页 |
| `tool_finished` | `label`、`result`、`durationMs` | 查找报告完成：找到 5 份报告 · 1.2s |
| `model_started` / `model_finished` | `purpose`、`durationMs`、`usage` | 撰写正文完成 · 62s · 6.2万 tokens |
| `assistant_message` | `tools` | 模型决定：阅读资料、提取数据 |
| `methods_planned` | `focus`、`checks` | 研究计划 12 项检查 |
| `writing_section` / `table_section` | `index`、`title` | 正在写：现金流…… / 正在整理表：产能、产量…… |

任务快照新增 `phase`，并返回全部事件（原来只返回最近 160 条，上限 3000）。

**流式输出**：`model_client._stream_payload()` 按 SSE 逐行读取，文字增量交给 `on_text`，最后拼成与非流式相同的结构，后续校验不变。`runner_report.text_watcher()` 从已收到的文字里识别新写完的 `"heading"` / `"title"`，逐个发事件。流式失败时沿用原有回退（不带工具、非流式）。

**前端：活动面板**（`ActivityPanel.tsx`）

- 研究进行中：右侧卡片显示阶段进度、模型调用次数 / token / 缓存命中 / 用时、研究计划、时间线（同一工具的开始与结束合成一行，进行中标 ◌，失败标 ✕；分批阅读进度并入正在进行的阅读行；写作逐节显示，写完打勾）。时间线自动滚到最新。
- 完成后：报告上方“研究过程回放”可展开回看。
- 颜色随所在区域切换（深色任务卡片 / 白色报告区）。

## 代码位置

| 位置 | 作用 |
| --- | --- |
| [research_jobs.py](../apps/agent/app/services/research_jobs.py) `ResearchJob.phase`、`set_phase()`、`snapshot()` | 阶段与事件快照 |
| [agent_runner.py](../apps/agent/app/services/agent_runner.py) `TOOL_LABELS`、`describe_call()`、`describe_result()`、`model_purpose()`、`run_tool_call()`、`run()` | 工具/模型事件、阶段切换 |
| [runner_report.py](../apps/agent/app/services/runner_report.py) `enter_phase()`、`text_watcher()` | 写作阶段与流式识别 |
| [runner_methods.py](../apps/agent/app/services/runner_methods.py) | `methods_planned` 带计划 |
| [model_client.py](../apps/agent/app/services/model_client.py) `_stream_payload()`、`complete_turn(on_text=...)` | 流式请求 |
| [ActivityPanel.tsx](../apps/web/src/features/research-lab/ActivityPanel.tsx) `timeline()`、`ActivityPanel` | 时间线整理与展示 |
| [ResearchPreview.tsx](../apps/web/src/features/research-lab/ResearchPreview.tsx) | 进行中显示面板、完成后回放 |
| [research.ts](../apps/web/src/api/research.ts) `JobEvent` | 事件类型 |

调用关系：`run()` 切阶段 → 模型决定（`assistant_message`）→ `run_tool_call()`（`tool_started`/`tool_finished`）→ … → `compose()`（流式，`writing_section`）→ `add_tables()`（流式，`table_section`）→ `review()` → 完成。网页每 1.5 秒轮询任务快照，`timeline()` 把事件整理成时间线。

## 验证

- 离线：`test_activity.py`（本地假 SSE 服务验证流式拼装、逐段回调、用量与截断报错；完整假研究验证阶段顺序、工具标签/摘要/耗时、计划事件）；新测试共 63 项与原有检查全部通过；网页构建通过。
- 真实运行（案例 A，任务 2e565765）：浏览器中打开运行中的任务，阶段进度、用量、工具时间线实时刷新；写作阶段逐节出现“正在写：……”；DeepSeek 接受流式 + 工具定义 + JSON 模式。结果见 `task-board.md` 与提交说明。

## 未做 / 边界

- 用 `?task=` 打开运行中的任务需点“恢复上次研究”才开始跟踪（原有行为）。
- 轮询而非推送（SSE/WebSocket 推送可在侧边聊天时一起考虑）。
- 此处为 M2-9 当时状态；随后 M2-1 已保存会话、支持重启后查看。任务重启接续尚未实现；最新稳定性见 reliability-review-2026-10-24.md。
