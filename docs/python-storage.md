# 第二阶段 · Python 会话与研究记忆存储

`SessionStore` 和 `MemoryStore` 可以直接打开既有的会话目录。会话沿用 `{sessionId}.jsonl`，偏好沿用 `memory/user.json`，检查点继续由研究引擎管理。本阶段在临时副本上验证双向读写。日常启动的网页和 Agent 仍使用 Java 存储入口。

## 从哪里读代码

| 入口 | 负责的行为 |
| --- | --- |
| [sessions.py](../apps/agent/app/storage/sessions.py) | `append` 按会话串行追加并按条目 ID 去重。`entries_for_run` 按运行 ID 取回整份会话，包括追问节点。冷启动从文件重建索引。 |
| [projections.py](../apps/agent/app/storage/projections.py) | 从条目还原某次任务的快照、对话分支及报告版本、最近研究列表和记忆用的用户提问。缺少结束记录的任务显式标记为 `RESEARCH_INTERRUPTED`。 |
| [memory.py](../apps/agent/app/storage/memory.py) | `snapshot`、`edit` 和 `suggest` 读取、修改偏好及记录候选。提交时检查 `revision`，候选须能在同一次运行的用户原话中找到。 |
| [storage_comparison.py](../scripts/backend_contract/storage_comparison.py) | 实际启动旧服务，让 Java 写入、Python 接手、Java 冷启动读回。在相同文件上逐字段比较快照、完整条目、版本、最近记录和记忆。 |

第三阶段在应用启动时创建一套 `sessions = SessionStore(directory)` 和 `memory = MemoryStore(sessions)`，供路由与研究任务共享。`directory` 指向会话目录本身。当前的锁协调同一进程内共享这些实例的调用，每个数据目录由一个写入进程负责。交接时先停旧写入方再启动新写入方。

## 写入与恢复

- 同一批中如有不合法的条目，整批在写文件前被拒绝。发生部分写入后，重试先从文件重建条目 ID，再补尚未写全的行。文件末尾如有残行，会从新的一行继续。
- 会话写入执行 `flush` 和 `fsync` 后才确认成功。即使上次刷盘报错时所有行已可读，重试也会再次刷盘。记忆修改把状态写到同目录的临时文件，刷盘成功后原子替换。刷盘或替换失败时旧偏好、旧版本号仍有效。
- 长期偏好与一次研究的材料各自保存。记忆中的经历仅取自成功研究或已完成追问。用户提出偏好建议时，可以核验本次提问及研究风格；报告、工具消息以及其他分支的输入都不能作为本次用户原话。
- 忘记一条偏好时删去正文与原话，保留与 Java 兼容的内容指纹。容量仍是 48 条有效笔记和 256 条删除指纹。Python 按删除时间保留最近 256 条，修正了旧实现满额时可能立即挤掉刚删除指纹的边界行为。

## 如何复验

在仓库根目录运行。跨语言检查使用第一阶段的 Java JAR，构建方式见[兼容基线](backend-compatibility.md)。

```powershell
.\apps\agent\.venv\Scripts\python.exe -X utf8 -m unittest discover -s apps/agent/tests -p test_local_storage.py
.\apps\agent\.venv\Scripts\python.exe -X utf8 scripts/check-backend-contract.py --compare-storage
.\apps\agent\.venv\Scripts\python.exe -X utf8 scripts/check-backend-contract.py
```

第一条覆盖并发追加、版本冲突、残行、刷盘和替换失败、坏文件保护、偏好容量及删除去重。第二条验证两种后端轮流读写同一副本，并从旧检查点接续，核对已读资料没有重复阅读。第三条复验旧后端的 12 个公开操作。合成样本中的原始 JSONL 与检查点均按字节核对，模型调用使用本地测试替身。

2026-11-18 上述三项均已通过。Python 全量离线测试通过 219 项，包含本阶段新增的 12 项存储测试。

下一阶段将公开 API、Agent 的事件追加、接续读取和记忆工具接到同一套存储实例，再运行同一套网页兼容检查。
