# 第一步：Python 研究服务骨架

任务编号：M0-1。当前状态：**待用户明确要求执行**。

本文件定义下一次实施任务；接口、数据结构和命令均为计划，不代表已实现。

## 为什么从这里开始

研究 Agent 在 Python 服务中执行。先把服务启动和研究数据格式确定下来，后续模型、工具、Java 和网页才能围绕同一份接口接入。

已有虚拟环境不代表服务已经完成。目前 `apps/agent/app/main.py` 仍是占位说明。

## 任务范围

1. 建立最小 FastAPI 应用和健康检查。
2. 定义研究请求与结构化报告的数据格式。
3. 提供返回演示数据的研究接口，并明确标记 `mode: mock`。
4. 补齐依赖清单和本地启动脚本。
5. 完成实际 HTTP 验证，记录结果并更新进度。

M0-1 这项任务不接真实模型、不抓行情、不建向量索引，也不实现 Java 或前端。Java 和网页属于同一 M0 阶段的后续任务；完成整条演示链路后，M1 再单独实现真实 Agent 循环。

## 计划接口

### GET /health

确认当前 Python 应用正在运行。健康检查不能声称模型或数据源已接通。

计划返回示例：

```json
{
  "status": "ok",
  "service": "agent",
  "mode": "mock"
}
```

### POST /research/mock

计划请求示例：

```json
{
  "target": "某公司",
  "question": "如何研究它的研发投入变化？",
  "userStyle": "关注长期增长和风险验证",
  "omens": ["opportunity", "abyssal_echoes"]
}
```

- `target`：研究对象，必填且不能只包含空白。
- `question`：研究问题，必填且不能只包含空白。
- `userStyle`：可选偏好，默认空字符串。
- `omens`：可选预兆列表，默认空列表；仅接受 `exalted`、`ancient`、`opportunity`、`abyssal_echoes`。
- 输入需要合理的长度和类型检查；无效请求返回可识别的校验错误。

计划返回至少包含以下字段：

```json
{
  "mode": "mock",
  "isMock": true,
  "target": "某公司",
  "question": "如何研究它的研发投入变化？",
  "userStyle": "关注长期增长和风险验证",
  "omens": ["opportunity", "abyssal_echoes"],
  "title": "演示研究报告",
  "summary": "用于验证接口，尚未读取真实资料或调用大模型。",
  "sections": [
    {
      "heading": "研究任务",
      "content": "展示收到的研究对象、问题和视角。"
    }
  ],
  "sources": [],
  "toolCalls": []
}
```

不得编造财经数字、资料来源或工具调用。预兆可以被接收和展示，但不能把演示接口标记为已经满足真实预兆研究规格。

## 预计修改范围

- `apps/agent/app/main.py`：服务入口与路由注册。
- `apps/agent/app/schemas/`：研究输入和报告格式。
- `apps/agent/app/api/routes/`：健康检查与演示研究接口。
- `apps/agent/app/services/workflows/`：演示报告生成，供 M1 后续接入真实研究执行。
- `apps/agent/requirements.txt`：经过实际验证的依赖清单。
- `scripts/start-agent.ps1`：从明确项目位置启动本地服务。
- `README.md`、`docs/current-state.md`、`docs/task-board.md`：真实运行方式、验证结果和完成状态。

文件数量以必要实现为准，保持代码可读，不引入本阶段用不到的复杂框架。

## 验收标准

1. 根据说明可以启动 Python 应用，默认仅监听本机 `127.0.0.1:8000`。
2. `/health` 返回 HTTP 200 和服务标识。
3. 合法研究请求返回 HTTP 200；中文对象、问题、偏好和预兆正确传递。
4. 空对象、空问题、错误类型或未知预兆有明确校验错误，不生成报告。
5. 演示报告有 mock 标记，真实来源和工具记录为空。
6. `/docs` 和 `/openapi.json` 可用于查看接口约定。
7. 更新文档后检查 diff，并保存一个明确的 M0-1 Git 提交。

## 实施完成后的下一步

先继续 M0：启动 Java 主后端，让 Java 调用 `/research/mock`，再启动网页，完成输入与演示报告展示。

完整骨架可用后进入 M1：接入模型和两三个真实资料工具，由模型选择动作、读取结果、按需补查或结束。后续在同一工作台中逐步加入真实研究与特色功能。
