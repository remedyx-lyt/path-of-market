# 第六步：整套应用的启动、停止与检查

任务编号：M0-6。状态：**已完成，2026-10-16 统一启动、停止、完整链路与恢复检查通过**。

## 三个服务是什么

| 服务 | 地址 | 负责什么 |
| --- | --- | --- |
| React 网页（web） | http://127.0.0.1:5173/ | 输入研究对象、问题和偏好，展示研究报告 |
| Java 主后端（server） | http://127.0.0.1:8080/api/health | 接收网页请求，调用 Python，再把报告交给网页 |
| Python 研究服务（agent） | http://127.0.0.1:8000/docs | 执行研究任务；当前返回演示报告，后续接模型、资料和工具 |

使用时只打开网页。三个服务均运行在自己的电脑上，演示模式无需数据库、Docker 或模型 API Key。后续 M1-1 已增加模型分析，密钥配置见 `m1-1-model.md`。

```text
浏览器 → React 网页的 /api 代理 → Java 主后端 → Python 研究服务
浏览器 ← 网页展示报告          ← Java 返回    ← 结构化演示报告
```

## 平时只用这三个命令

打开 PowerShell，先进入项目目录：

```powershell
Set-Location 'D:\Learning\AI Lab\Vibe Coding\Path of Market市场之路'
```

启动整套应用：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-app.ps1
```

看到“全部 4 项基础检查通过”和“整套应用已启动”后，打开 http://127.0.0.1:5173/ 。点击“填入示例 → 生成演示报告”。启动命令返回后可以关闭终端；服务在后台运行，电脑重启后需要重新启动。

检查是否正常：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-app.ps1
```

停止整套应用：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-app.ps1
```

命令中的 `Bypass` 仅应用于这次脚本进程，不修改电脑的全局执行策略。脚本根据自身位置寻找项目，从其他目录用脚本的完整路径运行也可以。

## 首次运行需要什么

| 环境 | 当前要求与本机验证版本 |
| --- | --- |
| Python | 本机 Python 3.14.3 已验证，`python` 可从 PATH 调用；虚拟环境由脚本创建 |
| Node.js / npm | 项目声明 Node.js `^20.19.0 || >=22.12.0`；本机 Node.js 24.13.1、npm 11.8.0 已验证，使用 `npm.cmd` |
| JDK | JDK 21 或更高；本机 JDK 25.0.2 已验证，`javac` 可从 PATH 调用，`JAVA_HOME` 如设置则应指向该 JDK |
| Maven | 不要求全局安装；已有 Maven Wrapper 固定版本并校验下载 |
| 网络 | 首次下载 Python、网页和 Maven 依赖时需要；当前演示请求不依赖外部财经或模型 API |

统一启动会调用已有三个独立启动脚本。Python 虚拟环境、网页依赖缺少时会安装，Java 每次先构建再启动。默认最多等待 600 秒；下载慢时可以延长：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-app.ps1 -StartupTimeoutSec 1200
```

需要按清单重新安装 Python 和网页依赖时，先停止服务，再启动并加 `-InstallDependencies`。该参数不重新下载 JDK 或 Node.js。

统一入口固定使用 8000、8080、5173，显式连接本机对应服务；不依赖父终端遗留的 `AGENT_BASE_URL`、`AGENT_REQUEST_TIMEOUT` 或 `JAVA_SERVER_URL`。需要自定义端口时使用下方独立调试方式。

## 启动脚本会做什么

1. 获取独占运行锁，避免同时启动或停止；读取本项目的启动记录；三个受管服务已经运行时只检查，不重复创建。
2. 有部分服务残留时提示先停止再启动；已有端口被其他程序或单独启动的服务使用时退出，不接管或结束它们。
3. 检查基础命令，后台启动三个已有脚本，将输出写入 `.runtime/logs/`。
4. 记录包装脚本的 PID、创建时间、可执行文件和脚本路径，等待三个 HTTP 服务就绪。
5. 从网页地址发送中文研究请求，验证整个链路后才报告成功。
6. 本次启动失败或超时时清理本次创建的进程，保留日志。

停止时先验证进程身份，再停止其子进程和包装脚本，不按 `java`、`python` 或 `node` 进程名批量结束。没有启动记录时不处理单独运行的服务。身份与记录不符时会拒绝操作，需要先核对记录和实际进程。

`.runtime/app-state.json` 与日志是本机运行信息，已排除在 Git 之外。每次新启动会替换同名日志；需要保留故障记录时先复制日志。后台服务不会自动随电脑开机启动，也没有故障自动重启功能。

## 检查通过意味着什么

`check-app.ps1` 检查四项：

1. Python `/health` 返回 `ok / agent / mock`。
2. Java `/api/health` 返回 `ok / server`。
3. 网页返回带 React 根节点的 HTML。
4. 向网页的 `/api/research/mock` 提交中文任务，核对报告的演示标记、对象、问题、偏好、预兆、三个章节，以及为空的真实来源和工具记录。

第四项经过真实 HTTP 调用，覆盖网页代理 → Java → Python。Windows PowerShell 5.1 检查脚本按 UTF-8 读取 JSON 原始字节，避免其默认字符集使中文对比失败。HTML/API 检查不能代替浏览器渲染检查；界面操作按“填入示例 → 生成演示报告”确认。

这四项基础检查使用演示报告，只确认应用骨架正常，不调用模型账户。M1-1 已另行接入并验证真实模型，配置和主动调用检查见 `m1-1-model.md`；财报检索与 Agent 工具循环仍在之后实现。

## 常见问题

| 现象 | 怎么处理 |
| --- | --- |
| 网页打不开 / 连接被拒绝 | 运行统一启动；如果仍失败，查看相应服务日志 |
| 页面能开，报告生成失败 | 运行 `check-app.ps1`，看哪个服务或完整链路失败 |
| 端口被占用 | 如之前在三个终端单独启动过，先分别 Ctrl+C；统一入口不会结束这些进程 |
| 提示无法取得运行锁 | 等待另一条启动或停止命令完成；确认没有其他操作时检查 `.runtime` 写入权限 |
| 提示只有部分服务运行 | 先运行 `stop-app.ps1`，再运行 `start-app.ps1` |
| 缺少 python / npm.cmd / javac | 检查环境是否安装、PATH 和 JAVA_HOME；环境变量修改后重开终端 |
| 首次下载慢或失败 | 检查网络和具体日志，必要时延长等待；失败后修复再启动 |
| 重启电脑后页面不能用了 | 重新运行 `start-app.ps1`；这不是已部署到云端的应用 |
| 刷新后输入和报告消失 | 当前数据只保存在页面内；研究记录持久化在 M2 实现 |

查看最近日志：

```powershell
Get-Content .\.runtime\logs\agent.err.log -Tail 40
Get-Content .\.runtime\logs\server.out.log -Tail 40
Get-Content .\.runtime\logs\server.err.log -Tail 40
Get-Content .\.runtime\logs\web.out.log -Tail 40
Get-Content .\.runtime\logs\web.err.log -Tail 40
```

有些服务会把正常启动消息写到 err 日志，仅凭文件非空不能判断失败。先看健康检查和错误正文。

只读查看端口占用，不会结束进程：

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8000,8080,5173 -ErrorAction SilentlyContinue |
    Select-Object LocalAddress,LocalPort,OwningProcess
```

## 开发时单独启动

需要实时看日志或改某个服务时，先停止统一启动的应用，再在三个终端分别运行：

```powershell
.\scripts\start-agent.ps1
```

```powershell
.\scripts\start-server.ps1
```

```powershell
.\scripts\start-web.ps1
```

在各终端按 Ctrl+C 停止；仍可运行 `check-app.ps1` 检查默认端口，但 `stop-app.ps1` 不管理这些独立进程。执行策略限制时也可像统一入口一样用 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File` 运行。

独立脚本支持的端口、重载、依赖和调用参数见 `first-step.md`、`second-step.md`、`third-step.md`、`fourth-step.md`、`fifth-step.md`。三方自定义端口必须相互对应；统一检查仅检查默认端口。

## 文件分工

| 文件 | 作用 |
| --- | --- |
| `scripts/start-app.ps1` | 统一启动、等待就绪、完整检查与失败清理 |
| `scripts/stop-app.ps1` | 停止由统一入口记录的服务 |
| `scripts/check-app.ps1` | 三个 HTTP 服务与网页研究链路检查 |
| `scripts/app-common.ps1` | 固定服务定义、状态文件、进程身份检查与清理 |
| `.runtime/` | 忽略提交的本地状态和日志 |

## 验收记录

- 全部 8 个 PowerShell 脚本通过 Windows PowerShell 5.1 语法检查；新增脚本使用 UTF-8 BOM，中文和空格路径可用。
- 从项目目录之外统一启动三个服务，Java 重新构建成功；启动终端正常退出后，后台服务继续提供网页和报告。
- 4 项整套应用检查通过：Python 健康、Java 健康、网页 HTML、经过网页代理的中文研究请求与完整演示参数。
- 重复启动保持原有三个包装进程和启动记录不变；停止后 8000、8080、5173 均释放，记录移除，再次停止正常返回。
- 独占运行锁阻止同时启动或停止覆盖记录；锁占用时两种操作均拒绝执行，服务和记录不变，释放后可再次使用。
- 对已由独立终端启动的服务，统一入口检测端口冲突并退出，没有结束原服务。
- 无效 JAVA_HOME 导致启动失败时，仅本次创建的服务被清理，端口和记录没有残留，错误日志保留。
- 临时改变启动记录中的创建时间时，停止命令拒绝操作，三个服务继续运行；测试后恢复原记录。
- 单个受管服务退出时，重复启动提示先停止；停止剩余服务后可重新完整启动。
- 父进程遗留错误的 Python 研究服务地址、1ms 研究等待上限和网页 Java 目标地址时，统一入口显式配置仍使完整链路通过。
- 最终 Chrome 浏览器中“填入示例 → 生成演示报告”通过，返回 200，三个实际报告章节均显示，无未处理页面错误。
- 最终保留统一入口启动的三个本机服务；日志和进程记录位于忽略提交的 `.runtime/`。

## 下一项

M1-1 模型接口与研究状态已于 2026-10-23 完成，见 `m1-1-model.md`。当前下一项为 M1-2 真实资料与工具，沿用既定三服务架构。
