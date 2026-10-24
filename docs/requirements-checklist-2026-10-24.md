# 改进要求核对清单（2026-10-24 会话）

用途：把这次会话里用户提出的全部改进要求逐条列出，写明“改在哪、怎么确认”，供下一个会话（Claude Code，本机）逐项核对是否真的改好了。逐文件说明见 [handoff-2026-10-24-m1-4.md](handoff-2026-10-24-m1-4.md)，设计说明见 [m1-4-omens.md](m1-4-omens.md)。

状态说明：✅ 已修改，并在云端离线验证；⏳ 已修改，但需要在本机或真实模型下确认；⏸ 暂缓未做（写明原因）。

**整体前提：所有改动都在工作区，未提交 Git。** 云端写完时未在本机运行过；本机会话（2026-10-24）已逐条核对、跑完统一核对命令并补完 C7、C10，结果见“十、本机核对记录”。真实模型验收（X2、X3）已通过。

## 一、用户原话要求 → 对应条目

| # | 用户要求（原意） | 对应条目 |
| --- | --- | --- |
| R1 | 看项目进度并汇报；代码可以改进，先按文档来 | 已汇报（非代码项）；代码问题见 C 组 |
| R2 | 确认用 Agent 时可以用这些 Skill | S1–S3 |
| R3 | 先改上次指出的代码问题 | C1–C11 |
| R4 | 每次用的 token 很多，想办法减少，有办法就优化 | T1–T10 |
| R5 | 改好后做 M1-4 | M1–M9 |
| R6 | Skill 也要改进：不选预兆也能用上；选了预兆，这方面研究能力更强 | S4–S7、M2 |
| R7 | 想看到改了哪些文件、具体改了什么 | V1–V3 |
| R8 | 检查好了再实际试一下 | X1–X3（⏳ 需本机执行） |

## 二、统一核对命令（项目根目录 PowerShell）

```powershell
git status
git diff --stat
.\apps\agent\.venv\Scripts\python.exe -m unittest discover -s apps\agent\tests -t apps\agent\tests -v
.\apps\agent\.venv\Scripts\python.exe .\scripts\check-agent-loop.py
.\apps\agent\.venv\Scripts\python.exe .\scripts\check-financial-research.py
.\apps\agent\.venv\Scripts\python.exe .\scripts\check-report-figures.py
.\apps\agent\.venv\Scripts\python.exe .\scripts\check-tools.py
Set-Location apps\web; npm.cmd run build; Set-Location ..\..
```

期望：新测试 38 项全部 OK（云端时为 36 项，本机会话补 C7 加了 2 项）；循环 16、财务 13、图表与方法 19、工具 12 项全部 OK；网页构建通过。云端只确认过 36+16+13+19 项和工具 12 项中的 11 项（缺 FastAPI），TypeScript 用的是 6.x，**本机 TS 7 构建和 FastAPI 那项要在这里第一次确认**。或者直接运行 `run-m1-4-acceptance.cmd -SkipLive`（日志在 `.runtime\m1-4-acceptance.log`）。

## 三、C 组：代码问题（R3）

| # | 原问题 | 状态 | 改在哪 | 怎么确认 |
| --- | --- | --- | --- | --- |
| C1 | `AgentRunner` 一个类 689 行，职责过多，`run()` 嵌套深 | ✅ | `apps/agent/app/services/agent_runner.py` 只剩循环、预算、模型调用、分派、上下文；拆出 `runner_reading.py`（ReadingMixin）、`runner_evidence.py`（EvidenceMixin）、`runner_methods.py`（MethodMixin）、`runner_omens.py`（OmenMixin）、`runner_report.py`（ReportMixin）、`runtime.py`；`run()` 拆出 `finish()`、`run_tool_call()` | 打开文件看 `class AgentRunner(ReadingMixin, EvidenceMixin, MethodMixin, OmenMixin, ReportMixin)`；原有 4 个检查脚本全部通过即行为未变 |
| C2 | “调用模型→解析→失败修一次→写缓存”复制 5 处 | ✅ | `apps/agent/app/services/model_json.py`：`ask_json()`、`DerivedCache`、`stable_key()`；阅读、视觉、取数、方法计划都改用它 | `test_runner_parts.py`：`test_ask_json_repairs_once_then_raises`、`test_derived_cache_round_trip_and_corruption`；在 runner_* 中搜索 `ask_json(` 应有 4 处调用 |
| C3 | 方法计划用 `assert` 校验（`python -O` 会跳过） | ✅ | `apps/agent/app/schemas/agent.py`：`MethodCheck`、`MethodPlan`；`runner_methods.py` 的 `parse()` | `test_method_plan_schema_replaces_asserts`；搜索 `assert` 在 `app/services/` 下应无业务校验用法 |
| C4 | `except Exception` 吞掉错误，日志无堆栈 | ✅ | `agent_runner.py` 的 `run()`：`logger.exception("research run %s failed", ...)`，logger 名 `path_of_market.agent`；网页仍只看到受控错误 | `test_unexpected_error_is_logged_with_traceback` |
| C5 | 一长串 `if name == ...` 分派工具 | ✅ | `agent_runner.py` 的 `dispatch()` 用 handlers 字典；未知工具返回 `UNKNOWN_TOOL` | `test_unknown_tool_rejected_by_dispatch_table` |
| C6 | 视觉模型名单写死在代码里 | ✅ | `apps/agent/app/core/config.py`：`DEFAULT_VISION_MODELS`、`ModelSettings.vision_models`、环境变量 `DEEPSEEK_VISION_MODELS`；`.env.example` 加注释；`runner_evidence.py` 的 `inspect()` 读取设置 | `test_vision_models_come_from_settings` |
| C7 | `context()` 每轮重解析、判断“是否带原文”的方式脆弱 | ✅（本机会话补完） | `agent_runner.py`：`ToolView`（每条工具消息的投影与较早回查的摘录版本，只解析一次）、`tool_view()`（按 `tool_call_id` 缓存，内容变化时重建）、`page_texts()`（按结构判断回查原文）；`context()` 直接取缓存的投影。修复：通读笔记 `facts.text` 不再被算作回查原文 | `test_context_parses_each_tool_message_once`、`test_full_read_notes_do_not_count_as_page_lookups`、`check-report-figures.py` test_17、`test_multi_page_lookup_in_one_call`；4 个离线场景改动前后发给模型的消息逐字节一致 |
| C8 | 风格不统一 | ✅ | `apps/agent/ruff.toml`；`ruff format` / `ruff check` 已对 `apps/agent/app` 和 `apps/agent/tests` 执行；格式化前后逐文件比对语法树，未改逻辑（`tools/market.py` 删了一个未使用的 `import json`） | 本机可选：`pip install ruff` 后在 `apps/agent` 下运行 `ruff check app tests` 和 `ruff format --check app tests` |
| C9 | 测试目录为空，只有自写检查脚本 | ✅ | 新增 `apps/agent/tests/`（标准库 unittest，无新依赖）：`support.py` + 4 个测试文件共 36 项（本机会话补 C7 后为 38 项） | 统一核对命令第三行 |
| C10 | 前端 `research.ts` 手写校验 387 行；`ResearchWorkspace` useState 很多 | ✅（本机会话补完） | `apps/web/src/api/researchSchemas.ts`（zod schema，跨字段规则用 refine）；`research.ts` 改为调用 schema（`isAgentReport`、`jobRequest`、`generateReport`、错误响应解析）；`apps/web/src/features/research-lab/workspaceState.ts`（`workspaceReducer`）；`ResearchWorkspace.tsx` 改用 `useReducer`；依赖 `zod@4.6.7` | 网页构建通过；新旧校验器对比（见“十、本机核对记录”）；浏览器核对演示流程、真实报告恢复与显示、预兆覆盖面板、任务不存在的错误路径 |
| C11 | 文档工具数量互相矛盾；`current-state.md` 过长 | ✅ | 统一为“六个逻辑工具 / 八个底层工具”，旧说法标“当时”；`current-state.md` 精简，原文移到 `docs/history.md` | 搜索 `五个逻辑工具`、`三个逻辑工具`，只应出现在 history.md 或带“当时/写作时”的句子里 |
| C12 | （测试中发现的缺陷）方法计划失败后复核把状态改成“已计划并复核” | ✅ | `runner_report.py` 的 `review()`：`plan_failed` 时保留状态 | `test_plan_failure_degrades_instead_of_aborting` |
| C13 | （核对中发现的缺陷）网页校验器把 `plan=null` 的报告判为格式错误 | ✅ | `apps/web/src/api/research.ts` 的 `isAgentReport()` | 网页构建通过；可用一个 `methodUsage.status='plan_failed'`、`plan=null` 的报告调用 `isAgentReport` 验证 |

## 四、S 组：Skill 可用与改进（R2、R6）

| # | 要求 | 状态 | 改在哪 | 怎么确认 |
| --- | --- | --- | --- | --- |
| S1 | 16 个原版 Skill 在 Agent 运行时真的能读到 | ✅ | `apps/agent/app/core/research_skills.py`：`catalog()`、`read_reference()`（按 `UPSTREAM.json` 哈希校验）；`.gitattributes` 已禁止对 `third_party/anthropic-financial-services/**` 做换行转换 | 云端核对：36 个文件哈希与固定版本 574ed36 一致；`test_every_omen_method_exists_in_pinned_catalog` |
| S2 | 每次研究自动加载项目 Skill | ✅（原有） | `load_research_skill()`：company-financial-research + 原版 earnings-analysis SKILL.md 放进系统提示 | `initial_messages()` 的第一、二条消息 |
| S3 | 模型可以按需读取其余 Skill，并留下记录 | ✅ | `agent_runner.py` 的 `read_skill()`：记录到 `methodUsage.onDemandReads`，发出 `skill_read` 事件 | `test_catalog_visible_and_on_demand_reads_recorded` |
| S4 | **不选预兆也能用上 Skill**：按研究问题选方法 | ✅ | `apps/agent/app/core/omens.py`：`INTENT_METHODS`、`select_methods()`（基础方法总是包含，再按问题词追加：业绩→earnings workflow，竞争→competitive-analysis，行业/周期→sector-overview，催化/展望→catalyst-calendar，预期→earnings-preview，机会→idea-generation，估值→valuation-methodologies） | `test_base_methods_always_present_without_omen`、`test_question_intent_selects_different_skills` |
| S5 | 把 Skill 目录交给模型，让它知道还能读什么 | ✅ | `omens.py` 的 `SKILL_CATALOG`（14 项中文用途与可用程度）；`research_skills.py` 的 `skill_catalog()`；`agent_prompts.py` 的 `initial_messages()` 加入 `skill_catalog` 消息；主提示说明用法 | `test_catalog_visible_and_on_demand_reads_recorded` |
| S6 | 方法计划每次研究都运行（以前只在包含财务时运行），失败不中止研究 | ✅ | `runner_methods.py` 的 `prepare_methods()`：失败记 `plan_failed` 并继续，报告局限注明 | `test_plan_runs_even_without_financials_or_omens`、`test_plan_failure_degrades_instead_of_aborting` |
| S7 | **选了预兆，这方面能力更强**：叠加该预兆专属 Skill 与检查 | ✅ | `omens.py` 每个 `OmenSpec.methods`（崇高→competitive-analysis + earnings best-practices；远古→sector-overview；机遇→catalyst-calendar + earnings-preview；深渊回响→valuation-methodologies）；`runner_methods.py` 要求每个所选预兆至少 2 项 `omen` 标记的计划检查 | `test_omen_stacks_its_own_skills_on_top_of_question`、`test_omen_plan_needs_tagged_checks_then_repairs` |

## 五、T 组：减少 token（R4）

依据：DeepSeek 前缀缓存自动开启，与先前请求开头相同的部分计为命中，`deepseek-flash` 命中价约为未命中的 1/50（api-docs.deepseek.com/guides/kv_cache、/quick_start/pricing）。

| # | 优化 | 状态 | 改在哪 | 怎么确认 |
| --- | --- | --- | --- | --- |
| T1 | 记录缓存命中/未命中（以前被丢弃） | ✅ | `model_client.py`：`USAGE_FIELDS`、`usage_counts()`；网页 `ResearchReport.tsx` 的 `usageText()` 显示命中率 | `test_usage_keeps_cache_hit_and_miss`；真实运行后看 `run.usage` |
| T2 | 写作沿用研究阶段的系统提示和历史（以前换系统提示，整段未命中） | ✅ | `runner_report.py` 的 `compose()`：`self.context()` + 追加 `REPORT_RULES`；`agent_prompts.py` 拆出 `REPORT_RULES` | `test_compose_reuses_research_prefix` |
| T3 | 写作请求带同一组工具定义但禁止调用（`tool_choice=none`），失败自动回退 | ⏳ | `model_client.complete_turn(tool_choice=...)`；`agent_runner.model(write_only=True)`；`compose()` 捕获 `MODEL_UPSTREAM_ERROR` / `MODEL_INVALID_RESPONSE` 后回退，发 `report_drafting_fallback` 事件 | `test_compose_sends_same_tools_but_forbids_calls`、`test_compose_falls_back_when_provider_rejects_tool_choice_none`；**真实运行中看是否触发回退** |
| T4 | 阅读笔记与研究问题无关：同一份年报换问题不再整本重读 | ✅ | `agent_prompts.py` 的 `READ_SYSTEM`（通读要点）；`runner_reading.py` 的 `batch_note()`，缓存键不含问题，`READING_VERSION=2` | `test_reading_notes_shared_across_questions` |
| T5 | 兼容旧缓存：以前含问题的笔记仍可找到并转存 | ✅ | `LEGACY_READ_SYSTEM`（与旧提示逐字相同）；`batch_note()` 的 legacy_key 分支 | `test_legacy_question_keyed_notes_are_migrated`；真实案例 A 应大量 `reading_cache_reused` |
| T6 | 已读完的资料再次 full 不重复回传全部笔记 | ✅ | `runner_reading.py` 的 `read()`：返回 `notesAlreadyProvided` | `test_second_full_read_does_not_resend_notes` |
| T7 | 减少轮次：一次回查 1～5 页；允许同一轮并行调用 | ✅ | `schemas/agent.py` 的 `AgentReadArguments.pages`；`runner_reading.lookup()`；`AGENT_SYSTEM` 的“节省轮次”说明 | `test_multi_page_lookup_in_one_call`；真实运行看决策轮数 |
| T8 | 每轮底稿精简（约 −43%） | ✅ | `runner_report.py` 的 `compact_financial()`、`strip_quotes()`；`context()` 使用 | `test_state_message_is_compact` |
| T9 | 复核无需修改时只回 `{"unchanged":true}` | ✅ | `REVIEW_SYSTEM`；`runner_report.review()`；`run.reviewOutcome` | `test_review_unchanged_skips_full_rewrite` |
| T10 | 方法参考固定顺序并放在任务前（跨研究命中）；同一任务的计划缓存复用 | ✅ | `omens.py` 的 `CANONICAL_METHODS`；`runner_methods.py`（`references` 在前、`task` 在后；`DerivedCache(... "method-plans")`） | `test_selection_order_is_canonical_for_prefix_cache`、`test_references_precede_task_in_plan_request`、`test_plan_is_cached_and_reused_for_identical_task` |

模拟结果（新旧代码回放同一场景，合成文字，只看相对变化）：同公司换问题，未命中 71.2万→6.8万字符（−90%）；写作一次 7.7万→0.1万（−98%）；回查批量化后决策 11→6 轮。**真实效果待 X2 确认。**

## 六、M 组：M1-4 预兆策略与 Agent 验收（R5）

依据：`docs/report-omens.md` 的五阶段与任务板最低验收案例。

| # | 要求 | 状态 | 改在哪 | 怎么确认 |
| --- | --- | --- | --- | --- |
| M1 | 预兆写进工作流状态，而不只拼进提示词 | ✅ | `omens.py` 的 `OmenSpec` / `OMENS`（四个预兆的完整规格）；`initial_messages()` 的 `omen_research_specs` 消息 | 打开 `omens.py`；`test_case1_omens_change_methods_plan_and_tool_hints` |
| M2 | 规划阶段：预兆增加专属任务与方法 | ✅ | `runner_methods.prepare_methods()`；每个预兆至少 2 项带 `omen` 的检查 | `test_omen_plan_needs_tagged_checks_then_repairs` |
| M3 | 资料阶段：预兆调整资料偏好与工具选择 | ✅（提示层面） | `OmenSpec.data_preferences`、`tool_hints`（远古：更早年报、更长行情；深渊回响：回查风险/应收/商誉；机遇：经营计划/产能/订单） | `test_case1_*`；**模型是否真的照做，需 X3 确认** |
| M4 | 生成阶段：按预兆组织章节 | ✅ | `schemas/agent.py`：章节 `omens` 字段、`OmenSelfReport`、`AgentContent.omen_coverage`，章节上限 12；`runner_omens.omen_writing_instruction()`；多预兆每个加 2500 输出 token | `test_writing_instruction_lists_selected_omens`、`test_more_omens_get_more_report_budget` |
| M5 | 自检阶段：每个所选预兆至少一个有来源的章节 | ✅ | `runner_omens.validate_omens()`（在 `validate_content()` 中调用） | `test_report_without_omen_section_is_sent_back` |
| M6 | 输出预兆覆盖情况 `omenCoverage` | ✅ | `runner_omens.omen_coverage()`：模型自评 + 程序关键要素检查（`required_terms`）+ 工具缺口（`capability_gaps`）；`covered` 限定为“现有工具范围内” | `test_completed_run_reports_coverage_per_omen` |
| M7 | 最低验收案例 1–4 | ✅（离线） | 冲突：`agent_runner.conflicts()`、底稿 `conflicts` 与 `conflictInstruction`、报告局限；缺口：`missingItems` / `capabilityGaps`；停止：预算停止后 `covered=false` | `test_case2_conflicts_surface_and_stay_in_limitations`、`test_case3_missing_evidence_is_explicit`、`test_case4_step_budget_stops_and_marks_omens_incomplete`；案例 1 的“实际工具动作不同”需 X3 |
| M8 | 网页显示预兆覆盖 | ✅ | `ResearchReport.tsx`：`OmenCoveragePanel`、章节 `section-omens` 标记、`MethodUsagePanel`（方法选择原因、按需读取）；`global.css` 少量样式；`research.ts` 新类型与 `validOmenCoverage()` | 网页构建通过；真实报告页面上能看到“研究预兆覆盖”面板 |
| M9 | 真实验收脚本 | ✅（脚本） | `scripts/check-omens-live.py`（案例 A/B/C）；一键脚本 `run-m1-4-acceptance.cmd` / `scripts/run-m1-4-acceptance.ps1` | 见 X 组 |

## 七、V 组：能看到改了什么（R7）

| # | 内容 | 位置 |
| --- | --- | --- |
| V1 | 逐文件改动清单（新增 / 有逻辑变化 / 只改格式 / 文档） | `docs/handoff-2026-10-24-m1-4.md` |
| V2 | 完整差异（6,713 行） | `.runtime/m1-4-changes.diff`（不进 Git）；本机 `git diff`，或 VS Code / Cursor 的“源代码管理”面板 |
| V3 | 本核对清单 | `docs/requirements-checklist-2026-10-24.md` |

## 八、X 组：实际试一下（R8，⏳ 全部需要本机执行）

| # | 步骤 | 通过标准 |
| --- | --- | --- |
| X1 | 统一核对命令全部通过（含本机 FastAPI 测试与 TS 7 网页构建） | 全部 OK；有失败先修，再继续 |
| X2 | 重启三服务后跑 `check-omens-live.py --live --cases A` | 状态 completed；与上次同一任务（647,664 tokens / 24 次调用，任务 921f4324）对比总 token 与缓存命中率；`readingCacheReused` 大于 0；记录是否出现 `report_drafting_fallback` |
| X3 | 跑 `--cases B,C` | B：未选预兆但方法里有竞争/行业相关 Skill，阅读缓存复用；C：工具动作与 A 有差异（如更长行情区间、展望/产能回查），`omenCoverage` 两项合理并列出工具缺口 |
| X4 | 通过后收尾 | `task-board.md` 里 M1-4 改为“已完成”，更新 `current-state.md`；先 `git status` 区分之前未提交的“图表数据标签”小改，分开提交 |

## 九、明确没做的

- ~~C10：前端 zod / `useReducer` 整理~~、~~C7 只做了一部分~~：本机会话已补完，见 C7、C10 与“十、本机核对记录”。
- 方法参考没有改为“只读相关段落”：沿用此前“选中的方法完整阅读”的规则，改为靠固定顺序 + 前缀缓存 + 计划缓存省钱。
- 新闻、政策、行业历史、一致预期等资料仍需 M2-7 的公开信息工具，相关预兆需求只能列为工具缺口。

## 十、本机核对记录（2026-10-24，Claude Code 本机会话）

| 项 | 结果 |
| --- | --- |
| 清单引用核对 | 本清单引用的函数、类、测试与文件全部存在；缺漏只有 C7（部分）与 C10（暂缓），已补完 |
| X1 统一核对命令 | 补做前：36 + 16 + 13 + 19 + 12 项全部通过（含 FastAPI HTTP），网页构建通过。补做后：新测试 38、循环 16、财务 13、图表与方法 19、工具 12 项全部通过；网页构建通过；`npm audit` 0 个漏洞 |
| C7 行为不变 | 4 个离线场景（默认、预兆、财务、多轮按页/关键词回查）改动前后发给模型的消息逐字节一致（仅时间戳与索引哈希不同） |
| C10 新旧校验器对比 | 14 份样本（本机保存的 8 份真实任务、4 份离线生成的 M1-4 格式任务、演示与模型报告各 1 份）加按字段路径生成的变异样本（删字段、改类型、置空、页码越界、空数组、重复元素等 14 种），共 57,120 个，新旧两版公开入口（`getAgentJob` / `generateReport`）的接受/拒绝结论全部一致 |
| 三服务 | 重启后 `check-app.ps1` 4 项基础链路通过 |
| 浏览器 | 演示模式完整流程；真实报告（任务 921f4324）经“恢复上次研究”显示 13 章、16 个图表；M1-4 预兆覆盖面板与章节标记；不存在任务的错误路径；控制台无错误 |
| X2、X3 | A、B、C 全部 completed（任务 e73232db、e8bf164a、111db574）；过程中修复写作超时、机械格式重写、上下文越限停止，详见 `m1-4-omens.md` 八 |
