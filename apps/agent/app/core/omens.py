"""研究预兆的结构化规格（来源：docs/report-omens.md），以及按问题/预兆选择研究方法 Skill。

预兆是研究策略配置，不是独立模型：它进入方法计划（专属检查与 Skill）、主循环上下文（资料偏好与工具提示）、
写作要求（专属章节与 omenCoverage）和程序自检（章节标记、关键要素、能力缺口）。
"""

from dataclasses import dataclass, field

PREFIX = "plugins/vertical-plugins/equity-research/skills/"
FIN = "plugins/vertical-plugins/financial-analysis/skills/"

# 方法参考的固定顺序：基础方法在前，问题/预兆追加的在后。顺序固定使方法计划请求的开头尽量相同，
# DeepSeek 前缀缓存可在不同研究之间命中（命中部分约为未命中价格的 1/50）。
CANONICAL_METHODS = (
    PREFIX + "initiating-coverage/references/task1-company-research.md",
    PREFIX + "initiating-coverage/references/task4-chart-generation.md",
    PREFIX + "initiating-coverage/assets/quality-checklist.md",
    PREFIX + "thesis-tracker/SKILL.md",
    PREFIX + "earnings-analysis/references/workflow.md",
    PREFIX + "earnings-analysis/references/best-practices.md",
    FIN + "competitive-analysis/SKILL.md",
    FIN + "competitive-analysis/references/frameworks.md",
    PREFIX + "sector-overview/SKILL.md",
    PREFIX + "catalyst-calendar/SKILL.md",
    PREFIX + "earnings-preview/SKILL.md",
    PREFIX + "idea-generation/SKILL.md",
    PREFIX + "model-update/SKILL.md",
    PREFIX + "initiating-coverage/references/valuation-methodologies.md",
)

# 给主循环模型看的 Skill 目录（中文一句话用途 + 在本应用中的可用程度），让它知道还能按需读哪些方法。
SKILL_CATALOG = [
    ("earnings-analysis", PREFIX + "earnings-analysis/SKILL.md", "财报/业绩解读：关键指标、驱动因素、与前期对比（已默认加载）。"),
    ("initiating-coverage", PREFIX + "initiating-coverage/SKILL.md", "首次覆盖深度研究五步法；本应用只用公司研究、图表与质量检查部分。"),
    ("thesis-tracker", PREFIX + "thesis-tracker/SKILL.md", "投资论点与关键假设跟踪：哪些数据会证实或推翻论点。"),
    ("competitive-analysis", FIN + "competitive-analysis/SKILL.md", "竞争格局、同行对比、定位与护城河框架。"),
    ("sector-overview", PREFIX + "sector-overview/SKILL.md", "行业/板块全景：市场结构、主要参与者、周期与主题趋势。"),
    ("catalyst-calendar", PREFIX + "catalyst-calendar/SKILL.md", "未来催化事件梳理：产品、产能、政策、业绩发布等时间点。"),
    ("earnings-preview", PREFIX + "earnings-preview/SKILL.md", "业绩前瞻：情景框架（保守/中性/乐观）与需要关注的指标。"),
    ("idea-generation", PREFIX + "idea-generation/SKILL.md", "线索发现与主题筛选思路；本应用无全市场筛选数据，只作方法参考。"),
    ("model-update", PREFIX + "model-update/SKILL.md", "新数据出现后如何更新假设并标记重大变化。"),
    ("morning-note", PREFIX + "morning-note/SKILL.md", "晨会简报写法；通常不适用于深度报告。"),
    ("comps-analysis", FIN + "comps-analysis/SKILL.md", "可比公司估值；本应用暂无可比估值数据，只能作方法参考。"),
    ("dcf-model", FIN + "dcf-model/SKILL.md", "DCF 估值；本应用无一致预期/估值输入，不执行，只作参考。"),
    ("3-statement-model", FIN + "3-statement-model/SKILL.md", "三表模型；本应用不生成 Excel 模型，只作参考。"),
    ("audit-xls / clean-data-xls / xlsx-author", FIN + "audit-xls/SKILL.md", "Excel 审计/清洗/生成；本应用不适用。"),
]

# 问题意图 → 追加的方法。没有选预兆时，也会按研究问题选到相关 Skill。
INTENT_METHODS = (
    (
        ("财务", "业绩", "经营", "情况", "年报", "变化", "季度", "利润", "收入", "现金"),
        (PREFIX + "earnings-analysis/references/workflow.md",),
        "业绩/经营问题",
    ),
    (
        ("竞品", "竞争", "同行", "行业对比", "份额", "护城河", "对手"),
        (FIN + "competitive-analysis/SKILL.md", FIN + "competitive-analysis/references/frameworks.md"),
        "竞争格局问题",
    ),
    (("行业", "板块", "产业链", "赛道", "周期"), (PREFIX + "sector-overview/SKILL.md",), "行业/周期问题"),
    (("催化", "事件", "展望", "未来", "计划", "指引", "产能", "订单"), (PREFIX + "catalyst-calendar/SKILL.md",), "未来变化/催化问题"),
    (("预期", "预测", "下一季", "前瞻"), (PREFIX + "earnings-preview/SKILL.md",), "业绩前瞻问题"),
    (("机会", "线索", "选股", "主题"), (PREFIX + "idea-generation/SKILL.md",), "线索发现问题"),
    (
        ("估值", "市值", "市盈", "PE", "DCF", "贵", "便宜"),
        (PREFIX + "initiating-coverage/references/valuation-methodologies.md",),
        "估值问题（仅方法参考）",
    ),
)


@dataclass(frozen=True)
class OmenSpec:
    id: str
    name: str
    goal: str
    methods: tuple[str, ...]
    data_preferences: tuple[str, ...]
    tool_hints: tuple[str, ...]
    required_sections: tuple[str, ...]
    key_questions: tuple[str, ...]
    self_checks: tuple[str, ...]
    forbidden: tuple[str, ...]
    # 程序可检查的最低要素：(说明, 任一关键词)；未出现时自动记入 missingItems，不直接拒绝报告。
    required_terms: tuple[tuple[str, tuple[str, ...]], ...] = ()
    # 当前工具做不到的资料需求，必须如实写成缺口（M2-7 公开信息搜索后可补）。
    capability_gaps: tuple[str, ...] = field(default=())

    def brief(self):
        return {
            "id": self.id,
            "name": self.name,
            "goal": self.goal,
            "dataPreferences": list(self.data_preferences),
            "toolHints": list(self.tool_hints),
            "requiredSections": list(self.required_sections),
            "keyQuestions": list(self.key_questions),
            "selfChecks": list(self.self_checks),
            "forbidden": list(self.forbidden),
            "capabilityGaps": list(self.capability_gaps),
        }


OMENS = {
    "exalted": OmenSpec(
        id="exalted",
        name="崇高预兆",
        goal="从知道公司是什么升级到理解它为什么这样运转：商业模式、利润结构、财务质量、竞争优势与关键指标含义。",
        methods=(
            FIN + "competitive-analysis/SKILL.md",
            FIN + "competitive-analysis/references/frameworks.md",
            PREFIX + "earnings-analysis/references/best-practices.md",
        ),
        data_preferences=("年报/半年报的管理层讨论与分析", "分部收入、毛利率、费用率", "现金流、资本开支、负债结构", "客户/供应商集中度"),
        tool_hints=(
            "用 extract_report_data 补齐分产品/地区收入、营业成本与研发投入",
            "对复杂分部表或客户集中度表用 inspect_document_pages 核对",
            "用 search 回查 竞争/市场地位/核心技术 等原文",
        ),
        required_sections=(
            "商业模式拆解",
            "利润与现金流驱动因素",
            "竞争格局与护城河",
            "关键指标解释",
            "财务质量观察",
            "仍需继续验证的问题",
        ),
        key_questions=(
            "公司如何赚钱？",
            "收入增长靠价格、销量、渗透率、周期、并购还是新业务？",
            "毛利率和净利率由什么决定？",
            "现金流是否支持利润质量？",
            "真正的竞争优势是什么，是否可持续？",
            "如果只追踪3到5个指标，追踪哪些？",
        ),
        self_checks=(
            "解释事实之间的因果，而不只罗列",
            "至少一段说明关键指标为什么重要",
            "区分利润、现金流和资产负债表",
            "至少2个仍需验证的问题",
            "使用护城河/龙头/高质量等词须说明依据",
        ),
        forbidden=("只写公司简介和新闻摘要", "把收入增长等同于经营质量提升", "无证据断言护城河稳固", "给出买卖建议"),
        required_terms=(("区分利润与现金流", ("现金流",)), ("列出仍需验证的问题", ("待验证", "仍需验证", "需继续验证", "有待验证"))),
        capability_gaps=("竞争对手财务对比需要同行公司的报告；当前可用 find_documents 查同行年报，但公开行业数据/市场份额暂无工具。",),
    ),
    "ancient": OmenSpec(
        id="ancient",
        name="远古预兆",
        goal="把当前截面放回历史：时间线、关键转折、相似周期与案例，同时写清这一次的不同点。",
        methods=(PREFIX + "sector-overview/SKILL.md",),
        data_preferences=("公司多年年报（可超出默认两年）", "历史关键公告", "较长区间的股价日线（只作背景）"),
        tool_hints=(
            "find_documents 可查更早年度的年报，用于建立关键转折时间线（新选定资料仍须 full 通读）",
            "get_market_data 单次最多约3年（1100天）；需要更长背景时分段取（如两次各约2.5年），只作周期背景，不能单独作为结论依据",
            "用 search 回查 历史沿革/发展历程/重大资产重组 等原文",
        ),
        required_sections=("历史时间线", "过去相似案例", "相同点与不同点", "历史教训", "当前可能处在周期中的位置", "历史验证指标"),
        key_questions=(
            "公司/行业过去经历过哪些关键转折？",
            "当前情况和历史上哪几次最像？",
            "这次和历史相比哪些条件不同？",
            "历史上最大的误判来自哪里？",
            "当前更像周期早期、中期、后期还是全新阶段？",
            "哪些数据能证明历史类比成立或失效？",
        ),
        self_checks=("同时写相似点和不同点", "不只用一个历史故事下结论", "标出历史类比的局限", "给出可继续验证的指标"),
        forbidden=("写“历史总会重演”", "把过去股价走势当未来预测", "只选支持观点的案例", "把历史类比写成确定结论"),
        required_terms=(("写出相似点", ("相似", "相同")), ("写出不同点", ("不同", "差异"))),
        capability_gaps=(
            "行业历史周期数据、其他公司/地区的历史案例与历史研报需要公开信息搜索（M2-7），本次只能依据公司自身多年披露与行情。",
        ),
    ),
    "opportunity": OmenSpec(
        id="opportunity",
        name="机遇预兆",
        goal="关注未来6到24个月的变化与拐点，但区分事实、信号和假设，给出情景与验证指标。",
        methods=(PREFIX + "catalyst-calendar/SKILL.md", PREFIX + "earnings-preview/SKILL.md"),
        data_preferences=("截止年度最新定期报告", "管理层展望、经营计划、产能/订单/新产品", "上下游与价格相关披露"),
        tool_hints=(
            "优先通读当年最新半年报/季报",
            "用 search 回查 经营计划/展望/产能/订单/新产品/募投 等原文",
            "用定性图 cards 呈现情景（保守/中性/乐观）及各自前提",
        ),
        required_sections=(
            "潜在变化地图",
            "催化因素",
            "已发生事实/正在变化的信号/尚未验证的假设",
            "三种情景推演",
            "机会验证指标",
            "后续跟踪清单",
        ),
        key_questions=(
            "未来变化来自需求、供给、政策、技术、成本还是竞争？",
            "哪些已经发生，哪些只是预期？",
            "机会成立需要哪些关键条件？",
            "哪些指标最早能验证机会是否兑现？",
            "这是短期催化、中期拐点还是长期趋势？",
            "乐观情景不成立最可能卡在哪里？",
        ),
        self_checks=("明确区分事实、信号和假设", "至少3个后续可追踪指标", "写出机会成立的前提", "包含保守情景"),
        forbidden=("空泛写“空间广阔”“有望受益”", "只讲故事不给验证指标", "用单条信息推导长期机会", "把预测当事实", "给出买卖建议"),
        required_terms=(
            ("包含保守/中性/乐观情景", ("保守",)),
            ("区分事实与假设", ("假设",)),
            ("给出跟踪指标", ("跟踪", "验证指标", "观察指标")),
        ),
        capability_gaps=("新闻、政策文件、行业价格/招投标数据和卖方一致预期需要公开信息搜索（M2-7），本次只能依据公司披露与行情。",),
    ),
    "abyssal_echoes": OmenSpec(
        id="abyssal_echoes",
        name="深渊回响预兆",
        goal="主动向下看：先写清乐观叙事，再拆关键假设、找反证、查财务与治理风险，推演最坏情景并给出监控指标。",
        methods=(PREFIX + "initiating-coverage/references/valuation-methodologies.md",),
        data_preferences=(
            "年报风险提示与附注",
            "应收账款、存货、商誉、债务与资本开支",
            "审计意见、关联交易、担保/质押/诉讼",
            "利润与经营现金流的背离",
        ),
        tool_hints=(
            "用 search 回查 风险/应收账款/存货跌价/商誉/诉讼/关联交易/担保/质押 等原文",
            "用 extract_report_data 补齐货币资金、应收、存货、负债等资产质量数据",
            "估值陷阱只能依据已有行情做定性说明；无估值数据不做DCF或目标价",
        ),
        required_sections=("主流乐观叙事", "关键假设拆解", "反方论点与证据", "财务和治理风险检查", "最坏情景推演", "风险监控清单"),
        key_questions=(
            "当前市场最相信的故事是什么？",
            "这个故事依赖哪些关键假设？",
            "哪些事实会推翻这些假设？",
            "利润和现金流是否背离？",
            "有没有高库存、高应收、高商誉、高负债或资本开支压力？",
            "最坏情景下先在哪个指标上出问题？",
        ),
        self_checks=(
            "先写乐观叙事再写反方",
            "至少拆解3个关键假设",
            "重大风险尽量对应证据或待验证数据",
            "包含财务层面检查",
            "给出风险监控指标",
        ),
        forbidden=("模板化罗列风险", "无证据暗示造假或违规", "把负面信息直接当确定事实", "只写宏观风险", "把风险分析写成投资建议"),
        required_terms=(("拆解关键假设", ("假设",)), ("推演最坏情景", ("最坏",)), ("给出监控指标", ("监控", "跟踪", "预警"))),
        capability_gaps=("做空报告、负面新闻、监管处罚与诉讼的外部记录需要公开信息搜索（M2-7）；本次只依据公司披露的风险提示与财务数据。",),
    ),
}


def selected_omens(request):
    return [OMENS[getattr(o, "value", o)] for o in request.omens]


def select_methods(request):
    """返回 [(参考路径, 选择原因)]，按固定顺序排列。基础方法总是包含；问题意图与预兆各自追加。"""
    reasons = {}

    def add(path, reason):
        reasons.setdefault(path, []).append(reason)

    add(CANONICAL_METHODS[0], "基础研究框架")
    if request.include_financials:
        add(CANONICAL_METHODS[1], "基础：财务图表选择")
    add(CANONICAL_METHODS[2], "基础：质量检查清单")
    add(CANONICAL_METHODS[3], "基础：关键假设与论点跟踪")
    text = request.question + " " + request.user_style
    for words, paths, label in INTENT_METHODS:
        if any(word in text for word in words):
            for path in paths:
                add(path, "问题：" + label)
    for omen in selected_omens(request):
        for path in omen.methods:
            add(path, "预兆：" + omen.name)
    return [(path, reasons[path]) for path in CANONICAL_METHODS if path in reasons]
