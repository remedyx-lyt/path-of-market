# 公司财务研究 Skill、原页视觉与财务表图

更新：2026-10-24（Australia/Sydney）。本轮按用户要求，优先完善公司年报研究的基本质量，再继续 M1-4。保留既有 React → Java → Python 架构，没有把原版金融插件整体安装到 Codex，也没有迁移到其他 Agent 框架。

后续同日扩展：本页记录首次四类财务表图交付。当前已进一步增加按任务完整阅读相关原版方法、方法计划/复核、正文取数、业务分部/研发/资产负债数据与模型逐章选图；六个逻辑工具、八个底层工具。最新机制与边界见 [方法实际使用与按论点选图](methods-and-section-figures.md)，不能再把下文历史四类图当成当前全部能力。

## 基本产品要求

用户有手工把财报数据录入 Excel、计算同比并制图的经历，希望产品自动完成这条链路，而且不能一直停留在文字摘要。基本公司研究要回答：公司做什么业务、收入和利润如何变化、增长由什么驱动、现金流是否支持利润、资产负债有何压力、研发与经营投入怎样、有哪些风险和待验证项。图表用于支持这些判断，不以数量代替分析质量。

研究菜单与事实数据分开：Skill 描述研究方法和要求；工具找资料/读图/取数；程序做计算和绘图；模型解释证据。写好 Skill 不会自动接通某个付费数据服务或 Excel/PDF 工作流。

## 查阅与直接保留的上游

| 来源 | 核对内容 | 本项目采用方式 |
| --- | --- | --- |
| [Anthropic financial-services](https://github.com/anthropics/financial-services/tree/574ed3624aebd0418c7e96cd101262f30210ab26) | 公司研究、财报变化、三表/模型、图表和报告整合；每张表图的来源 | 按用户要求直接保留相关原版 Skill 与参考文件，另写 A 股/产品适配层 |
| [证监会年报内容与格式准则，2025版](https://www.csrc.gov.cn/csrc/c101954/c7547588/content.shtml) | 近三年主要会计数据、业务与管理层讨论、研发、现金流及重大变化解释 | 用于研究资料清单，不能把披露规范说成证券研究报告的统一格式 |
| [东吴证券中际旭创深度报告，2023-07-17](https://pdf.dfcfw.com/pdf/H3_AP202307171592350526_1.pdf) | 业务、营收/利润与同比、利润率、产品结构、研发等图文组织 | 参考呈现方式；不把该历史研报的预测当当前事实 |
| [FinRobot](https://github.com/AI4Finance-Foundation/FinRobot/tree/2717499b8e30f242640af08c4ad9afd1113c2d45) | 财务分析/查询/画图分层与年度报告示例 | 参考程序分工，未复制其运行代码或引入 AutoGen 等框架 |
| [DeepSeek Vision](https://api-docs.deepseek.com/guides/vision/) | `deepseek-flash` 图片输入、content 数组与 image_url | 把实际 PDF 页转 PNG，使用本地已有模型配置发送图片，记录实际视觉范围 |

### 原版文件的位置与许可

`third_party/anthropic-financial-services/` 保留固定版本 `574ed3624aebd0418c7e96cd101262f30210ab26` 的 **36 个原始文件**，包括根 LICENSE；`UPSTREAM.json` 记录 Git blob 与 SHA-256，`NOTICE.md` 说明来源与本项目适配。原始文件逐字节保留，`.gitattributes` 禁止对副本自动转换换行。上游根目录未见 NOTICE，未虚构上游署名文件。

共 **16 个原版 Skill**：

- equity-research 九个：`initiating-coverage`、`earnings-analysis`、`earnings-preview`、`model-update`、`sector-overview`、`thesis-tracker`、`catalyst-calendar`、`idea-generation`、`morning-note`。
- financial-analysis 七个：`3-statement-model`、`clean-data-xls`、`audit-xls`、`competitive-analysis`、`comps-analysis`、`dcf-model`、`xlsx-author`。

其余内部 Skill 创建器、并购/LBO、PPT 模板等没有因为“金融相关”就全部塞入当前产品。保留的估值/工作簿/晨报等内容是可读方法库，不代表依赖的工具、数据与脚本已可执行。第三方脚本没有自动运行，也没有按其 requirements 安装依赖。

## 本项目的可加载 Skill

入口：`apps/agent/skills/company-financial-research/SKILL.md`。

- `references/metrics-and-charts.md`：指标、同比、期间、负/零基数、表图与引用检查。
- `references/upstream.md`：参考来源和上游到本产品的适配边界。
- `app/core/research_skills.py`：固定注册、加载和哈希版本、参考白名单与分段读取。

每次研究实际加载本项目 Skill 的规则与指标参考，同时加载原版 `earnings-analysis/SKILL.md` 方法资料。模型可通过 `read_research_skill` 查看其余保留文件；超长参考按 `offset/nextOffset` 继续。不会每次把 36 个文件全部塞进上下文。报告带 Skill 名称、版本和上游标识，便于核对哪版规范生效。

主产品规则优先于参考资料里的环境约定：不照搬 Claude 专属工具、强制 Word 字体/页数、逐子任务确认、买卖评级或付费数据要求。缺少预测/一致预期/估值工具时标记缺口。原版方法不能授权交易、发送消息或外部发布。

综合报告用章节 `topics` 标记业务、业绩、盈利、现金流、资产负债、研发/投入、风险七类；最终校验要求覆盖或在相关章节明确缺口。它检查结构与遗漏，不证明每个判断都专业正确；不把“有标题”当成完整质量审计。

## 新增/更新的模型工具

本文写作时主模型共五个逻辑工具（之后新增 `extract_report_data`，当前六个，见 `m1-4-omens.md`）：

| 工具 | 作用 | 程序入口 |
| --- | --- | --- |
| `find_documents` | 自动发现完整年报/中报/季报 | `app/tools/cninfo.py` |
| `read_document` | 连续分批全文文字处理；完成后自动定位主要会计数据原页并尝试视觉取数 | `services/agent_runner.py:read` / `financial_summary` |
| `get_market_data` | 日线与确定性行情计算 | `app/tools/market.py` |
| 新增 `inspect_document_pages` | 主动查看 1–3 个实际 PDF 物理页图像，理解图表/列序/单位，返回观察与可核对数值 | `agent_runner.py:inspect`、`schemas/financial.py` |
| 新增 `read_research_skill` | 读取保留的原版研究方法，白名单限制路径、核对哈希、支持分页 | `core/research_skills.py:read_reference` |

底层注册表新增第八个工具 `render_document_pages`，在 `app/tools/visuals.py`：仅渲染，不把“生成 PNG”叫作“模型已看懂”。它只接受已校验文档 ID 与正整数页码，固定 Poppler 命令参数，单页最长边 1800、30 秒渲染边界、PNG 4MB 边界，并检查图片头与尺寸。无任意磁盘路径、Shell 或任意 URL 执行。

## 原页视觉如何生效

1. 文本仍按 M1-3 全部分批处理。自动财务路径从前 40 页中找含主要会计数据与收入/利润/现金流的页，不写死某家公司第八页。
2. 下载/缓存校验后，Poppler 将指定物理页渲染为 PNG。
3. **图片原页实际发送给模型，视觉请求不附带整页提取文字**，以免将文字解析误称为读图。返回各页观察、疑问和原始财务数值。
4. 检查页码与格式；财务数字再与同一页可提取文字匹配，单位要能由行标签或全局单位声明确认。金额不匹配/单位不明/期间不符的点不进入图表，记录缺口。
5. 图片缓存和视觉结果缓存都有来源键、原运行 ID、模型和图片哈希；复用明确标记。只记录已处理的图片页，不把全文文字完成率当视觉覆盖率。

目前扫描页可以尝试视觉描述，但没有文本可对照的金额不会进入自动核对图表；它需要后续独立复核能力。局部原页视觉不等于全本每张图片都理解，也不是独立财务审计。未声明视觉能力的实际配置模型返回明确限制；默认本地 `deepseek-flash` 已实际验证。

默认每轮最多 12 个不同视觉页，沿用模型调用/token/时间边界；图片字节与文字上下文分别限制，图像 token 仍计入实际供应商用量。Poppler 是当前本机已有的运行工具；其他电脑需让 `pdftoppm` 位于 PATH，否则明确返回缺少渲染器。

## 财务底稿和图表

`services/financial_data.py` 保留标准化金额（元）、期间、来源、物理页、原始数值和单位；目前结构化支持营收、归母/扣非利润、经营现金流、总资产、归母净资产、研发费用。实际自动摘要页能取得六项主数据；研发/业务分部/毛利率/费用等并非都已自动提取，仍需原文分析与后续工具扩展。

程序负责单位换算、同比、归母净利率、来源冲突和绘图数据，不接受模型算出的最终同比或任意绘图代码：

- 年度、上半年、一季度、前三季度分组；流量指标不能在半年表中伪装全年。资产是期末存量，不能把“上年度末”当上年同期末。
- 正基数同比 `(本期/上年同期间-1)*100%`；上年缺失/零/负值留空并说明，不补成零。缺少基数的折线点不连接成虚构趋势。
- 同一指标同期间多个来源值不同，默认排除冲突，保留缺口；当前尚未自动识别所有财务重述的可优先口径。
- 归母净利率为归母利润/营收，不冒充合并净利润率；经营现金流与归母利润的归属口径差异在页面说明。

网页 `FinancialCharts.tsx` 使用同一底稿生成营收柱图、营收/归母利润同比线图、归母利润与经营现金流分组柱图、归母净利率线图。年度/半年独立切换，表格显示金额与同比，每个金额有原始金额/单位/页码链接。`ReportText.tsx` 安全呈现段落与加粗，不执行模型 HTML。

真实研究页改为更宽的白色报告区、有目录与段落间距；原预览/mock/model 格式兼容，原行情图仍可切价格口径和日期。通用报告块、任意图型、Excel 导出与业务分部图还没有完成。

## 上下文与成本

首次完整联调暴露重复返回底稿导致 `context_budget`，已保留部分结果并修复 `AgentRunner.context`：旧工具结果去除重复 financialData，只保留有来源的有限阅读投影，再传一份当前底稿和视觉覆盖。完整批次记录仍在运行状态/派生缓存中，可按页回查。

这属于确定性的上下文投影，不是 M2 的自动历史 compaction、分支上下文或会话落盘。没有为了通过验收直接提高上下文上限。真实视觉探测与完整研究调用账户并计费，离线测试与查看已完成链接不创建付费模型任务。

## 学习入口

按这个顺序读代码：`research_skills.py` → `agent_prompts.py:initial_messages` → `agent_runner.py:read/inspect/context` → `visuals.py` → `financial_data.py` → `FinancialCharts.tsx`。先看“规则怎样送给模型”，再看“图片怎样发送”，最后看“数字怎样变成图”。

本轮检查与最终真实案例 ID 记录在 `current-state.md`；原版文件的完整清单以 `UPSTREAM.json` 为准。
