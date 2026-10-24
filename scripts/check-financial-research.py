"""离线验证Skill、原页协议、财务数据与同比；不会调用模型账户。"""

import asyncio
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apps/agent'))
from app.core.config import ModelSettings
from app.core.research_skills import UPSTREAM_ROOT, load_research_skill, read_reference
from app.schemas.agent import AgentResearchRequest
from app.schemas.financial import InspectArguments, VisualResult
from app.services.agent_runner import AgentRunner, RunLimits
from app.services.financial_data import build_financial_data, locate_summary_pages, verified_points, yoy
from app.services.research_jobs import ResearchJob
from app.tools.contracts import ToolError
from app.tools.visuals import render_pages

DOC={'documentId':'cninfo-1234567890','title':'测试公司2025年年度报告','fiscalYear':2025,'reportType':'annual',
     'publishedAt':'2026-03-01','pageCount':1,'sourceUrl':'https://static.cninfo.com.cn/finalpage/2026-03-01/1234567890.PDF','sha256':'fixture'}
TEXT='主要会计数据 营业收入（元） 200.00 100.00 归属于上市公司股东的净利润（元） 30.00 20.00 经营活动产生的现金流量净额（元） -10.00 15.00'


def result():
    return VisualResult.model_validate({'observations':[{'page':1,'summary':'观察到列头2025、2024与金额元。','uncertainties':[]}],
        'financialPoints':[{'metric':key,'year':year,'period':'annual','rawValue':raw,'unit':'元','page':1}
            for key,values in [('revenue',['200.00','100.00']),('netProfit',['30.00','20.00']),('operatingCashFlow',['-10.00','15.00'])]
            for year,raw in zip([2025,2024],values)]})


class DataChecks(unittest.TestCase):
    def test_01_vendor_integrity_and_skill_loaded(self):
        manifest=json.loads((UPSTREAM_ROOT/'UPSTREAM.json').read_text(encoding='utf-8'))
        for entry in manifest['files']:
            self.assertEqual(sha256((UPSTREAM_ROOT/entry['path']).read_bytes()).hexdigest(),entry['sha256'])
        skill=load_research_skill()
        self.assertTrue(skill['upstreamContent'] and skill['instructions'] and skill['version'])
        self.assertEqual(len(skill['references']),16)

    def test_02_reference_allowlist_and_pagination(self):
        path=next(p for p in read_reference({'reference':'catalog'})['files'] if p.endswith('task4-chart-generation.md'))
        first=read_reference({'reference':path}); second=read_reference({'reference':path,'offset':first['nextOffset']})
        self.assertEqual(first['content']+second['content'],(UPSTREAM_ROOT/path).read_text(encoding='utf-8')[:20000])
        with self.assertRaises(ToolError): read_reference({'reference':'../../.env'})

    def test_03_only_matching_numbers_and_units_enter_dataset(self):
        points,gaps=verified_points(result(),DOC,{1:TEXT})
        self.assertEqual(len(points),6);self.assertFalse(gaps)
        bad=result();bad.financial_points[0].raw_value='999.99';bad.financial_points[1].unit='万元'
        points,gaps=verified_points(bad,DOC,{1:TEXT})
        self.assertEqual(len(points),4);self.assertEqual(len(gaps),2)

    def test_04_same_period_and_future_year_guard(self):
        bad=result();bad.financial_points[0].period='h1';bad.financial_points[1].year=2027
        self.assertEqual(len(verified_points(bad,DOC,{1:TEXT})[0]),4)

    def test_05_yoy_positive_negative_zero_missing(self):
        self.assertEqual(yoy(200,100)['value'],100)
        self.assertAlmostEqual(yoy(-10,15)['value'],-166.6667)
        for prior in [None,0,-10]:self.assertIsNone(yoy(20,prior)['value'])

    def test_06_conflicts_excluded_and_periods_separate(self):
        points,_=verified_points(result(),DOC,{1:TEXT})
        conflict=deepcopy(points[0]);conflict['value']=300
        half=deepcopy(points[0]);half.update(period='h1',value=50)
        data=build_financial_data(points+[conflict,half])
        annual=next(d for d in data['datasets'] if d['id']=='annual')
        self.assertNotIn('revenue',annual['rows'][-1]['values'])
        self.assertEqual(next(d for d in data['datasets'] if d['id']=='h1')['rows'][0]['values']['revenue'],50)
        self.assertTrue(any('冲突' in g for g in data['gaps']))

    def test_07_derived_margin_and_no_missing_zero_fill(self):
        points,_=verified_points(result(),DOC,{1:TEXT});data=build_financial_data(points)
        row=data['datasets'][0]['rows'][-1]
        self.assertEqual(row['values']['attributableMargin'],15)
        self.assertEqual(row['yoy']['revenue']['value'],100)
        self.assertNotIn('rdExpense',row['values'])

    def test_08_summary_location_not_written_page_number(self):
        self.assertEqual(locate_summary_pages([{'page':17,'text':TEXT}]),[17])
        self.assertEqual(locate_summary_pages([{'page':8,'text':'目录：主要会计数据'}]),[])

    def test_09_page_arguments_reject_bool_and_arbitrary_path(self):
        for pages in [[True],[0],['1']]:
            with self.assertRaises(ValueError): InspectArguments(documentId='cninfo-1234567890',pages=pages)


class FakeStore:
    def __init__(self,root):self.root=root
    def metadata(self,_id):return DOC
    def loaded(self,_id):return DOC,[{'page':1,'text':TEXT}]


class FakeTools:
    def __init__(self,root):self.store=FakeStore(root)
    def execute(self,name,args):
        if name=='fetch_document':data={'document':DOC}
        else:data={'document':DOC,'pages':[{'page':1,'width':10,'height':10,'imageSha256':'imagefixture',
                                         'imageDataUrl':'data:image/png;base64,ZmFrZQ==','text':TEXT}]}
        return {'status':'completed','data':data}


class VisionChecks(unittest.IsolatedAsyncioTestCase):
    async def test_13_context_transmits_one_current_dataset_and_keeps_original_notes(self):
        with TemporaryDirectory() as temporary:
            runner=AgentRunner(ResearchJob(AgentResearchRequest(target='测试',question='研究',asOfDate='2026-10-23')),FakeTools(Path(temporary)),ModelSettings('test'))
            runner.financial_points=verified_points(result(),DOC,{1:TEXT})[0]
            note={'summary':'s'*1000,'facts':[{'text':'t'*1000,'pages':[1]} for _ in range(6)],'gaps':[]}
            payload={'status':'completed','data':{'sourceId':DOC['documentId'],'notes':[note],'financialData':{'duplicate':'x'*100000}}}
            runner.messages += [{'role':'tool','tool_call_id':str(i),'content':json.dumps(payload)} for i in range(6)]
            context=runner.context()
            self.assertLess(len(json.dumps(context)),80000)
            self.assertEqual(sum('financialData' in m['content'] for m in context if m['role']=='user'),1)
            self.assertEqual(len(json.loads(runner.messages[-1]['content'])['data']['notes'][0]['facts']),6)

    async def test_10_image_parts_sent_without_text_and_cached_with_provenance(self):
        received=[]
        async def model(settings,messages,**kwargs):
            received.append(messages)
            return {'role':'assistant','content':result().model_dump_json(by_alias=True)},{'total_tokens':50}
        with TemporaryDirectory() as temporary:
            tools=FakeTools(Path(temporary));settings=ModelSettings('test','http://127.0.0.1:1','test')
            req=AgentResearchRequest(target='测试',question='研究财务',asOfDate='2026-10-23')
            job=ResearchJob(req);runner=AgentRunner(job,tools,settings,completion=model)
            response=await runner.inspect({'documentId':DOC['documentId'],'pages':[1]})
            self.assertEqual(len(received),1)
            parts=received[0][1]['content'];self.assertTrue(any(p['type']=='image_url' for p in parts))
            self.assertNotIn('200.00',json.dumps(parts[0]))
            self.assertEqual(response['verifiedPointCount'],6)
            other=ResearchJob(req);again=AgentRunner(other,tools,settings,completion=model)
            cached=await again.inspect({'documentId':DOC['documentId'],'pages':[1]})
            self.assertEqual(len(received),1);self.assertEqual(cached['originRunId'],job.task_id)
            self.assertTrue(cached['cacheReused'])

    async def test_11_failed_visual_citation_not_recorded(self):
        async def model(*args,**kwargs):
            bad=result().model_dump(by_alias=True);bad['observations'][0]['page']=9
            return {'role':'assistant','content':json.dumps(bad)},{'total_tokens':50}
        with TemporaryDirectory() as temporary:
            job=ResearchJob(AgentResearchRequest(target='测试',question='研究',asOfDate='2026-10-23'))
            runner=AgentRunner(job,FakeTools(Path(temporary)),ModelSettings('test'),completion=model)
            with self.assertRaises(ToolError):await runner.inspect({'documentId':DOC['documentId'],'pages':[1]})
            self.assertFalse(runner.visual_readings)

    async def test_12_visual_budget_and_after_cutoff(self):
        with TemporaryDirectory() as temporary:
            job=ResearchJob(AgentResearchRequest(target='测试',question='研究',asOfDate='2026-10-23'))
            runner=AgentRunner(job,FakeTools(Path(temporary)),ModelSettings('test'),limits=replace(RunLimits(),max_visual_pages=0))
            with self.assertRaises(ToolError):await runner.inspect({'documentId':DOC['documentId'],'pages':[1]})
            self.assertEqual(job.model_calls,0)


if __name__=='__main__':unittest.main(verbosity=2)
