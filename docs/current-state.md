# 当前进度

更新时间：2026-10-13（Australia/Sydney）。

## 当前状态

本轮任务：用户明确要求第三步，完成 M0-3 Java 调用 Python。Java 可接收研究请求、交给 Python 并返回演示报告；中文、字段校验转发、连接失败、完整响应超时和异常结果已通过实际 HTTP 检查。

**已完成：M0-1、M0-2、M0-3。下一项功能任务：M0-4 React 页面启动。**

目前已跑通“HTTP 请求 → Java → Python → Java 返回演示报告”。网页和真实模型接入仍待实现。

## 已完成的规划与准备

- 项目目录：`D:\Learning\AI Lab\Vibe Coding\Path of Market市场之路`。
- 产品定位：本地网页财经研究工作台，内部包含研究 Agent；用于资料积累、变化比较和不同视角的研究。
- 应用分工：React + Vite + TypeScript 前端、Java Spring Boot 主后端、Python FastAPI 研究服务。
- 主模块：用户画像、板块地图、深研室、追猎者、锐眼、研究日志、数据层。
- 模块命名：`Deadeye / 锐眼`、`Pathfinder / 追猎者`。
- 四个研究预兆及完整研究规格已写入 `report-omens.md`：崇高、远古、机遇、深渊回响。
- 前端设计方向：黑白极简、高对比、大留白、强字体；参考图已保存在 `docs/assets/easy-farm-style-reference.png`。
- 研究 Agent 的动态工具循环和验收要求已写入 `architecture.md`、`agent-concepts.md`、`task-board.md`。
- 实施顺序已确认为 M0 完整应用骨架、M1 真实 Agent、M2 研究积累与资料完善、M3 特色功能。
- M0 内部依次完成 Python 演示服务、Java 启动与调用、网页启动与展示；先用 mock 报告跑通整条链路。
- 创建 `first-step.md`，说明第一步范围、数据格式和验收标准。
- 创建 `second-step.md`，记录 Java 主后端的启动、健康接口和第二步验收结果。
- 创建 `third-step.md`，记录 Java 调用 Python 的请求、配置、错误格式和第三步验收结果。
- 创建 `git-workflow.md`，说明本地版本保存和未来 GitHub 接入。
- 下一步实施的依据已明确：`architecture.md` 管职责边界，`task-board.md` 管顺序，`current-state.md` 管实际状态，`first-step.md`、`second-step.md`、`third-step.md` 记录已完成任务的接口与验收。

## 实际代码与环境

| 项目 | 检查结果 |
| --- | --- |
| Python 入口 | FastAPI 应用已实现，注册 `/health`、`/research/mock` 和根路径到 `/docs` 的跳转 |
| 请求与报告 | Pydantic 格式已实现，接收对象、问题、偏好与预兆；严格校验类型、空白和长度 |
| Python 环境 | Python 3.14.3，FastAPI 0.143.0、Pydantic 2.14.1、Uvicorn 0.54.0；直接与间接依赖固定在 `requirements.txt` |
| Python 验证 | 语法、依赖、应用/OpenAPI 和 20 次实际 HTTP 请求检查通过 |
| 启动与检查 | `scripts/start-agent.ps1` 和 `scripts/check-agent.py` 已实现；无需手动激活虚拟环境 |
| Java 入口 | `Application.java` 已实现 Spring Boot 启动，`pom.xml` 固定 Spring Boot 4.1.1，生成可运行 JAR |
| Java 环境 | 本机 JDK 25.0.2；源码目标 Java 21，可使用 JDK 21 或更高版本构建；Maven Wrapper 3.3.4 固定 Maven 3.10.0 并验证下载校验和 |
| Java 接口 | `GET /api/health` 检查 Java 自身；`POST /api/research/mock` 已调用 Python 并返回演示报告 |
| Java 启动与检查 | `scripts/start-server.ps1` 自动构建和启动，`scripts/check-server.ps1` 检查真实 HTTP 接口 |
| Java 与 Python | 研究 JSON 保留原始字段类型并交给 Python 校验；200 报告与 422 `detail` 转发，错误连接/响应有明确错误码 |
| 调用配置 | Python 默认地址 `http://127.0.0.1:8000`，连接超时 3 秒，完整响应等待上限 10 秒；环境变量与启动参数可覆盖 |
| 链路检查 | `scripts/check-research-bridge.py` 已实现，33 次真实服务请求与 12 次隔离故障请求通过 |
| 网页 | 只有目录占位，尚无可运行的 React 工程 |
| 模型与工具 | 尚未接入真实模型、文档检索、行情查询或研究循环 |
| 服务运行 | 本次验收时 Python 在 `127.0.0.1:8000`、Java 在 `127.0.0.1:8080` 运行；之后分别用启动脚本重新运行 |

演示报告带 `mode: mock` 和 `isMock: true`，来源与工具调用为空。M0-1 至 M0-3 完成说明两项后端服务及研究请求链路可用；网页与 M1 的真实 Agent 仍未完成。

## M0-1 验收记录

- 用 Windows PowerShell 从项目目录之外运行启动脚本，中文与空格路径可用。
- 空环境副本中自动创建虚拟环境、安装清单依赖并成功提供健康检查和演示报告。
- 健康检查、完整中文输入、字段别名、首尾空白和可选默认值通过。
- 15 类无效请求返回 HTTP 422：空/空白字段、缺少问题、错误类型、未知预兆、过长输入、过多预兆、未知字段。
- `/docs` 与 `/openapi.json` 返回 HTTP 200，服务根地址跳转到 `/docs`。
- 完整请求返回结构化演示报告，不编造资料、行情、工具记录或预兆研究完成情况。

## M0-2 验收记录

- Maven Wrapper 成功下载固定版本 Maven，Spring Boot 工程编译、打包为可运行 JAR 并启动。
- 两个 PowerShell 脚本通过 Windows PowerShell 5.1 语法检查。
- 从项目目录之外运行启动脚本，包含中文和空格的项目路径可用，默认只监听 `127.0.0.1:8080`。
- 3 次实际 HTTP 请求通过：健康接口返回 200 和约定 JSON、不存在的路由返回 404、健康接口的 POST 请求返回 405。
- 在独立工程副本中，从空 Maven Wrapper 缓存开始，并移除该测试进程的 `JAVA_HOME`；脚本从 PATH 找到已安装 JDK、下载 Maven、重新构建并在指定的 `8081` 端口启动，3 次 HTTP 检查通过。
- 临时副本的验收进程已停止；原项目 Java 服务保留运行。
- 本轮没有添加数据库、Python 调用、前端或模型依赖。

## M0-3 验收记录

- Spring Boot 工程编译、打包、重启通过，Python 服务保持运行。
- 检查脚本向真实服务发出 33 次 HTTP 请求：包含 4 组正常请求与直接调用 Python 的结果对比、18 类字段/根对象校验、完整 422 错误内容对比、非法/空 JSON、媒体类型和 HTTP 方法。
- 正常请求覆盖中文对象/问题/偏好、四个预兆、首尾空白、可选默认值和 Unicode 字符数量边界；Java 返回报告与 Python 相同。
- 在临时 Java 实例与本地模拟服务中发出 12 次故障验收请求：上游错误、重定向、非 JSON、错误报告、错误校验格式、响应头超时、正文超时、断线、422 转发、恢复、连接拒绝和独立健康检查。
- 故障响应区分 503 `AGENT_UNAVAILABLE`、504 `AGENT_TIMEOUT`、502 `AGENT_ERROR` / `AGENT_INVALID_RESPONSE`；非法或缺少 JSON 返回 400 `INVALID_JSON`。
- 两种超时都在配置上限附近结束等待；不会转发上游内部错误正文。
- Windows PowerShell 5.1 启动参数在临时工程副本中通过：从项目外启动，显式地址/等待上限覆盖环境配置，地址末尾斜线正确处理，中文研究请求成功；临时进程已关闭。
- 临时 Java 与故障服务已关闭，原项目 Python/Java 保留运行。
- 本轮未修改 Python 的研究逻辑，未实现网页、模型、行情或真实资料工具。

## Git 状态

- 已在项目目录初始化本地仓库，分支为 `main`。
- 原有规划与目录骨架已保存为基线提交 `09eb2b1`。
- 架构与验收补充保存在 `6dca578`，恢复原闭环和统一任务依据保存在 `8da7ae5`。
- M0-1 的代码、运行说明和进度更新保存为同一个功能提交，标识以 `git log` 为准。
- M0-2 的 Java 工程、Wrapper、脚本、运行说明和进度更新保存为一个独立功能提交，标识以 `git log` 为准。
- M0-3 的调用客户端、接口、配置、错误处理、检查脚本和文档保存为一个独立功能提交，标识以 `git log` 为准。
- `.gitignore` 排除虚拟环境、密钥文件、构建缓存、上传资料、向量索引、研究运行结果和本地数据库。
- `.env.example`、源代码、项目文档和前端设计参考图纳入版本管理。
- 当前没有配置 remote，保存的是本地 Git 历史，未进行推送。

## 下一步

1. M0-4：按 `design-style.md` 启动 React 基础研究页面，填写对象和问题。
2. M0-5：网页调用 Java，展示 Python 返回的演示报告及明确的错误状态。
3. M0-6：补完整应用启动说明，再进入 M1 的真实模型和资料工具。
4. 逐步加入研究记录、用户画像、板块地图、追猎者和锐眼。

## 当前约定

- 项目说明、页面文案和必要注释尽量使用中文；代码标识优先使用英文。
- 已有 React、Java、Python 分工继续作为架构边界。
- 每次只完成一个明确任务；完成情况按实际检查结果记录。
- 用户要求只规划或等待时，只进行当前已授权的工作。
- 每个功能任务完成后及时更新本文件和 `task-board.md`，并保存相应 Git 提交。
- 涉及前端时先读 `design-style.md`。
- M0 演示报告和 M1 真实 Agent 分开验收，不虚构工具执行、来源或预兆覆盖情况。
