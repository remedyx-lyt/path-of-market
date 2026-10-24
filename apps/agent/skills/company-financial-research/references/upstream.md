# 原版参考与产品适配

2026-10-24 查阅；许可副本与逐文件哈希见项目 `third_party/anthropic-financial-services/`。原文件未修改；适配由本项目单独维护，不暗示上游认可。

- Anthropic [financial-services](https://github.com/anthropics/financial-services)，版本 `574ed3624aebd0418c7e96cd101262f30210ab26`，Apache-2.0。保留 equity-research 全部9个 Skill，以及 financial-analysis 的三表、清洗/核查 Excel、竞争分析、可比公司、DCF、XLSX 七个 Skill 与附带文件，共36个原版文件（含 LICENSE）。
- 核心借鉴：公司研究/数据建模/估值/图表/整合的职责分开；财报变化与同口径对比；每张表图指向具体来源。原版的篇幅、固定图数、评级与工具依赖是上游工作流选择，不是所有研究报告的统一标准。
- [证监会2025年年报内容与格式准则](https://www.csrc.gov.cn/csrc/c101954/c7547588/content.shtml)，尤其近三年主要数据、管理层业务分析、研发与现金流部分，用作资料检查清单依据。披露要求不等同于研究报告格式，也不要求照搬全部法定披露章节。
- [东吴证券中际旭创深度报告](https://pdf.dfcfw.com/pdf/H3_AP202307171592350526_1.pdf)，2023-07-17：参考图文组织方式和图表菜单，不使用其历史预测当当前事实。
- [FinRobot](https://github.com/AI4Finance-Foundation/FinRobot/tree/2717499b8e30f242640af08c4ad9afd1113c2d45)：参考工具/数据/绘图分层，未引入整套框架或直接复制运行代码。

当前程序自动加载本项目 Skill 的基本规则。需要原版细节时通过 `read_research_skill` 获取已保留的参考文件；不同场景只加载所需部分。付费数据/DCF/工作簿等未连接能力只作可读参考，不宣称已经可执行。
