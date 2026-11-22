# Python 后端兼容与切换

React 经同源代理调用一个 FastAPI 进程。API 和研究任务共享 `SessionStore` 与 `MemoryStore`，继续使用已有 JSONL、记忆和检查点。单个后端独占会话目录，启动第二个写入进程会失败。指定单独会话目录可设置进程环境变量 `SESSIONS_DIR`，相对路径从项目根目录计算。研究资料与检查点仍在 `storage/documents`。

## 复验

在仓库根目录运行。兼容脚本在临时目录使用合成历史样本、两页 PDF 和本地模型替身，三次独立启动同一个后端。浏览器检查使用本机 Chrome 和 Playwright，支持 `CHROME_PATH`、`PLAYWRIGHT_MODULE_PATH` 覆盖路径。

```powershell
.\apps\agent\.venv\Scripts\python.exe -X utf8 scripts/check-backend-contract.py
.\apps\agent\.venv\Scripts\python.exe -X utf8 scripts/check-discussion.py
.\apps\agent\.venv\Scripts\python.exe -X utf8 scripts/check-memory.py
node scripts/check-python-web.mjs
```

## 切换与回退

先结束进行中的研究，运行 `scripts/stop-app.ps1`。备份 `storage/sessions` 和 `storage/documents/run-checkpoints`，保留同一份资料缓存。运行 `scripts/start-app.ps1` 后可从最近研究打开原报告；查看记录只读取本地文件。Windows 保留默认端口时，脚本会打印实际网址，`scripts/check-app.ps1` 根据启动记录检查两个服务和网页代理。

回到旧运行方式时，先停新后端并保存切换后的记录。在独立工作目录检出 `900831b`，按该版本 README 准备 JDK、Node 和 Python，用备份副本还原上述相对路径及对应资料缓存，再运行旧版启动脚本。原目录保留切换后的新增研究。从该提交也可复现双向读写比对 `scripts/check-backend-contract.py --compare-storage`。旧内部 HTTP 写入端点随 Java 退役，Agent 直接调用存储。

2026-11-22 已在隔离数据副本上演练回退。原版后端成功读回旧报告、原记忆版本以及 Python 新追加的一份报告。

## 12 个公开操作

下表的路径均以 `/api` 开头。`{id}` 是任务的 UUID。研究输入包含 `target`、`question`、可选的 `userStyle` 和 `omens`；模型和 Agent 还接收 `asOfDate`。字段用网页当前发送的驼峰命名。

| 方法与路径 | 输入、成功响应及前端依赖 |
|---|---|
| GET `/api/health` | `200`，`status=ok`、`service=server`。启动脚本据此判断后端就绪。 |
| POST `/api/research/mock` | 研究输入。`200` 演示报告，`mode=mock`、`isMock=true`，含标题、摘要、章节、输入回显，`sources`、`toolCalls` 为空数组。 |
| POST `/api/research/model` | 带截止日的输入。`200` 思路报告，`mode=model`、`isMock=false`、`evidenceStatus=not_retrieved`，保留 `limitations` 和 `run` 的状态序列、任务标识与起止时间。 |
| POST `/api/research/jobs` | 带截止日的输入，可传 `includeMarket`、`includeCurrentPeriod`、`includeFinancials`。`202` 返回新任务快照，`taskId` 用于轮询；已有运行时 `409 RESEARCH_BUSY`。 |
| GET `/api/research/jobs/{id}` | `200` 快照。当前任务从内存读，进程重启后从 JSONL 还原。返回活动、用量、证据覆盖和可空报告。未知任务 `404 RESEARCH_NOT_FOUND`。 |
| DELETE `/api/research/jobs/{id}` | `200` 返回原任务快照，随后轮询最终状态 `cancelled`。已写入的阅读进度可用于接续。 |
| POST `/api/research/jobs/{id}/continue` | 无请求体。`202` 返回新快照，其 `parentTaskId` 指向原任务。原任务仍可查。数据不足以恢复时 `409 RESEARCH_NOT_RESUMABLE`。 |
| POST `/api/research/jobs/{id}/chat` | `message`、`action`（`ask` 或 `revise`）、`parentId`、`requestId`。`202` 返回追问任务。`parentId` 指向选中的会话节点，`requestId` 用于识别重发。 |
| GET `/api/research/jobs/{id}/discussion` | `200` 返回 `sessionId`、`rootTaskId`、`turns` 和 `versions`。保留每次追问的父节点、来源版本和修订后的版本。未知任务返回空响应体的 `404`。 |
| GET `/api/research/sessions` | `limit` 默认 20，限制在 1–100。`200` 返回 `{sessions: [...]}`，按创建时间倒序，列表使用根任务的 `runId`。 |
| GET `/api/research/memory` | 可传 `query`、`limit`、`excludeRoot`。`200` 返回版本、开关、偏好、研究经历、公司及主题观察。记忆检索上限是 30。 |
| POST `/api/research/memory` | 发送读取时的 `revision`、`action` 和动作字段。支持保存、遗忘、开关、忽略或恢复公司。`200` 返回新快照；过期版本 `409 MEMORY_CONFLICT`，非法编辑 `400 INVALID_MEMORY`。 |

网页依赖的任务状态为 `queued / running / completed / partial / failed / cancelled`。轮询读取 `progress`、`events`、`modelCalls`、`coverage` 和 `report`；活动历史还读取 `target`、`phase`、`usage` 与 `parentTaskId`。结束时如 `persistence.unsent` 仍大于零，追问页面会继续等待落盘。完整报告、财务表图、覆盖范围和引用仍须满足现有 [Zod 校验](../apps/web/src/api/researchSchemas.ts)；对话版本与记忆分别见[对话读取](../apps/web/src/api/discussion.ts)和[记忆读取](../apps/web/src/api/memory.ts)。

无效 JSON 的参考响应是 `400`，错误码为 `INVALID_JSON`。请求字段校验失败返回 `422`，`detail` 是含 `loc`、`msg` 和 `type` 的数组。业务错误使用 `{error: {code, message}}`。两个 `404` 的差异，以及追问重发的两种结果，都已纳入回归。

## 固定历史样本与验收

[样本目录](../scripts/backend_contract/fixtures)包含 3 个 v1 会话、1 个 v1 检查点和 1 份已有偏好的记忆文件。样本由测试数据构造。检查点的证据状态来自项目离线模型读取两页合成 PDF 的结果，固定了标识并缩短了测试提示词。

| 情形 | 自动检查的行为 |
|---|---|
| 已完成研究带一次修订 | 通过根任务读取第一版，通过追问任务读取修订版。两版报告、父版本、追问节点和用户回答能够对应。 |
| 中断且仅有活动记录 | 历史可读，状态为 `failed`，错误码为 `RESEARCH_INTERRUPTED`；尝试接续得到 `409`。 |
| 中断且保有旧版检查点 | 恢复已读的两页资料，生成独立的新任务并完成报告。根据工具记录和测试模型调用记录核对没有重读。 |
| 再创建一个任务并取消 | 运行期间第二次创建得到 `409`。资料读完后取消，重启后端，再接续到完成；旧任务仍可按原 ID 查询。 |
| 重发同一次追问 | 任务还在内存时返回原追问任务。再次重启后重发返回 `409 RESEARCH_NOT_RESUMABLE`，打开历史仍能读到原回答。两次重发合计没有增加模型调用。 |
| 更新旧记忆 | 旧版偏好可以读取；提交过期修改不会覆盖新值，非法修改不会递增版本。重启后开关及版本仍可读。 |

测试结束逐字节核对三份原始 JSONL 和原始检查点。条目去重、截断行恢复、并发提交与记忆候选规则见[存储测试](../apps/agent/tests/test_local_storage.py)及[记忆验收](../scripts/check-memory.py)。
