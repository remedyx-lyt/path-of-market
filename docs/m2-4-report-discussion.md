# M2-4：报告侧边对话与版本

2026-10-24（Australia/Sydney）。F9 本地默认问题完成后，按用户授权接续本项。没有重生成天齐报告，也没有调用真实模型账户验收对话。

2026-10-25更新：M2-5已接入对话摘要、回查与恢复，见[M2-5交接](m2-5-context-compaction.md)。下文原六工具为M2-4交付范围；现在增加`recall_research_context`，共七个逻辑工具。摘要仍不等于跨报告长期记忆。

## 已接入的使用流程

打开完整研究报告 → 点“报告对话” → 选择“追问 / 补查”或“修改正文并另存版本” → 发送。查看、切换版本、展开执行记录和刷新进度都是读取操作；只有发送追问/修改会启动模型。未完成报告先使用原有接续入口。

- 追问自动带上所选报告、原截止日、当前分支历史及准确底稿/来源目录。完整阅读笔记保留在程序中，可按批次回查，避免每轮重复塞入全部笔记。模型可决定回查原页、找其他官方报告、完整阅读、查行情或读研究方法。公开网页搜索仍未接入，不能冒充有搜索能力。
- 修改只输出章节补丁或新摘要；程序合并到新版本，保留旧报告和原图表/数据表。可以追加章节（总数仍最多12节），并同步补齐图表计划。新版标明局部修改，不声称重新审计整篇报告。
- 版本选择器可切换初版/修订版；修改位置可展开比较前后正文。从旧版或旧对话节点再问形成另一分支，其他分支不进入模型上下文。URL中的版本/节点可以恢复当前选择。
- 在报告中选中文字后点“引用选中文字”可带入问题；空引用/超过输入长度有提示。
- 每轮对话保存用户输入、模型消息、工具结果、结束状态和版本关联；完成后可查看本轮工具与执行记录。原研究过程入口已加大对比和留白，可展开回放，不称为模型完整内部思维。
- 刷新/重开会恢复进度轮询，不重发付费请求。临时模型异常在当前节点有限重试；失败/停止的对话可保留已读证据再尝试。硬中断有检查点时复用；请求刚落盘、没有新检查点时回到所基于的完整报告。存储尚未成功时明确提示，不当成已保存。

## 核心实现与学习入口

| 文件 | 职责 |
| --- | --- |
| `apps/web/src/features/research-lab/defaultQuestion.ts`、`workspaceState.ts` | F9模板与自动/手动问题状态；历史问题不被覆盖 |
| `apps/web/src/features/research-lab/ReportWorkbench.tsx` | 报告/侧栏布局、版本与父节点选择、引用原文、修改差异、进度与失败重试 |
| `apps/web/src/api/discussion.ts` | 对话/版本契约、请求标识、免费读取/轮询、前端父链展示；校验后保留完整报告扩展字段 |
| `apps/server/src/main/java/com/pathofmarket/server/controller/ResearchJobController.java`、`client/AgentJobClient.java` | Java转发异步聊天请求，复用统一任务查询/停止入口 |
| `apps/server/src/main/java/com/pathofmarket/server/session/SessionStore.java` | JSONL只追加；向网页投影版本/对话，重启还原；不暴露原始模型上下文 |
| `apps/agent/app/schemas/discussion.py` | 用户请求、回复引用、章节补丁的结构约束 |
| `apps/agent/app/services/report_discussion.py` | 沿父链取上下文、恢复证据、模型→工具→结果循环、引用校验、版本合并、有限重试和保存 |
| `apps/agent/app/services/research_recovery.py` | 复用原执行检查点；完整旧报告也可作为对话证据基础，未完成研究的接续规则仍保留 |

调用关系：React `sendFollowup` → Java `POST /api/research/jobs/{rootTaskId}/chat` → Python `DiscussionRunner` → 原 `AgentRunner.run_tool_call` → 工具结果回传模型 → 回复/修订引用校验 → JSONL → 网页轮询和版本读取。`GET /api/research/jobs/{taskId}/discussion` 只返回版本与对话投影；原始上下文只在本机内部接口读取。

**没有增加新工具**；对话复用现有六个逻辑工具，定义仍在 `agent_runner.py:TOOL_SPECS`，执行入口仍是 `dispatch`：

| 工具 | 作用 |
| --- | --- |
| `find_documents` | 自动找截止日前披露的官方报告 |
| `read_document` | 新选资料分批全文阅读；已读资料按页/关键词回查 |
| `get_market_data` | 取得股票日线与程序计算的行情指标 |
| `inspect_document_pages` | 查看选定PDF物理页图片 |
| `read_research_skill` | 按需读已保留的原版金融研究方法 |
| `extract_report_data` | 从已读原页取数，建立可核对底稿 |

这里新增的是**使用这些工具的多轮对话入口、分支上下文和版本管理**，不是把聊天框本身称为记忆能力。

## JSONL适配

沿用一个研究会话一个文件，旧行不改。新增 `followup`（请求标识、父节点、基础版本、输入）和 `chat_turn`（最终回复/引用/来源、状态、新版本）；修订仍用 `report`，增加 `parentVersionId`、`changedSections`、`summaryChanged`。每轮运行有独立runId，版本号在同会话递增。新运行先把请求标识写入会话再启动模型；重复POST返回原运行，重启后也拒绝重复收费启动。

2026-10-25起，重用所选父节点检查点中的原始消息与摘要边界，原始工具事件/消息继续保存；没有检查点时只沿该JSONL父链重建。当前报告和最新问题固定在历史摘要之外；旧历史超阈值才摘要，完整笔记通过工具回查。超过不可恢复的上下文/调用/时间边界仍会明确停止并保留证据。

参考 [Pi session-format](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/session-format.md) 的父链与追加事件、[Pi agent-loop](https://github.com/earendil-works/pi/blob/main/packages/agent/src/agent-loop.ts) 的上下文转换、[DeepSeek工具调用协议](https://api-docs.deepseek.com/guides/tool_calls/) 的工具请求/结果配对。未拷贝其源码或引入整套框架；章节补丁、报告版本关系、截止日和证据校验是本项目适配。JSONL树形存储是成熟实现选择，不声称所有Agent都必须采用相同格式。

## 验证与边界

- 原有95项Python单测通过；F9状态场景、既有8组恢复UI检查及网页构建通过。
- `python scripts/check-discussion.py`：隔离Java+FastAPI+脚本模型+实际PDF工具+JSONL，21项通过。覆盖追问、修订/追加章节、原版不变、分支隔离、原页回查、临时超时、无效引用修正、账户失败后复用证据、请求去重、非法输入、双服务重启、进程硬中断、取消。隔离JAR副本避免Windows构建锁；测试资料不进正式研究记录。
- `node scripts/check-discussion-web.mjs`：用上述实际HTTP结果检查三个版本的网页契约、渲染、父链隔离、读取零POST和外部文字转义。抓到并修复zod剥离报告扩展字段导致用量显示崩溃的问题。
- 真实浏览器：默认问题联动、手改保护、恢复模板/本地预览；已持久化天齐报告正常打开、侧栏开关、操作切换、空输入/空引用提示、过程展开。没有提交收费问题。小屏抽屉布局已接入，未单独做移动设备视觉验收。
- **真实DeepSeek对话与修订效果尚待用户使用验收**；隔离模型通过不代表真实模型每次都能正确分析。新版本引用页码校验也不是独立财务事实审计。
- 本轮正文/摘要可以修改，图表/数据表内容重写与数值公式核验仍待后续完善；公开搜索、改截止日后的完整更新研究和长期记忆不冒充完成。M2-5压缩已于2026-10-25独立接入。

M2-5已接入，当前下一项为M2-2研究记忆，随后M2-7公开信息搜索。F16剩余项、F17真实分节写作验收与29个表格单元格核验问题继续跟踪。
