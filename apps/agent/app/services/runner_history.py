"""年报范围由程序落实，同行公司不被自动扩成主公司的历史任务。"""
from app.core.research_history import history_scope
from app.tools.contracts import ToolError
from app.tools.contracts import FindArguments
from app.services.reading_coverage import reading_complete
import json


class HistoryMixin:
    def reconcile_saved_history(self):
        if not self.history_checked or not self.required_annual:
            return
        codes = {d.get('companyCode') for d in self.required_annual.values()} - {None}
        known = [d for d in self.discovered.values() if d.get('companyCode') in codes]
        args = FindArguments(company=self.job.request.target, years=history_scope(self.job.request)['years'],
                             asOfDate=self.job.request.as_of_date.isoformat())
        self.register_history(args, {'documents': known, 'company': {}})

    async def history_documents(self, args):
        if "annual" not in args.report_types or self.history_checked:
            return args
        # 原始输入可为股票代码；先交给官方目录消歧，不靠模型猜公司身份。
        company = await self.raw_tool("resolve_company", {"company": args.company})
        if self.job.request.target not in {args.company, company.get("name"), company.get("code")}:
            return args
        scope = history_scope(self.job.request)
        if scope["count"] <= 2:
            return args  # 明确短专题沿用按需选年度，保留原两年流程；五/十年才扩为历史取证任务。
        self.job.emit("annual_history_lookup", f"查询主公司{scope['count']}年完整年报：{scope['years'][0]}–{scope['years'][-1]}会计年度")
        return args.model_copy(update={"years": scope["years"]})

    def register_history(self, args, result):
        scope = history_scope(self.job.request)
        company = result.get("company", {})
        if self.job.request.target not in {args.company, company.get("name"), company.get("code")}:
            return
        if "annual" not in args.report_types or not self.history_checked and args.years != scope["years"]:
            return
        self.history_checked = True
        documents = [d for d in result["documents"] if d.get("preferred") and d.get("reportType", "annual") == "annual"]
        # 后续针对某一缺失年度的成功补查，也应填补旧缺口；同年只保留最新优选版本为必读项。
        by_year = {d['fiscalYear']: d for d in self.required_annual.values()}
        for document in documents:
            year = document['fiscalYear']
            if year in scope['years'] and (year not in by_year or (document['publishedAt'], document['documentId']) >= (by_year[year]['publishedAt'], by_year[year]['documentId'])):
                by_year[year] = document
        self.required_annual = {d['documentId']: d for d in by_year.values()}
        available = set(by_year)
        missing = [y for y in scope["years"] if y not in available]
        self.history_gap = "当前来源与截止日下未找到这些会计年度的完整年报：" + "、".join(map(str, missing)) if missing else None
        result["annualHistory"] = {**scope, "requiredDocuments": list(self.required_annual), "missingYears": missing}
        self.job.emit("annual_history_found", f"{scope['count']}年范围找到{len(available)}个年度的完整年报；选定原文须通读", requiredDocuments=list(self.required_annual), missingYears=missing)

    def annual_context(self):
        return {**history_scope(self.job.request), "checked": self.history_checked,
                "requiredDocuments": [{"documentId": sid, "title": d["title"], "readingComplete": reading_complete(self.coverage.get(sid))}
                                      for sid, d in self.required_annual.items()], "gap": self.history_gap}

    async def refresh_missing_history(self):
        """接续时复查先前缺失的年度，保留原覆盖；来源恢复/适配修复后不永久沿用旧缺口。"""
        if not self.history_gap or not self.history_checked or self.report_candidate or self.writing_state:
            return
        self.history_checked = False
        try:
            result = await self.find_documents({"company": self.job.request.target, "years": history_scope(self.job.request)["years"],
                                                "asOfDate": self.job.request.as_of_date.isoformat(), "reportTypes": ["annual"]})
        except ToolError as error:
            self.history_checked = True
            self.job.emit("annual_history_recheck_failed", "接续时年度复查暂未成功，保留原资料与已知缺口", errorCode=error.code)
            return
        self.messages.append({"role": "user", "content": json.dumps({"type": "annual_history_rechecked", "data": result,
                              "instruction": "接续时程序复查先前缺失年度的实际结果。已有阅读覆盖保留，仅补新增或未读原文。"}, ensure_ascii=False)})
        self.checkpoint()
