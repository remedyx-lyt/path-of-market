# 第四步：React 深研室页面

任务编号：M0-4。状态：**已完成，2026-10-13 构建与浏览器检查通过，断网后复查通过**。

本文件记录第四步的页面基础。后续 M0-5 已接通报告生成按钮，当前使用方式见 `fifth-step.md`；下一项为 M0-6。

## 当前可用内容

- 研究对象、研究问题的必填输入框。
- 可展开的研究偏好与四种预兆，支持多选。
- 填入示例、清空、本地任务预览。
- 空白与长度检查、明确错误提示、定位首个错误字段。
- 桌面左右分栏、手机上下分区，黑白布局与深色摘要面板。

M0-4 的预览操作只整理页面摘要。当前页面保留“预览任务”，并在 M0-5 新增实际调用后端的“生成演示报告”。修改输入会使旧结果失效。草稿存在页面状态中，刷新会清空；持久化属于后续任务。

没有报告时明确显示“报告尚未生成”；M0-5 已接通网页 → Java → Python 的报告调用。

## 启动

在项目根目录执行：

```powershell
.\scripts\start-web.ps1
```

打开 `http://127.0.0.1:5173`。表单与任务预览无需后端；当前“生成演示报告”需 Java 和 Python 同时运行，见 `fifth-step.md`。按 Ctrl+C 停止网页服务。

如果本地 PowerShell 策略阻止脚本，使用单独进程，不修改系统的持久策略：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-web.ps1
```

缺少依赖时脚本自动运行 `npm ci`，按照 `apps/web/package-lock.json` 安装。已有依赖需要重装时使用 `-InstallDependencies`，指定端口使用 `-Port 5174`。默认只监听 `127.0.0.1`，端口冲突时报错，不会悄悄换端口。

## 输入规则

| 字段 | 规则 |
| --- | --- |
| `target` | 必填，去掉首尾空白后最多 120 个 Unicode 码点 |
| `question` | 必填，去掉首尾空白后最多 2000 个 Unicode 码点 |
| `userStyle` | 选填，最多 500 个 Unicode 码点 |
| `omens` | 选填，四个枚举选项的组合 |

使用 Unicode 码点计数，不将非 BMP 字符计为两个；不会为限制长度自动截断用户输入。预览会去掉首尾空白。可选区域收起时若偏好超长，会自动展开并定位该字段。

四种预兆使用后端既有标识：`exalted`、`ancient`、`opportunity`、`abyssal_echoes`。本轮只收集并显示配置，未执行真实研究策略。M0-5 的接口输入仍由 Python 做最终校验。

## 工程与依赖

`apps/web` 使用 React + Vite + TypeScript。直接依赖固定版本，完整依赖由 `package-lock.json` 锁定。当前验证环境为 Node.js 24.13.1、npm 11.8.0。

- React / React DOM：19.3.0。
- Vite：8.3.4。
- TypeScript：7.0.2。
- `@vitejs/plugin-react`：6.1.2。

Node.js 版本要求以 `package.json` 的 `engines` 为准。工程配置参考 [Vite 官方入门说明](https://vite.dev/guide/) 与 [React TypeScript 文档](https://react.dev/learn/typescript)。

在 `apps/web` 下执行：

```powershell
npm.cmd run check
npm.cmd run build
```

`build` 已包含类型检查，再生成 `dist/` 静态文件。本轮已经运行 build，无需为了交付重复安装或构建。`node_modules/` 与 `dist/` 按现有 Git 规则忽略。

## 文件分工

| 文件 | 作用 |
| --- | --- |
| `apps/web/package.json`、`package-lock.json` | 依赖版本与构建命令 |
| `apps/web/index.html`、`src/main.tsx` | HTML 与 React 入口 |
| `apps/web/vite.config.ts`、`tsconfig.json`、`src/vite-env.d.ts` | 开发服务器、类型检查与资源类型 |
| `apps/web/src/app/App.tsx` | 页头、页面入口与页脚 |
| `apps/web/src/features/research-lab/ResearchWorkspace.tsx` | 表单和页面操作 |
| `apps/web/src/features/research-lab/ResearchPreview.tsx` | 本地任务摘要与报告占位 |
| `apps/web/src/features/research-lab/researchDraft.ts` | 草稿类型、预兆、输入整理与检查 |
| `apps/web/src/styles/global.css` | 黑白视觉、表单、响应式布局和焦点样式 |
| `scripts/start-web.ps1` | 定位项目、按锁文件安装依赖、启动网页 |

## 验证与复查

- 依赖安装、TypeScript 类型检查与 Vite 生产构建通过。
- 页面和 favicon 可正常加载，Chrome 无运行或控制台错误。
- 11 组浏览器检查通过：初始渲染、空白输入与焦点、示例与预览、编辑后预览失效与空白处理、选填展开与四个预兆、偏好长度与隐藏错误定位、Unicode 长度、问题长度、清空、响应式布局、浏览器错误与后端请求检查。
- 1440、768、375、320 像素宽度无横向溢出，展开选填区时也通过；桌面和手机截图已实际查看。
- 页面交互未发送后端 API 请求，符合当前 M0-4 范围。
- Windows PowerShell 5.1 语法、项目外启动、中文与空格路径通过。
- 在没有 `node_modules` 的工程副本中，脚本按锁文件自动安装并在指定端口返回页面与已转换 React 模块；临时服务已关闭。
- 用户报告网络中断后重新检查：网页 HTTP 200、依赖完整、11 组浏览器检查再次通过。未发现中断造成的文件缺失或交互故障。

## 后续：M0-5 已完成，下一项 M0-6

网页报告接入及错误、超时、取消已完成，详见 `fifth-step.md`。下一项 M0-6 整理整体启动与验收说明。
