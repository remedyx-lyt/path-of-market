"""方法实际阅读、正文取数与自由选图检查；全部隔离，不调用模型账户。"""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apps/agent'))
from app.core.config import ModelSettings, ModelServiceError
from app.core.research_skills import load_method_bundle, UPSTREAM_ROOT
from app.schemas.agent import AgentResearchRequest
from app.schemas.financial import ExtractResult, parse_extraction
from app.services.agent_runner import AgentRunner
from app.services.financial_data import build_financial_data, verified_points
from app.services.report_figures import build_business_data, verified_segments, locate_detail_pages, plan_section_figures
from app.services.research_jobs import ResearchJob
from app.tools.contracts import ToolError

DOC={'documentId':'cninfo-1234567890','title':'测试2025年报','fiscalYear':2025,'reportType':'annual',
     'sourceUrl':'https://static.cninfo.com.cn/finalpage/2026-01-01/1234567890.PDF','publishedAt':'2026-01-01','pageCount':2}
TEXT='单位：元 2025年 2024年 营业收入 200.00 100.00 研发投入金额（元） 20.00 10.00 分产品 产品A 150.00 60.00 其他 50.00 40.00 分地区 境外 180.00 80.00 境内 20.00 20.00'
REQ=AgentResearchRequest(target='测试',question='最近两年经营变化与财务情况',asOfDate='2026-10-23',includeMarket=False,includeCurrentPeriod=False)

def extracted():
    return ExtractResult.model_validate({'financialPoints':[
        {'metric':metric,'year':year,'period':'annual','rawValue':value,'unit':'元','page':1,'quote':quote}
        for metric,quote,values in [('revenue','营业收入 200.00 100.00',['200.00','100.00']),('rdInvestment','研发投入金额（元） 20.00 10.00',['20.00','10.00'])]
        for year,value in zip([2025,2024],values)],'segmentPoints':[
        {'dimension':dim,'label':label,'year':2025,'period':'annual','rawValue':value,'unit':'元','page':1,'quote':quote}
        for dim,label,value,quote in [('product','产品A','150.00','产品A 150.00 60.00'),('product','其他','50.00','其他 50.00 40.00'),
                                     ('geography','境外','180.00','境外 180.00 80.00'),('geography','境内','20.00','境内 20.00 20.00')]],'gaps':[]})

def data():
    result=extracted(); points,_=verified_points(result,DOC,{1:TEXT});segments,_=verified_segments(result,DOC,{1:TEXT})
    return build_financial_data(points),segments

class DataChecks(unittest.TestCase):
    def test_16_main_accounting_table_precedes_incidental_visual_numbers(self):
        original={'metric':'revenue','year':2025,'period':'annual','value':200,'sourceId':DOC['documentId'],'page':1,'publishedAt':'2026-01-01','rawValue':'200.00','unit':'元','verification':'vision_and_text_number_match','verificationOrigin':'automatic_financial_summary'}
        incidental={**original,'value':150,'verificationOrigin':'model_tool','rawValue':'150.00'}
        row=build_financial_data([original,incidental])['datasets'][0]['rows'][0]
        self.assertEqual(row['values']['revenue'],200)

    def test_13_narrative_number_unit_and_precision(self):
        result=ExtractResult.model_validate({'financialPoints':[{'metric':'rdInvestment','year':2025,'period':'annual','rawValue':'20.00','unit':'万元','page':1,'quote':'本年度研发投入20.00万元。'}]})
        points,gaps=verified_points(result,DOC,{1:'单位：元 本年度研发投入20.00万元。'})
        self.assertFalse(gaps);self.assertEqual(points[0]['value'],200000)
        fine=deepcopy(points[0]);fine.update(value=200001,rawValue='200001.00',unit='元')
        row=build_financial_data(points+[fine])['datasets'][0]['rows'][0]
        self.assertEqual(row['values']['rdInvestment'],200001)
        bad=deepcopy(fine);bad.update(value=200001.01,rawValue='200001.01')
        self.assertFalse(build_financial_data([fine,bad])['datasets'])

    def test_14_one_invalid_entry_does_not_discard_valid_entries(self):
        body=extracted().model_dump(by_alias=True)
        body['financialPoints'].append({'metric':'invented','year':2025})
        parsed=parse_extraction(json.dumps(body))
        self.assertEqual(len(parsed.financial_points),4);self.assertEqual(len(parsed.segment_points),4);self.assertTrue(parsed.gaps)

    def test_15_split_table_heading_and_body_found_together(self):
        pages=[{'page':1,'text':'合并资产负债表 单位：元'}, {'page':2,'text':'流动资产：货币资金'},
               {'page':3,'text':'负债合计'}, {'page':4,'text':'合并利润表'}, {'page':5,'text':'营业总收入 营业成本'}]
        self.assertEqual(locate_detail_pages(pages),[1,2,3,4,5])

    def test_01_selected_originals_are_read_in_full(self):
        references=load_method_bundle(REQ)
        self.assertTrue(any(r['characters']>30000 for r in references))
        for r in references:
            self.assertEqual(r['content'],(UPSTREAM_ROOT/r['reference']).read_text(encoding='utf-8'))

    def test_02_task_routing_avoids_unavailable_valuation(self):
        request=REQ.model_copy(update={'question':'竞争同行对比'})
        refs=load_method_bundle(request)
        self.assertTrue(any('competitive-analysis' in r['reference'] for r in refs))
        self.assertFalse(any('dcf-model' in r['reference'] for r in refs))

    def test_03_prose_quote_must_match_amount_and_metric(self):
        result=extracted();result.financial_points[0].quote='模型编造 营业收入 200.00'
        points,gaps=verified_points(result,DOC,{1:TEXT})
        self.assertEqual(len(points),3);self.assertTrue(gaps)

    def test_04_dimensions_not_double_counted(self):
        financial,points=data();business=build_business_data(points,financial)
        self.assertEqual(len(business['datasets']),2)
        for d in business['datasets']:
            row=d['rows'][0];self.assertEqual(sum(p['value'] for p in row['items']),200)
            self.assertEqual(sum(p['share'] for p in row['items']),100)

    def test_05_incomplete_components_keep_residual_not_renormalized(self):
        financial,points=data();business=build_business_data(points[:1],financial)
        row=business['datasets'][0]['rows'][0]
        self.assertEqual(row['items'][0]['share'],75)
        self.assertTrue(row['items'][1]['derived']);self.assertEqual(row['items'][1]['value'],50)

    def test_06_conflicts_or_components_exceeding_total_not_plotted(self):
        financial,points=data();bad=deepcopy(points[0]);bad['value']=300
        self.assertFalse(build_business_data([bad],financial)['datasets'])
        result=build_business_data(points+[bad],financial)
        self.assertTrue(any('冲突' in s for s in result['gaps']))

    def test_07_period_future_and_unit_guard(self):
        result=extracted();result.segment_points[0].period='h1';result.segment_points[1].year=2027;result.segment_points[2].unit='万元'
        self.assertEqual(len(verified_segments(result,DOC,{1:TEXT})[0]),1)

    def test_08_model_selects_figures_no_per_section_quota(self):
        financial,points=data();business=build_business_data(points,financial)
        sections=[{'heading':'概览','topics':['business'],'chartIds':[],'businessIds':[]},
                  {'heading':'业务','topics':['business'],'chartIds':[],'businessIds':['product-annual']}]
        plan=plan_section_figures(sections,financial,business)
        self.assertFalse(plan[0]['businessDatasetIds']);self.assertEqual(plan[1]['businessDatasetIds'],['product-annual'])

    def test_09_discovery_uses_table_content_not_page_numbers(self):
        pages=[{'page':1,'text':'目录'}, {'page':2,'text':'营业收入构成 分产品 单位：元'},
               {'page':3,'text':'合并资产负债表 流动资产'}, {'page':4,'text':'母公司资产负债表'}]
        self.assertIn(2,locate_detail_pages(pages));self.assertNotIn(1,locate_detail_pages(pages))

class Store:
    def __init__(self,root):self.root=root
    def loaded(self,identifier):return DOC,[{'page':1,'text':TEXT},{'page':2,'text':'单位：元 2025年 负债合计 30.00'}]

class Tools:
    def __init__(self,root):self.store=Store(root)

class RunnerChecks(unittest.IsolatedAsyncioTestCase):
    async def test_18_ready_then_separate_report_and_review(self):
        limits=[]
        citation={'sourceId':DOC['documentId'],'page':1}
        content={'title':'完成研究','summary':'证据支持的分析','sections':[{'heading':'业务','content':'事实','citations':[citation]},{'heading':'风险','content':'观察','citations':[citation]}]}
        async def complete(settings,messages,**kwargs):
            limits.append(kwargs['max_tokens'])
            if kwargs.get('tools') and kwargs.get('tool_choice')!='none':result={'ready':True}
            elif 'references' in messages[1]['content'][:20]:
                path=json.loads(messages[1]['content'])['references'][0]['reference']
                check={'topic':'business','question':'q','evidenceNeeded':'e','figureIdea':'无','methodReference':path}
                result={'focus':'f','checks':[check]*3,'unavailable':[]}
            elif '核对财经研究报告' in messages[0]['content']:result=json.loads(messages[1]['content'])['candidate']
            else:result=content
            return {'role':'assistant','content':json.dumps(result)},{'total_tokens':10}
        with TemporaryDirectory() as temp:
            req=REQ.model_copy(update={'include_financials':False})
            job=ResearchJob(req);runner=AgentRunner(job,Tools(Path(temp)),ModelSettings('test'),completion=complete)
            runner.source(DOC);runner.coverage[DOC['documentId']].update(textComplete=True,processedPages=[1,2])
            await runner.run()
            self.assertEqual(job.status,'completed',job.error);self.assertEqual(limits,[6500,6500,14000,14000])

    async def test_19_invalid_response_usage_is_still_counted(self):
        async def complete(*args,**kwargs):
            error=ModelServiceError('MODEL_INVALID_RESPONSE','invalid');error.usage={'total_tokens':123};raise error
        with TemporaryDirectory() as temp:
            job=ResearchJob(REQ);runner=AgentRunner(job,Tools(Path(temp)),ModelSettings('test'),completion=complete)
            with self.assertRaises(ModelServiceError):await runner.model([{'role':'user','content':'test'}])
            self.assertEqual(job.usage['total_tokens'],123)

    async def test_17_long_tool_history_projected_with_recent_pages_kept(self):
        with TemporaryDirectory() as temp:
            runner=AgentRunner(ResearchJob(REQ),Tools(Path(temp)),ModelSettings('test'))
            for i in range(25):
                runner.messages.append({'role':'tool','tool_call_id':str(i),'content':json.dumps({'data':{'sourceId':DOC['documentId'],'page':1,'text':'原文'*4000}})})
            context=runner.context()
            self.assertLess(len(json.dumps(context,ensure_ascii=False)),80000)
            self.assertEqual(len(json.loads(context[-2]['content'])['data']['text']),8000)
            self.assertEqual(len(json.loads(runner.messages[-1]['content'])['data']['text']),8000)

    async def test_10_methods_actually_sent_to_model_and_planned(self):
        received=[]
        async def complete(settings,messages,**kwargs):
            payload=json.loads(messages[1]['content']); received.extend(payload['references'])
            check={'topic':'business','question':'收入增长来自哪里','evidenceNeeded':'分部收入','figureIdea':'收入结构图','methodReference':received[0]['reference']}
            return {'role':'assistant','content':json.dumps({'focus':'核对增长质量','checks':[check]*3,'unavailable':['缺一致预期，不做超预期判断']})},{'total_tokens':100}
        with TemporaryDirectory() as temp:
            runner=AgentRunner(ResearchJob(REQ),Tools(Path(temp)),ModelSettings('test'),completion=complete)
            await runner.prepare_methods()
            self.assertEqual(len(received),5);self.assertTrue(runner.method_usage['plan']['checks'])
            self.assertTrue(any(r['characters']>30000 for r in received));self.assertFalse(runner.method_usage['reviewed'])

    async def test_11_full_read_required_then_extract_and_cache(self):
        calls=[]
        async def complete(*args,**kwargs):
            calls.append(1);return {'role':'assistant','content':extracted().model_dump_json(by_alias=True)},{'total_tokens':30}
        with TemporaryDirectory() as temp:
            runner=AgentRunner(ResearchJob(REQ),Tools(Path(temp)),ModelSettings('test'),completion=complete)
            args={'documentId':DOC['documentId'],'pages':[1]}
            with self.assertRaises(ToolError):await runner.extract(args)
            runner.source(DOC);runner.coverage[DOC['documentId']]['textComplete']=True
            first=await runner.extract(args);second=await runner.extract(args)
            self.assertEqual(len(calls),1);self.assertEqual(first['segmentPointCount'],4);self.assertTrue(second['cacheReused'])
            self.assertTrue(first['businessData']['datasets'])

    async def test_12_qualitative_diagram_citations_checked(self):
        with TemporaryDirectory() as temp:
            runner=AgentRunner(ResearchJob(REQ),Tools(Path(temp)),ModelSettings('test'))
            runner.source(DOC);runner.coverage[DOC['documentId']].update(textComplete=True,processedPages=[1,2])
            citation={'sourceId':DOC['documentId'],'page':1}
            diagram={'kind':'cards','title':'风险观察','nodes':[{'label':'风险','detail':'证据','citations':[citation]}]*2}
            body={'title':'研究','summary':'结论','sections':[{'heading':'概览','content':'研究','topics':['business','performance','profitability','cashflow','balance_sheet','research','risks'],'citations':[citation]},
                  {'heading':'风险','content':'观察','topics':['risks'],'citations':[citation],'visual':diagram}]}
            runner.validate_content({'content':json.dumps(body)})
            body['sections'][1]['visual']['nodes'][0]['citations']=[{'sourceId':DOC['documentId'],'page':999}]
            with self.assertRaises(ValueError):runner.validate_content({'content':json.dumps(body)})

if __name__=='__main__':unittest.main(verbosity=2)
