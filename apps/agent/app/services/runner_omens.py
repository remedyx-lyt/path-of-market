"""预兆策略的执行与自检（AgentRunner 的一部分，M1-4）。

预兆按 docs/report-omens.md 的五个阶段生效：
1. 规划：方法计划里有该预兆的专属检查与 Skill（runner_methods）。
2. 资料：主循环上下文带资料偏好与工具提示（omen_context_message）。
3. 分析/生成：写作要求列出专属章节与关键问题，章节用 omens 字段标记（omen_writing_instruction）。
4. 自检：程序核对每个所选预兆至少有一个有来源的标记章节（validate_omens），并检查关键要素（omen_coverage）。
5. 输出：omenCoverage 合并模型自评、程序核查与能力缺口；covered 只代表“现有工具范围内”的覆盖。
"""

from app.core.omens import selected_omens


class OmenMixin:
    def omen_brief(self, omen):
        brief = omen.brief()
        if self.mcp_enabled:
            brief["toolHints"] = list(brief["toolHints"]) + ["需要外部资料时用search_public_information发现，再read_web_document全文读网页；PDF走官方披露工具。"]
            brief["capabilityGaps"] = ["已接公开网页搜索/正文工具，但付费数据库、完整卖方一致预期、全市场结构化行业数据和受限内容未接；未实际找到并读完的外部证据仍须写缺口。"]
        return brief

    def omens(self):
        return selected_omens(self.job.request)

    def omen_context_message(self):
        omens = self.omens()
        if not omens:
            return None
        return {
            "type": "omen_research_specs",
            "omens": [self.omen_brief(o) for o in omens],
            "instruction": (
                "所选预兆改变研究视角与资料选择：按 dataPreferences/toolHints 决定补查哪些资料，回答 keyQuestions；"
                "多个预兆并列呈现，冲突时不强行调和；capabilityGaps 是当前工具拿不到的资料，必须写成缺口而不是猜测。"
            ),
        }

    def omen_writing_instruction(self):
        omens = self.omens()
        if not omens:
            return "本次未选择预兆：sections 的 omens 留空数组，omenCoverage 输出 []。"
        lines = ["本次启用预兆。预兆只决定研究视角，不是报告内容：title、summary、heading、content 都不写预兆名称（崇高/远古/机遇预兆、深渊回响等），用“历史对照”“风险与反方”等普通说法；预兆只体现在章节 omens 标记与 omenCoverage。"]
        for omen in omens:
            lines.append(
                f'- {omen.id}（{omen.name}）：至少一个章节在 omens 中标记 "{omen.id}"；应覆盖章节 {list(omen.required_sections)}，'
                f"回答关键问题 {list(omen.key_questions)}；自检 {list(omen.self_checks)}；禁止 {list(omen.forbidden)}。"
            )
        lines.append(
            'omenCoverage=[{"omen":"预兆ID","addressed":["已回答的关键问题或检查"],"missingItems":["未覆盖项与原因（含工具拿不到的资料）"]}]，'
            "每个所选预兆一项。预兆专属章节可以和基础主题章节合并（同时标 topics 与 omens），但不能只用一句话概括。"
            "全部章节（含预兆章节）合计不超过 12 节；上面列出的应覆盖章节是内容要求，不是各占一节，章节多时优先合并。"
        )
        return "\n".join(lines)

    def omen_review_payload(self):
        return [
            {
                "id": o.id,
                "name": o.name,
                "requiredSections": list(o.required_sections),
                "selfChecks": list(o.self_checks),
                "forbidden": list(o.forbidden),
            }
            for o in self.omens()
        ]

    def validate_omens(self, content):
        for omen in self.omens():
            tagged = [s for s in content.sections if omen.id in s.omens]
            if not tagged:
                raise ValueError(f"所选{omen.name}没有对应章节：请至少一个章节在 omens 中标记 {omen.id}，并覆盖其关键问题。")
            if not any(s.citations or s.visual for s in tagged):
                raise ValueError(f"{omen.name}的章节需要引用实际来源。")

    def omen_coverage(self, content):
        """content 为最终报告字典；研究未完成时为 None。"""
        coverage = []
        plan_checks = ((self.method_usage or {}).get("plan") or {}).get("checks", [])
        read = {r["reference"] for r in (self.method_usage or {}).get("references", [])}
        read |= set((self.method_usage or {}).get("onDemandReads", []))
        for omen in self.omens():
            entry = {
                "omen": omen.id,
                "name": omen.name,
                "skillsRead": [m for m in omen.methods if m in read],
                "planChecks": sum(c.get("omen") == omen.id for c in plan_checks),
                "capabilityGaps": self.omen_brief(omen)["capabilityGaps"],
                "coverageScope": "现有工具与已读资料范围内",
                "verification": "程序核对章节标记、来源与关键要素；内容是否充分由模型自评并经复核，不等于独立审计。",
            }
            if content is None:
                coverage.append(
                    {**entry, "covered": False, "sections": [], "addressed": [], "missingItems": ["研究未完成，预兆要求未全部执行。"]}
                )
                continue
            sections = [s for s in content["sections"] if omen.id in s.get("omens", [])]
            text = "".join(s["heading"] + s["content"] for s in sections)
            program_missing = [label for label, words in omen.required_terms if not any(w in text for w in words)]
            report = next((r for r in content.get("omenCoverage", []) if r["omen"] == omen.id), None)
            missing = (report or {}).get("missingItems", []) + [f"程序自检未发现：{m}" for m in program_missing]
            if report is None:
                missing.append("模型未提交该预兆的覆盖自评。")
            coverage.append(
                {
                    **entry,
                    "covered": bool(sections) and not program_missing,
                    "sections": [s["heading"] for s in sections],
                    "addressed": (report or {}).get("addressed", []),
                    "missingItems": missing,
                }
            )
        return coverage
