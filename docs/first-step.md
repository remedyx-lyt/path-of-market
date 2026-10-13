# 第一步：Python 研究服务骨架

任务编号：M0-1。当前状态：**已完成，2026-10-13 通过实际 HTTP 验证**。

本文件记录 M0-1 已实现的接口与验收结果。Java 启动已在 M0-2 另行完成，Java 调用 Python 与网页任务仍待做；真实研究能力在 M1 中实现。

## 为什么从这里开始

研究 Agent 在 Python 服务中执行。先把服务启动和研究数据格式确定下来，后续模型、工具、Java 和网页才能围绕同一份接口接入。

服务入口已实现：`app/main.py` 注册 FastAPI 应用和接口路由，请求格式在 `app/schemas/research.py`，演示报告处理在 `app/services/workflows/mock_research.py`。

## 任务范围

1. 建立最小 FastAPI 应用和健康检查。
2. 定义研究请求与结构化报告的数据格式。
3. 提供返回演示数据的研究接口，并明确标记 `mode: mock`。
4. 补齐依赖清单和本地启动脚本。
5. 完成实际 HTTP 验证，记录结果并更新进度。

M0-1 这项任务不接真实模型、不抓行情、不建向量索引，也不实现 Java 或前端。Java 和网页属于同一 M0 阶段的后续任务；完成整条演示链路后，M1 再单独实现真实 Agent 循环。

## 已实现接口

### GET /health

确认当前 Python 应用正在运行。健康检查不能声称模型或数据源已接通。

实际返回格式：

```json
{
  "status": "ok",
  "service": "agent",
  "mode": "mock"
}
```

### POST /research/mock

请求示例：

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
- 字符串去掉首尾空白后校验。对象最多 120 字符、问题最多 2000 字符、偏好最多 500 字符、预兆最多 4 项。
- 字符串字段不接受数字、布尔或数组；不接受未知请求字段。无效请求返回 HTTP 422 和 `detail` 校验信息。

返回包含以下字段；以下内容用于说明格式，实际标题与章节会带上请求中的对象、问题和视角：

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

## 实现文件

- `apps/agent/app/main.py`：服务入口与路由注册。
- `apps/agent/app/schemas/`：研究输入和报告格式。
- `apps/agent/app/api/routes/`：健康检查与演示研究接口。
- `apps/agent/app/services/workflows/mock_research.py`：演示报告生成。
- `apps/agent/requirements.txt`：包含直接和间接依赖的固定版本清单。
- `scripts/start-agent.ps1`：从明确项目位置启动本地服务。
- `scripts/check-agent.py`：用 Python 标准库通过实际 HTTP 检查接口，不需要额外测试依赖。
- `README.md`、`docs/current-state.md`、`docs/task-board.md`：真实运行方式、验证结果和完成状态。

文件数量以必要实现为准，保持代码可读，不引入本阶段用不到的复杂框架。

## 使用方法

在项目根目录执行：

```powershell
.\scripts\start-agent.ps1
```

如果当前 PowerShell 策略阻止本地脚本，可在单独进程中运行；这不会修改系统的持久执行策略：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-agent.ps1
```

默认服务地址 `http://127.0.0.1:8000`。打开 `/docs` 可以通过交互文档发送请求，`/openapi.json` 提供接口约定。服务根地址跳转到 `/docs`。

也可以从另一个终端发送中文请求：

```powershell
$researchPayload = @{
    target = '示例公司'
    question = '如何研究它的研发投入变化？'
    userStyle = '关注长期增长和风险验证'
    omens = @('opportunity', 'abyssal_echoes')
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Uri 'http://127.0.0.1:8000/research/mock' -Method Post -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($researchPayload)) | ConvertTo-Json -Depth 10
```

运行检查脚本前先保持服务启动：

```powershell
.\apps\agent\.venv\Scripts\python.exe .\scripts\check-agent.py
```

指定端口示例：启动使用 `-Port 8001`，检查使用 `--base-url http://127.0.0.1:8001`。开发热重载使用 `-Reload`；需要按清单重装依赖使用 `-InstallDependencies`。

启动脚本使用 UTF-8 BOM，兼容本次验证的 Windows PowerShell 5.1 和包含中文、空格的项目路径。Python 已在 3.14.3 环境验证。

## 验收标准

1. 根据说明可以启动 Python 应用，默认仅监听本机 `127.0.0.1:8000`。
2. `/health` 返回 HTTP 200 和服务标识。
3. 合法研究请求返回 HTTP 200；中文对象、问题、偏好和预兆正确传递。
4. 空对象、空问题、错误类型或未知预兆有明确校验错误，不生成报告。
5. 演示报告有 mock 标记，真实来源和工具记录为空。
6. `/docs` 和 `/openapi.json` 可用于查看接口约定。
7. 更新文档后检查 diff，并保存一个明确的 M0-1 Git 提交。

## 本次验证结果

- Python 语法检查、应用导入、OpenAPI 接口定义和 `pip check` 通过。
- 从项目目录之外用 Windows PowerShell 启动脚本，成功在 `127.0.0.1:8000` 启动服务。
- 在单独的空环境副本中，启动脚本成功创建虚拟环境、安装固定版本依赖，并通过健康检查和演示研究请求；该临时验收服务已关闭。
- 20 次实际 HTTP 请求覆盖健康检查、完整中文输入、字段别名、可选默认值、首尾空白处理、15 类无效请求、接口文档和 OpenAPI；全部通过。
- 根地址访问能跳转到 `/docs`，最终返回 HTTP 200。
- 演示报告 `isMock` 为 true，来源和工具调用为空；没有接入模型或读取真实资料。
- M0-1 完成不代表 M0 完整应用骨架完成；M0-2 Java 启动已另行完成，见 `second-step.md`。

## 实施完成后的下一步

继续 M0：下一项为 M0-3，让已启动的 Java 主后端调用 `/research/mock`，再启动网页，完成输入与演示报告展示。

完整骨架可用后进入 M1：接入模型和两三个真实资料工具，由模型选择动作、读取结果、按需补查或结束。后续在同一工作台中逐步加入真实研究与特色功能。
