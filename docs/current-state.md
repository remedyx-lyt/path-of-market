# 当前进度

## 已完成

- 创建项目目录：`Path of Market市场之路`。
- 确定项目定位：个人金融研究操作台，不做荐股和自动交易。
- 确定主模块：用户画像、板块地图、深研室、追猎者、锐眼、研究日志、数据层。
- 确定技术路线：React 前端 + Java Spring Boot 主后端 + Python FastAPI Agent 服务。
- 调整应用目录：
  - `apps/web`：前端。
  - `apps/server`：Java 主后端。
  - `apps/agent`：Python Agent 服务。
- 采用 PoE2 官方/常见命名：
  - `Deadeye / 锐眼`：个性化信号发现。
  - `Pathfinder / 追猎者`：持续追踪变化。
- 创建基础文档：
  - `README.md`
  - `docs/product-plan.md`
  - `docs/agent-concepts.md`
  - `docs/data-sources.md`
- 确定前端风格方向：黑白极简、高对比、大留白、强字体、工具感，参考 Easy Farm 页面风格。
- 新增 `docs/design-style.md` 作为后续前端任务的设计约束。
- 记录深研室的研究报告预兆设计：
  - 崇高预兆：深入解读。
  - 远古预兆：历史参照。
  - 机遇预兆：未来变化。
  - 深渊回响预兆：风险端。
  - 详细设计见 `docs/report-omens.md`。
- 已补充研究报告预兆的第一版完整约束，包括每个预兆的核心目标、适用场景、资料偏好、任务拆解要求、报告章节要求、关键问题清单、自检标准和禁止事项。

## 当前正在做

- 建立跨聊天框协作工作流。
- 补齐共享项目记忆文档。
- 准备开始第一阶段最小闭环。

## 下一步

1. 搭建 Python Agent hello world。
2. 搭建 Java Server hello world。
3. 实现 Java 调 Python 的 mock research 接口。
4. 搭建 React 前端 hello world。
5. 前端调用 Java 并展示 mock 研究报告。
6. 更新启动说明和开发记录。

## 当前约定

- 项目内说明、页面文案、注释尽量使用中文。
- 代码文件名、目录名、类名、函数名优先使用英文。
- 每次新任务先读项目文档，再动代码。
- 每次完成任务后更新本文件和 `docs/task-board.md`。
- 涉及前端页面和组件时，必须先读 `docs/design-style.md`。
