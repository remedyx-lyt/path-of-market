"""模型选工具的循环 + 文档完整分批阅读流程；参考 Pi 和 DeepSeek 工具协议。"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from hashlib import sha256
import time
from uuid import uuid4

from app.core.agent_prompts import READ_SYSTEM, REVIEW_SYSTEM, VISION_SYSTEM, EXTRACT_SYSTEM, METHOD_SYSTEM, REPORT_SYSTEM, initial_messages
from app.core.research_skills import SkillArguments, load_research_skill, load_method_bundle, read_reference
from app.core.config import ModelServiceError
from app.schemas.agent import AgentContent, AgentReadArguments, ReadingNote
from app.schemas.financial import InspectArguments, VisualResult, ExtractArguments, ExtractResult, parse_extraction
from app.services.financial_data import locate_summary_pages, verified_points, build_financial_data
from app.services.report_figures import locate_detail_pages, verified_segments, build_business_data, plan_section_figures
from app.services.model_client import complete_turn
from app.tools.contracts import FindArguments, ToolError
from app.tools.market import MarketArguments
from app.tools.documents import write_json


@dataclass(frozen=True)
class RunLimits:
    max_steps: int = 18
    max_model_calls: int = 72
    max_tokens: int = 1_200_000
    max_seconds: float = 1200
    max_context_characters: int = 160000
    report_tokens: int = 14000
    read_characters: int = 26000
    max_visual_pages: int = 12


class BudgetStop(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def declarations():
    specs = [
        ("find_documents", "从公司/会计年度/截止日找官方完整报告，支持年报、半年报、一季报和三季报；不需要上传。", FindArguments),
        ("read_document", "完整读取选定 PDF（full 默认），内部下载、分批阅读并返回带页码要点和覆盖；page/search 仅复查。", AgentReadArguments),
        ("get_market_data", "获取股票区间日线，返回不复权实际价格和后复权计算的变化/回撤/波动/月度表现。", MarketArguments),
        ("inspect_document_pages", "实际查看已发现PDF的1至3个物理页图片，理解图表/表格/扫描页并保留页码；不代替全本文字阅读。", InspectArguments),
        ("read_research_skill", "读取项目保留的Anthropic原版金融研究方法；catalog列目录，按需分页读取，不执行其脚本或专属工具。", SkillArguments),
        ("extract_report_data", "从已通读PDF的1至4个物理页提取有原文依据的业务分部收入、研发、成本及资产负债数据，程序计算占比与趋势。", ExtractArguments),
    ]
    return [{"type": "function", "function": {"name": name, "description": description,
            "parameters": schema.model_json_schema(by_alias=True)}} for name, description, schema in specs]


class AgentRunner:
    def __init__(self, job, tools, settings, *, limits=None, completion=None):
        self.job, self.tools, self.settings = job, tools, settings
        self.limits = limits or RunLimits()
        self.completion = completion or complete_turn
        self.began = time.monotonic()
        self.messages = initial_messages(job.request)
        self.notes = {}
        self.sources = {}
        self.coverage = {}
        self.market_data = None
        self.steps = 0
        self.action_counts = {}
        self.current_period_checked = False
        self.required_current = None
        self.current_period_gap = None
        self.discovered = {}
        self.skill = load_research_skill()
        self.visual_readings = []
        self.financial_points = []
        self.financial_gaps = []
        self.financial_checked = set()
        self.detail_checked = set()
        self.segment_points = []
        self.business_gaps = []
        self.extraction_readings = []
        self.method_usage = None

    def financial_data(self):
        return build_financial_data(self.financial_points,self.financial_gaps)

    def business_data(self):
        return build_business_data(self.segment_points,self.financial_data(),self.business_gaps)

    async def prepare_methods(self):
        if not self.job.request.include_financials:
            return
        references = load_method_bundle(self.job.request)
        self.job.emit('methods_started','阅读相关原版金融方法，形成适合本次研究的方法计划')
        messages = [{'role':'system','content':METHOD_SYSTEM},{'role':'user','content':json.dumps({
            'task':self.job.request.model_dump(mode='json',by_alias=True),
            'availableTools':[s['function']['name'] for s in declarations()],
            'references':references},ensure_ascii=False)}]
        for attempt in range(2):
            message = await self.model(messages)
            try:
                plan = json.loads(message['content'])
                paths = {r['reference'] for r in references}
                assert isinstance(plan.get('focus'),str) and isinstance(plan.get('unavailable'),list)
                assert 3 <= len(plan['checks']) <= 12
                assert all(isinstance(c,dict) and c.get('methodReference') in paths and all(isinstance(c.get(k),str) for k in ['topic','question','evidenceNeeded','figureIdea']) for c in plan['checks'])
                break
            except (ValueError,KeyError,TypeError,AssertionError):
                if attempt:
                    raise ToolError('METHOD_PLAN_INVALID','研究方法计划格式无效，尚未开始事实分析。') from None
                messages += [message,{'role':'user','content':'请修正为指定JSON结构，checks有3至12项，methodReference须是实际提供的文件路径。'}]
        self.method_usage = {'status':'planned','references':[{k:v for k,v in r.items() if k!='content'} for r in references],
                             'plan':plan,'reviewed':False}
        self.messages.append({'role':'user','content':json.dumps({'type':'research_method_plan',**self.method_usage,
            'instruction':'围绕计划主动取证、分析和选图，可依据新证据调整；缺数据明确说明，不机械执行固定配额。'},ensure_ascii=False)})
        self.job.emit('methods_planned',f'已完整读取{len(references)}份相关原版方法并形成研究计划',references=[r['reference'] for r in references])

    async def extract(self, arguments, *, origin='model_tool'):
        args = ExtractArguments.model_validate(arguments)
        if not self.coverage.get(args.document_id,{}).get('textComplete'):
            raise ToolError('FULL_READING_REQUIRED','先完整阅读资料，再回查取数；指定页提取不能代替全文阅读。')
        metadata,pages = await asyncio.to_thread(self.tools.store.loaded,args.document_id)
        if metadata['publishedAt'] > self.job.request.as_of_date.isoformat():
            raise ToolError('AFTER_RESEARCH_CUTOFF','资料晚于研究截止日。')
        if len(set(args.pages)) != len(args.pages) or any(p > len(pages) for p in args.pages):
            raise ToolError('PAGE_OUT_OF_RANGE','取数页码重复或超出资料范围。')
        payload, texts, units = [],{},{}
        for number in args.pages:
            text = pages[number-1]['text']
            # 同一页可能开始母公司报表，模型不可把它与此前合并口径混用。
            text = re.split(r'2[、．.]\s*母公司资产负债表|4[、．.]\s*母公司利润表',text)[0]
            texts[number] = text
            for prior in reversed(pages[max(0,number-4):number]):
                candidate = text if prior['page']==number else prior['text']
                hit = re.search(r'单位\s*[:：]\s*(?:人民币)?(亿元|万元|元)',candidate)
                if hit:
                    units[number] = {'unit':hit[1],'page':prior['page'],'quote':hit[0]}
                    break
            payload.append({'page':number,'text':text,'unitContext':units.get(number)})
        task = {'document':{k:metadata[k] for k in ['documentId','fiscalYear','reportType']},'focus':args.focus,'pages':payload}
        key = sha256(json.dumps({'task':task,'system':EXTRACT_SYSTEM,'model':self.settings.model,'baseUrl':self.settings.base_url},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        cache = self.tools.store.root/'data-notes'/(key+'.json')
        parsed,origin_run = None,None
        if cache.exists():
            try:
                saved = json.loads(cache.read_text(encoding='utf-8'))
                parsed = ExtractResult.model_validate(saved['result']); origin_run = saved['runId']
            except (ValueError,KeyError,OSError): pass
        if parsed is None:
            messages = [{'role':'system','content':EXTRACT_SYSTEM},{'role':'user','content':json.dumps(task,ensure_ascii=False)}]
            for attempt in range(2):
                message = await self.model(messages)
                try:
                    parsed = parse_extraction(message['content'])
                    break
                except ValueError as error:
                    write_json(self.tools.store.root/'data-errors'/(key+f'-{attempt}.json'),
                               {'response':message['content'],'error':str(error)[:1200],'runId':self.job.task_id})
                    if attempt: raise ToolError('DATA_EXTRACTION_INVALID','正文取数未通过格式校验，未计入底稿。') from None
                    messages += [message,{'role':'user','content':'按financialPoints、segmentPoints、gaps结构修正，不推算，quote只保留含指标行与数值的短连续原文。格式问题：'+str(error)[:700]}]
            write_json(cache,{'result':parsed.model_dump(by_alias=True),'runId':self.job.task_id})
        # 文本路径必须提供逐字引文；旧视觉路径不受此约束。
        missing = [p for p in parsed.financial_points if not p.quote]
        parsed.financial_points = [p for p in parsed.financial_points if p.quote]
        points,gaps = verified_points(parsed,metadata,texts,units)
        segments,segment_gaps = verified_segments(parsed,metadata,texts)
        self.financial_points += points; self.financial_gaps += gaps
        self.segment_points += segments; self.business_gaps += segment_gaps+parsed.gaps
        if missing: self.financial_gaps.append('正文取数缺少连续原文引文的数值已排除。')
        record = {'sourceId':args.document_id,'pages':sorted(args.pages),'origin':origin,'cacheReused':origin_run is not None,
                  'originRunId':origin_run or self.job.task_id,'verifiedPointCount':len(points),'segmentPointCount':len(segments)}
        self.extraction_readings.append(record)
        self.job.emit('data_extracted',f'正文取数完成：{len(points)}个财务值、{len(segments)}个业务收入值',**record)
        return {**record,'financialData':self.financial_data(),'businessData':self.business_data()}

    async def detail_data(self, identifier):
        if not self.job.request.include_financials or identifier in self.detail_checked:
            return
        self.detail_checked.add(identifier)
        metadata,pages = await asyncio.to_thread(self.tools.store.loaded,identifier)
        selected = locate_detail_pages(pages)
        for start in range(0,len(selected),2):
            try:
                await self.extract({'documentId':identifier,'pages':selected[start:start+2]},origin='automatic_detail_extraction')
            except ToolError as error:
                self.business_gaps.append(metadata['title']+'：'+error.message)
                self.job.emit('data_gap',error.message,sourceId=identifier)

    def check_budget(self):
        if self.job.cancel_requested:
            raise asyncio.CancelledError
        if time.monotonic() - self.began >= self.limits.max_seconds:
            raise BudgetStop("time_budget")
        if self.job.model_calls >= self.limits.max_model_calls:
            raise BudgetStop("model_call_budget")
        if self.job.usage.get("total_tokens", 0) >= self.limits.max_tokens:
            raise BudgetStop("token_budget")

    async def model(self, messages, *, tool_specs=None, reading=False, visual=False, report=False):
        self.check_budget()
        # 图片字节单独由渲染器限制，不能把base64当文字上下文；图片仍计入供应商实际用量。
        projected = [{**m, 'content': [{'type':'image_url'} if p.get('type')=='image_url' else p for p in m['content']]
                      if isinstance(m.get('content'), list) else m.get('content')} for m in messages]
        if len(json.dumps(projected, ensure_ascii=False)) > self.limits.max_context_characters:
            raise BudgetStop("context_budget")
        self.job.model_calls += 1
        self.job.emit("model_started", "查看PDF原页图像" if visual else "阅读原文" if reading else "判断下一步研究动作", modelCall=self.job.model_calls)
        output_tokens = min(1800, self.settings.max_tokens) if reading else self.limits.report_tokens if report else 6500
        # 累计预算以供应商实际用量记账，下一调用前检查；单次也有明确输出/时间上限。
        try:
            message, usage = await self.completion(self.settings, messages, tools=tool_specs,
                                                   max_tokens=output_tokens, json_mode=not bool(tool_specs))
        except ModelServiceError as error:
            for key,value in getattr(error,'usage',{}).items():
                self.job.usage[key]=self.job.usage.get(key,0)+value
            raise
        for key, value in usage.items():
            self.job.usage[key] = self.job.usage.get(key, 0) + value
        if "total_tokens" not in usage and "prompt_tokens" in usage and "completion_tokens" in usage:
            self.job.usage["total_tokens"] = self.job.usage.get("total_tokens", 0) + usage["prompt_tokens"] + usage["completion_tokens"]
        self.job.emit("model_finished", "模型调用完成", modelCall=self.job.model_calls)
        return message

    async def inspect(self, arguments, *, origin='model_tool'):
        args = InspectArguments.model_validate(arguments)
        metadata = await asyncio.to_thread(self.tools.store.metadata, args.document_id)
        if metadata['publishedAt'] > self.job.request.as_of_date.isoformat():
            raise ToolError('AFTER_RESEARCH_CUTOFF', '资料晚于研究截止日。')
        if self.completion is complete_turn and self.settings.model not in {'deepseek-flash','deepseek-v4-flash-vision-exp'}:
            raise ToolError('VISION_MODEL_UNSUPPORTED', '当前配置模型未声明图片能力，请使用支持视觉输入的模型。')
        existing = {(r['sourceId'],p) for r in self.visual_readings for p in r['pages']}
        if len(existing | {(args.document_id,p) for p in args.pages}) > self.limits.max_visual_pages:
            raise ToolError('VISUAL_PAGE_BUDGET', '本轮视觉页面预算已达上限，保留已检查范围。')
        downloaded = await self.raw_tool('fetch_document', {'documentId':args.document_id})
        identifier = self.source(downloaded['document'])
        rendered = await self.raw_tool('render_document_pages', args.model_dump(by_alias=True))
        task = {'document':rendered['document'], 'focus':args.focus,
                'pages':[{k:v for k,v in p.items() if k not in {'imageDataUrl','text'}} for p in rendered['pages']]}
        key = sha256(json.dumps({'task':task,'system':VISION_SYSTEM,'model':self.settings.model,
            'baseUrl':self.settings.base_url},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        cache = self.tools.store.root / 'visual-notes' / (key+'.json')
        parsed, origin_run = None, None
        if cache.exists():
            try:
                saved = json.loads(cache.read_text(encoding='utf-8'))
                parsed = VisualResult.model_validate(saved['result']); origin_run = saved['runId']
            except (ValueError,KeyError,OSError):
                pass
        def validate_pages(candidate):
            if {o.page for o in candidate.observations} != set(args.pages) or any(p.page not in args.pages for p in candidate.financial_points):
                raise ValueError('视觉结果引用了未提供的页码或遗漏输入页')
        if parsed is not None:
            try: validate_pages(parsed)
            except ValueError: parsed, origin_run = None, None
        if parsed is None:
            parts = [{'type':'text','text':json.dumps(task,ensure_ascii=False)}]
            for page in rendered['pages']:
                parts.extend([{'type':'text','text':f'以下为PDF物理第{page["page"]}页'},
                    {'type':'image_url','image_url':{'url':page['imageDataUrl'],'detail':'high'}}])
            messages = [{'role':'system','content':VISION_SYSTEM},{'role':'user','content':parts}]
            for attempt in range(2):
                message = await self.model(messages, visual=True)
                try:
                    parsed = VisualResult.model_validate_json(message['content']); validate_pages(parsed)
                    break
                except ValueError:
                    if attempt:
                        raise ToolError('VISUAL_RESULT_INVALID','原页视觉结果未通过格式/页码校验，未计入已理解范围。') from None
                    messages += [message, {'role':'user','content':'请严格按JSON结构和输入物理页码修正；未看清数值可省略。'}]
            write_json(cache, {'result':parsed.model_dump(by_alias=True),'runId':self.job.task_id,'processedAt':now()})
        points, gaps = verified_points(parsed, rendered['document'], {p['page']:p['text'] for p in rendered['pages']})
        for point in points:
            point['verificationOrigin']=origin
        self.financial_points.extend(points); self.financial_gaps.extend(gaps)
        record = {'sourceId':identifier,'pages':sorted(args.pages),'origin':origin,'model':self.settings.model,
                  'processedAt':now(),'cacheReused':origin_run is not None,'originRunId':origin_run or self.job.task_id,
                  'observations':[o.model_dump() for o in parsed.observations], 'verifiedPointCount':len(points),
                  'imageHashes':[p['imageSha256'] for p in rendered['pages']]}
        self.visual_readings.append(record)
        self.job.emit('visual_processed', f'已查看 {metadata["title"]} 原页 {args.pages}，核对{len(points)}个财务数值',
                      sourceId=identifier, pages=args.pages, originRunId=record['originRunId'])
        return {**record, 'financialData':build_financial_data(self.financial_points,self.financial_gaps),
                'limitations':['只检查所列图片页；数值匹配不证明所有列序与会计口径都无误，保留来源供核查。']}

    async def financial_summary(self, identifier):
        if not self.job.request.include_financials or identifier in self.financial_checked:
            return
        self.financial_checked.add(identifier)
        metadata,pages = await asyncio.to_thread(self.tools.store.loaded, identifier)
        selected = locate_summary_pages(pages)
        if not selected:
            self.financial_gaps.append(metadata['title']+'：未定位主要会计数据页，尚无自动结构化财务取数。')
            return
        try:
            await self.inspect({'documentId':identifier,'pages':selected,'focus':'检查主要会计数据表，提取当前及比较年度的实际值，核对表头年份/单位。'}, origin='automatic_financial_summary')
        except ToolError as error:
            self.financial_gaps.append(metadata['title']+'：'+error.message)
            self.job.emit('visual_gap',error.message,sourceId=identifier)

    async def raw_tool(self, name, arguments):
        self.check_budget()
        result = await asyncio.to_thread(self.tools.execute, name, arguments)
        if result["status"] != "completed":
            error = result["error"]
            raise ToolError(error["code"], error["message"], error.get("details"))
        return result["data"]

    def source(self, metadata):
        identifier = metadata["documentId"]
        if identifier not in self.sources:
            self.sources[identifier] = {"sourceId": identifier, "kind": "document", "title": metadata["title"],
                "url": metadata["sourceUrl"], "publishedAt": metadata["publishedAt"], "pageCount": metadata["pageCount"],
                "fiscalYear": metadata["fiscalYear"], "reportType": metadata.get("reportType", "annual")}
            self.coverage[identifier] = {"sourceId": identifier, "pageCount": metadata["pageCount"],
                "returnedCharacters": 0, "processedCharacters": 0, "processedPages": [], "emptyTextPages": [],
                "textComplete": False, "batches": 0}
        self.job.sources = list(self.sources.values())
        self.job.coverage = list(self.coverage.values())
        return identifier

    async def read(self, arguments):
        args = AgentReadArguments.model_validate(arguments)
        metadata = await asyncio.to_thread(self.tools.store.metadata, args.document_id)
        if metadata["publishedAt"] > self.job.request.as_of_date.isoformat():
            raise ToolError("AFTER_RESEARCH_CUTOFF", "资料披露时间晚于研究截止日。")
        downloaded = await self.raw_tool("fetch_document", {"documentId": args.document_id})
        identifier = self.source(downloaded["document"])
        if args.mode != "full":
            if not self.coverage[identifier]["textComplete"]:
                raise ToolError("FULL_READ_REQUIRED", "此资料尚未完成通读。请使用 mode=full，程序会从上次成功处理的位置接续；单页或关键词不能替代。")
            if args.mode == "page":
                return await self.raw_tool("read_document", {"documentId": identifier, "page": args.page})
            if not args.query.strip():
                raise ToolError("INVALID_TOOL_ARGUMENTS", "关键词回查需要 query。")
            return await self.raw_tool("search_document", {"documentId": identifier, "query": args.query})
        if self.coverage[identifier]["textComplete"]:
            await self.financial_summary(identifier)
            await self.detail_data(identifier)
            return {"sourceId": identifier, "notes": self.notes[identifier], "coverage": self.coverage[identifier], "cacheHit": True,
                    'financialData':self.financial_data(),'businessData':self.business_data()}
        # 失败后的补读从已处理游标接续；不把先前只返回但模型失败的批次算成已读。
        cursor = self.coverage[identifier].get("nextCursor", {"startPage": 1, "offset": 0})
        self.notes.setdefault(identifier, [])
        while cursor is not None:
            self.check_budget()
            batch = await self.raw_tool("read_document_batch", {"documentId": identifier, **cursor,
                "maxPages": 20, "maxCharacters": self.limits.read_characters})
            progress = self.coverage[identifier]
            progress["returnedCharacters"] += sum(len(p["text"]) for p in batch["pages"])
            self.job.emit("reading_batch", f"{metadata['title']}：阅读第 {batch['pages'][0]['page']}–{batch['pages'][-1]['page']} 页",
                          sourceId=identifier, firstPage=batch["pages"][0]["page"], lastPage=batch["pages"][-1]["page"])
            reading_task = {"question": self.job.request.question, "sourceId": identifier,
                            "title": metadata["title"], "pages": batch["pages"]}
            reading_messages = [{"role": "system", "content": READ_SYSTEM},
                {"role": "user", "content": json.dumps(reading_task, ensure_ascii=False)}]
            # 这是派生阅读缓存，不是会话持久化。必须命中原文件/原文/问题/模型/提示版本。
            cache_key = sha256(json.dumps({"messages": reading_messages, "model": self.settings.model,
                "sha256": downloaded["document"]["sha256"]}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            cache_path = self.tools.store.root / "reading-notes" / (cache_key + ".json")
            note, origin = None, None
            allowed = {p["page"] for p in batch["pages"]}
            if cache_path.exists():
                try:
                    cached = json.loads(cache_path.read_text(encoding="utf-8"))
                    candidate = ReadingNote.model_validate(cached["note"])
                    if all(set(f.pages) <= allowed for f in candidate.facts):
                        note, origin = candidate, cached.get("runId")
                except (ValueError, KeyError, TypeError, OSError):
                    pass
            for attempt in range(2 if note is None else 0):
                message = await self.model(reading_messages, reading=True)
                try:
                    candidate = ReadingNote.model_validate_json(message["content"])
                    if any(not set(fact.pages) <= allowed for fact in candidate.facts):
                        raise ValueError("引用了当前批次之外的物理页码")
                    note = candidate
                    write_json(cache_path, {"note": note.model_dump(), "runId": self.job.task_id, "processedAt": now(),
                                           "sourceId": identifier, "model": self.settings.model})
                    break
                except ValueError as error:
                    if attempt == 1:
                        raise ToolError("READING_NOTE_INVALID", "本批阅读记录未通过校验；继续 full 可接续重试，本批尚未计入覆盖。",
                            {"allowedPages": sorted(allowed), "nextCursor": cursor}) from None
                    # 只修复一次，不能把结构失败当成全文已读；不把验证异常里的原文/堆栈塞入结果。
                    reading_messages.extend([message, {"role": "user", "content":
                        "上次记录未通过校验。请修正为 summary 字符串、最多8个 facts（每个 text 字符串和 pages 整数数组）、最多6个 gaps 字符串。"
                        + "只能引用这些物理页码：" + json.dumps(sorted(allowed)) + "。原文中其他引用页码不能当作本批来源。"}])
            if origin:
                self.job.emit("reading_cache_reused", "复用同一原文与问题的已验证阅读记录", sourceId=identifier, originRunId=origin)
            self.notes[identifier].append(note.model_dump())
            progress["processedCharacters"] += sum(len(p["text"]) for p in batch["pages"])
            progress["processedPages"] = sorted(set(progress["processedPages"]) | {p["page"] for p in batch["pages"] if p["pageComplete"]})
            progress["emptyTextPages"] = sorted(set(progress["emptyTextPages"]) | {p["page"] for p in batch["pages"] if p["textStatus"] != "extracted"})
            progress["batches"] += 1
            cursor = batch["nextCursor"]
            progress["nextCursor"] = cursor
            progress["textComplete"] = cursor is None and len(progress["processedPages"]) == progress["pageCount"] and not progress["emptyTextPages"]
            self.job.emit("reading_processed", f"{metadata['title']}：已处理 {len(progress['processedPages'])}/{progress['pageCount']} 页文本",
                          sourceId=identifier)
        await self.financial_summary(identifier)
        await self.detail_data(identifier)
        return {"sourceId": identifier, "notes": self.notes[identifier], "coverage": self.coverage[identifier],
                'financialData':build_financial_data(self.financial_points,self.financial_gaps),
                'businessData':self.business_data(),
                "limitations": ["文字与视觉覆盖分别记录；未列出的图片尚未理解。"]}

    async def dispatch(self, name, arguments):
        if name == 'extract_report_data':
            return await self.extract(arguments)
        if name == 'inspect_document_pages':
            return await self.inspect(arguments)
        if name == 'read_research_skill':
            return await asyncio.to_thread(read_reference, arguments)
        if name == "find_documents":
            args = FindArguments.model_validate(arguments)
            if args.as_of_date != self.job.request.as_of_date.isoformat():
                raise ToolError("CUTOFF_MISMATCH", "查询应使用任务的研究截止日期。")
            result = await self.raw_tool(name, args.model_dump(by_alias=True))
            if self.job.request.include_current_period and not self.current_period_checked:
                self.current_period_checked = True
                year = self.job.request.as_of_date.year
                supplement_args = {"company": args.company, "years": [year], "asOfDate": args.as_of_date,
                                   "reportTypes": ["q1", "interim", "q3"]}
                self.job.emit("current_period_lookup", f"核对 {year} 年已披露的最新定期报告")
                try:
                    supplement = await self.raw_tool(name, supplement_args)
                    latest = [d for d in supplement["documents"] if d["preferred"]]
                    if latest:
                        self.required_current = max(latest, key=lambda d: d["publishedAt"])
                    else:
                        self.current_period_gap = f"当前来源未找到截至 {args.as_of_date} 已披露的 {year} 年季报/半年报。"
                    merged = {d["documentId"]: d for d in result["documents"] + supplement["documents"]}
                    result["documents"] = list(merged.values())
                    result["currentPeriodQuery"] = {"arguments": supplement_args, "queryComplete": supplement["queryComplete"],
                                                     "requiredLatestDocument": self.required_current}
                except ToolError as error:
                    self.current_period_gap = "当年最新报告查询未完成：" + error.message
                if self.current_period_gap:
                    result["gaps"].append(self.current_period_gap)
            self.discovered.update({d["documentId"]: d for d in result["documents"]})
            return result
        if name == "read_document":
            return await self.read(arguments)
        if name == "get_market_data":
            args = MarketArguments.model_validate(arguments)
            if args.end_date > self.job.request.as_of_date.isoformat():
                raise ToolError("AFTER_RESEARCH_CUTOFF", "行情结束日期晚于研究截止日。")
            data = await self.raw_tool(name, args.model_dump(by_alias=True))
            self.market_data = data
            identifier = "market-" + data["company"]["code"]
            self.sources[identifier] = {"sourceId": identifier, "kind": "market", "title": data["company"]["name"] + "历史日线（" + data["provider"] + "）",
                "url": data["sourceUrls"][0], "publishedAt": data["actualEnd"], "retrievedAt": data["retrievedAt"]}
            self.job.sources = list(self.sources.values())
            return {k: v for k, v in data.items() if k != "series"} | {"sourceId": identifier}
        raise ToolError("UNKNOWN_TOOL", "此工具未向研究模型开放。")

    def context(self):
        # 完整批次笔记保留在运行状态/缓存；主循环使用有来源的有限投影，底稿只传当前一份。
        messages = [dict(m) for m in self.messages]
        for message in messages:
            if message.get('role') != 'tool':
                continue
            body = json.loads(message['content'])
            data = body.get('data')
            if not isinstance(data, dict):
                continue
            data.pop('financialData', None)
            data.pop('businessData', None)
            if data.get('notes'):
                data['notes'] = [{'summary':n['summary'][:240], 'facts':[{'text':f['text'][:320], 'pages':f['pages']} for f in n['facts'][:2]],
                                  'gaps':n['gaps']} for n in data['notes']]
                data['contextProjection'] = '主循环为有限要点投影；完整批次记录保留，其他细节可按页回查。'
            message['content'] = json.dumps(body, ensure_ascii=False)
        # 最近两次按页回查保留原文；更早结果保留来源和有限摘录，完整内容仍可回查。
        page_results=[m for m in messages if m.get('role')=='tool' and '"text"' in m.get('content','')]
        for message in page_results[:-2]:
            body=json.loads(message['content']);data=body.get('data',{})
            if isinstance(data.get('text'),str) and len(data['text'])>700:
                data['text']=data['text'][:700]
                data['contextProjection']='历史回查原文的有限摘录；完整页仍可通过read_document回查。'
                message['content']=json.dumps(body,ensure_ascii=False)
        if self.financial_points or self.financial_gaps or self.segment_points:
            data = build_financial_data(self.financial_points,self.financial_gaps)
            business=self.business_data()
            business['datasets']=[{**d,'rows':[{**r,'items':[{k:v for k,v in p.items() if k not in {'quote','publishedAt','verification'}} for p in r['items']]} for r in d['rows']]} for d in business['datasets']]
            state = {'type':'current_research_state', 'financialData':{k:data[k] for k in ['datasets','gaps','method']},
                     'availableCharts':data['charts'], 'businessData':business,
                     'visualCoverage':[{'sourceId':r['sourceId'],'pages':r['pages']} for r in self.visual_readings],
                     'note':'这是唯一当前底稿。主动选择能说明问题的图，章节chartIds/businessIds引用这里的ID；不按配额凑图。'}
            messages.append({'role':'user','content':json.dumps(state,ensure_ascii=False)})
        messages.append({'role':'user','content':json.dumps({'remainingDecisionSteps':max(0,self.limits.max_steps-self.steps),
            'instruction':'优先用已取得的证据形成报告；只有会改变结论的缺口再补查，不为方法菜单穷尽所有指标。剩余轮数不足时明确局限并提交已有证据支持的最终报告。'},ensure_ascii=False)})
        return messages

    def validate_content(self, message):
        content = AgentContent.model_validate_json(message["content"])
        if self.job.request.include_financials:
            missing = {'business','performance','profitability','cashflow','balance_sheet','research','risks'} - {t for s in content.sections for t in s.topics}
            if missing:
                raise ValueError('基本研究主题缺少：'+','.join(sorted(missing))+'；补充分析或明确资料缺口，并标记topics。')
        if not self.sources:
            raise ValueError("尚未取得证据")
        if not self.coverage or any(not c["textComplete"] for c in self.coverage.values()):
            raise ValueError("选定报告尚未完整处理可提取文字，请继续 full 阅读或明确停止缺口")
        if self.job.request.include_market and self.market_data is None:
            raise ValueError("本任务要求行情分析，尚未取得行情")
        if self.job.request.include_current_period and not self.current_period_checked:
            raise ValueError("尚未查找截止年度最新已披露的定期报告")
        if self.required_current and not self.coverage.get(self.required_current["documentId"], {}).get("textComplete"):
            raise ValueError("当年最新已披露报告尚未通读，请以 mode=full 阅读 " + self.required_current["documentId"] + "：" + self.required_current["title"])
        citations = [c for section in content.sections for c in section.citations]
        if not citations:
            raise ValueError("最终章节需要引用实际来源")
        for citation in citations:
            source = self.sources.get(citation.source_id)
            if source is None or source["kind"] == "document" and (citation.page is None or citation.page not in self.coverage[citation.source_id]["processedPages"]):
                raise ValueError("引用必须指向本次实际处理的来源和页码")
        chart_ids = {c['id'] for c in self.financial_data()['charts']}
        business_ids = {d['id'] for d in self.business_data()['datasets']}
        if self.job.request.include_financials:
            if chart_ids and not any(s.chart_ids for s in content.sections):
                raise ValueError('已取得财务绘图数据，请主动选择支持论点的chartIds，不能全部闲置。')
            if business_ids and not any(s.business_ids for s in content.sections):
                raise ValueError('已取得业务收入结构，请主动选择相关businessIds；不能仅展示财务总览。')
        used = set()
        for section in content.sections:
            if not set(section.chart_ids) <= chart_ids or not set(section.business_ids) <= business_ids:
                raise ValueError('所选图表ID必须来自实际底稿。')
            selected = set(section.chart_ids+section.business_ids)
            if used & selected:
                raise ValueError('同一图表放在最相关章节即可，不重复插入。')
            used |= selected
            if section.visual:
                for node in section.visual.nodes:
                    for citation in node.citations:
                        source = self.sources.get(citation.source_id)
                        if source is None or source['kind']=='document' and citation.page not in self.coverage[citation.source_id]['processedPages']:
                            raise ValueError('定性图节点也须引用实际已读来源和页码。')
        return content

    async def review(self, content):
        self.job.emit("report_review", "核对报告文字、资料范围与行情计算口径")
        payload = {"candidate": content.model_dump(by_alias=True), "asOfDate": self.job.request.as_of_date.isoformat(),
                   "discoveredDocuments": list(self.discovered.values()), "processedSources": list(self.sources.values()),
                   "coverage": list(self.coverage.values()),
                   'financialData':build_financial_data(self.financial_points,self.financial_gaps),'visualReadings':self.visual_readings,
                   'businessData':self.business_data(),'methodUsage':self.method_usage,
                   "market": {k: v for k, v in (self.market_data or {}).items() if k != "series"}}
        message = await self.model([{"role": "system", "content": REVIEW_SYSTEM},
                                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],report=True)
        revised = self.validate_content(message)
        if self.method_usage:
            self.method_usage.update(status='planned_and_reviewed',reviewed=True)
        return revised

    async def compose(self):
        self.job.emit('report_drafting','根据已有证据和所选方法撰写图文报告')
        messages=self.context()
        messages[0]={'role':'system','content':REPORT_SYSTEM+'\n\n'+self.skill['instructions']}
        messages.append({'role':'user','content':'取证阶段已结束。现在按完整报告JSON格式写作，自主选择有用的实际图表ID与有来源的定性图；不要返回ready。'})
        return await self.model(messages,report=True)

    def report(self, content=None, reason="research_completed"):
        partial = reason != "research_completed"
        if content is None:
            sections = [{"heading": "本次完成的工作", "content": f"执行 {self.steps} 轮研究动作，模型调用 {self.job.model_calls} 次。请结合来源与阅读覆盖查看已完成范围。", "citations": []},
                        {"heading": "未完成与停止原因", "content": f"停止原因：{reason}。保留已获取的来源、行情和阅读覆盖；未完成完整报告，不应视作最终研究结论。", "citations": []}]
            for identifier, notes in self.notes.items():
                if notes:
                    sections.append({"heading": self.sources[identifier]["title"] + "：已读部分记录",
                                     "content": "\n".join(n["summary"] for n in notes), "citations": []})
            content = {"title": self.job.request.target + "研究（未完成）", "summary": "研究已停止，以下仅保留实际完成范围与资料。", "sections": sections}
        else:
            content = content.model_dump(by_alias=True)
        limitations = ["PDF全文文字与局部原页视觉检查分别记录；未列出的图片/扫描页未进行视觉理解，取数校验不等于独立审计。",
                       "会话和任务目前保存在运行进程内，重启后不能恢复；持久化按 M2 实施。"]
        if self.market_data:
            limitations += self.market_data["limitations"]
        if self.current_period_gap:
            limitations.append(self.current_period_gap)
        if partial:
            limitations.insert(0, "本次研究未完成：" + reason)
        financial_data,business_data = self.financial_data(),self.business_data()
        return {**self.job.request.model_dump(mode="json", by_alias=True), **content,
                "mode": "agent", "isMock": False, "evidenceStatus": "partial" if partial else "retrieved",
                "sources": list(self.sources.values()), "toolCalls": self.job.tool_calls,
                "coverage": list(self.coverage.values()), "marketData": self.market_data,
                'financialData':build_financial_data(self.financial_points,self.financial_gaps) if self.job.request.include_financials or self.financial_points else None,
                'visualReadings':self.visual_readings, 'researchSkill':{k:self.skill[k] for k in ['name','version','upstream']},
                'businessData':business_data,'extractionReadings':self.extraction_readings,'methodUsage':self.method_usage,
                'figurePlan':plan_section_figures(content['sections'],financial_data,business_data),
                "limitations": limitations, "run": {"taskId": self.job.task_id, "sessionId": self.job.session_id,
                    "status": "partial" if partial else "completed", "startedAt": self.job.started_at, "finishedAt": now(),
                    "stopReason": reason, "model": self.settings.model, "modelCalls": self.job.model_calls,
                    "usage": self.job.usage, "steps": self.steps}}

    async def run(self):
        self.job.status = "running"
        self.job.emit("run_started", "开始研究；模型将选择需要的报告和行情")
        invalid_finals = 0
        try:
            async with asyncio.timeout(self.limits.max_seconds):
                await self.prepare_methods()
                for self.steps in range(1, self.limits.max_steps + 1):
                    self.check_budget()
                    assistant = await self.model(self.context(), tool_specs=declarations())
                    self.messages.append(assistant)
                    self.job.emit("assistant_message", "模型提出研究动作" if assistant.get("tool_calls") else "模型提交研究报告")
                    calls = assistant.get("tool_calls") or []
                    if not calls:
                        try:
                            if json.loads(assistant.get('content') or '{}') == {'ready':True}:
                                assistant=await self.compose()
                            content = self.validate_content(assistant)
                            content = await self.review(content)
                            self.job.report = self.report(content)
                            self.job.status = "completed"
                            self.job.emit("run_completed", "研究完成，报告与证据已返回")
                            return
                        except ValueError as error:
                            diagnostics = '; '.join('.'.join(map(str,e['loc']))+': '+e['msg'] for e in error.errors()[:5]) if hasattr(error,'errors') else str(error)[:700]
                            write_json(self.tools.store.root/'invalid-reports'/f'{self.job.task_id}-{self.steps}.json',
                                       {'candidate':assistant.get('content'),'diagnostics':diagnostics})
                            # 错误草稿不反复堆入主上下文；事实与完整来源仍保留。
                            self.messages.pop()
                            invalid_finals += 1
                            self.job.emit('report_validation_failed','报告需修正：'+diagnostics[:300])
                            if invalid_finals >= 3:
                                raise BudgetStop("incomplete_evidence_or_report")
                            self.messages.append({"role": "user", "content": "报告尚未通过程序核查：" + diagnostics + "。请修正 JSON/引用或仅补关键证据，不重复穷尽取数。"})
                            continue
                    for call in calls:
                        self.check_budget()
                        name = call["function"]["name"]
                        record = {"toolCallId": call["id"], "name": name, "status": "running", "startedAt": now()}
                        self.job.tool_calls.append(record)
                        self.job.emit("tool_started", "执行工具：" + name, toolCallId=call["id"], name=name)
                        try:
                            arguments = json.loads(call["function"]["arguments"])
                            if not isinstance(arguments, dict):
                                raise ValueError
                            signature = name + json.dumps(arguments, sort_keys=True, ensure_ascii=False)
                            prior = self.action_counts.get(signature, 0)
                            self.action_counts[signature] = prior + 1
                            # full 允许带覆盖进展的接续；其他同参动作反复执行不增加证据。
                            if prior >= 2 and not (name == "read_document" and arguments.get("mode", "full") == "full"):
                                raise ToolError("REPEATED_ACTION", "同一动作已多次返回，请使用已有结果或改查，避免重复循环。")
                            record["arguments"] = arguments
                            data = await self.dispatch(name, arguments)
                            result = {"status": "completed", "data": data}
                            record["status"] = "completed"
                        except (ValueError, ToolError) as error:
                            code = error.code if isinstance(error, ToolError) else "INVALID_TOOL_ARGUMENTS"
                            result = {"status": "failed", "error": {"code": code,
                                      "message": error.message if isinstance(error, ToolError) else "参数未通过工具校验。",
                                      "details": error.details if isinstance(error, ToolError) else {}}}
                            record.update(status="failed", errorCode=code)
                        record["finishedAt"] = now()
                        self.messages.append({"role": "tool", "tool_call_id": call["id"],
                                              "content": json.dumps(result, ensure_ascii=False)})
                        self.job.emit("tool_finished", name + (" 完成" if record["status"] == "completed" else " 未完成"),
                                      toolCallId=call["id"], status=record["status"])
                raise BudgetStop("step_budget")
        except (BudgetStop, TimeoutError) as error:
            reason = str(error) or "time_budget"
            self.job.report = self.report(reason=reason)
            self.job.status = "partial"
            self.job.emit("run_partial", "已保留部分结果：" + reason)
        except asyncio.CancelledError:
            self.job.status = "cancelled"
            self.job.report = self.report(reason="cancelled")
            self.job.emit("run_cancelled", "研究已停止，已完成的模型调用可能已计费")
        except ModelServiceError as error:
            self.job.status = "failed"
            self.job.error = {"code": error.code, "message": error.message}
            self.job.report = self.report(reason=error.code)
            self.job.emit("run_failed", error.message)
        except Exception:
            self.job.status = "failed"
            self.job.error = {"code": "RESEARCH_FAILED", "message": "研究执行失败，已保留完成范围，请检查后重试。"}
            self.job.report = self.report(reason="execution_error")
            self.job.emit("run_failed", "研究执行失败")
        finally:
            self.job.finished_at = now()
            for record in self.job.tool_calls:
                if record["status"] == "running":
                    record.update(status="interrupted", finishedAt=now())
