"""真实PDF分页/PNG渲染与脚本视觉响应；没有真实模型调用。"""
from dataclasses import replace
from io import BytesIO
import json
import unittest

from pypdf import PdfReader, PdfWriter
from tests.support import RunnerFixture, FakeModel, USAGE, DOC_ID, fixtures, report, section
from app.core.agent_prompts import VISION_SYSTEM
from app.core.config import ModelServiceError
from app.schemas.agent import Citation
from app.services.agent_runner import AgentRunner
from app.services.reading_coverage import reading_complete
from app.services.research_recovery import load_recovery
from app.tools.contracts import ToolError


class VisualModel(FakeModel):
    def __init__(self, fail_page=None):
        super().__init__()
        self.fail_page = fail_page
        self.visual_pages = []

    async def __call__(self, settings, messages, **kwargs):
        if messages[0].get('content') != VISION_SYSTEM:
            return await super().__call__(settings, messages, **kwargs)
        parts = messages[1]['content']
        pages = [p['page'] for p in json.loads(parts[0]['text'])['pages']]
        assert any(p.get('type') == 'image_url' for p in parts)
        self.visual_pages.extend(pages)
        if self.fail_page in pages:
            raise ModelServiceError('MODEL_UNAVAILABLE', 'isolated visual interruption')
        return {'role': 'assistant', 'content': json.dumps({'observations': [
            {'page': p, 'summary': '实际查看本页图像，隔离样本为空白页。', 'uncertainties': []} for p in pages], 'financialPoints': []})}, USAGE


class ScanReadingTests(RunnerFixture, unittest.IsolatedAsyncioTestCase):
    async def prepare(self, *, four_pages=False, model=None, vision=True, limit=12):
        raw = fixtures.sample_pdf()
        if four_pages:
            writer = PdfWriter()
            for page in PdfReader(BytesIO(raw)).pages:
                writer.add_page(page)
            writer.add_blank_page(width=595, height=842)
            stream = BytesIO(); writer.write(stream); raw = stream.getvalue()
        self.tools.provider.transport.data = raw
        job, runner = self.runner(model or VisualModel(), limits={'max_visual_pages': limit}, includeMarket=False)
        if vision:
            runner.settings = replace(runner.settings, vision_models=(runner.settings.model,))
        await runner.find_documents({'company': '同花顺', 'years': [2024], 'asOfDate': '2026-10-23'})
        return job, runner

    async def test_empty_page_not_complete_until_actual_image_call(self):
        model = VisualModel()
        _, runner = await self.prepare(model=model)
        result = await runner.read({'documentId': DOC_ID})
        progress = result['coverage']
        self.assertFalse(progress['textComplete'])
        self.assertTrue(reading_complete(progress))
        self.assertEqual(progress['emptyTextPages'], [3])
        self.assertEqual(progress['visuallyProcessedPages'], [3])
        self.assertEqual(model.visual_pages, [3])
        self.assertTrue(runner.check_citation(Citation(sourceId=DOC_ID, page=3)))
        recalled = await runner.recall_research_context({'kind': 'visual_notes', 'sourceId': DOC_ID, 'batch': 0})
        self.assertEqual(recalled['pages'], [3])

    async def test_visual_interruption_resumes_only_unseen_page(self):
        first = VisualModel(fail_page=4)
        job, runner = await self.prepare(four_pages=True, model=first)
        with self.assertRaises(ModelServiceError):
            await runner.read({'documentId': DOC_ID})
        self.assertEqual(runner.coverage[DOC_ID]['visuallyProcessedPages'], [3])
        self.assertFalse(reading_complete(runner.coverage[DOC_ID]))
        self.assertFalse(runner.check_citation(Citation(sourceId=DOC_ID, page=4)))
        model = VisualModel()
        restored = AgentRunner(job, self.tools, runner.settings, completion=model, recovery=load_recovery(self.tools, job.task_id))
        result = await restored.read({'documentId': DOC_ID})
        self.assertTrue(reading_complete(result['coverage']))
        self.assertEqual(model.visual_pages, [4])
        self.assertEqual(model.count('reading'), 0)

    async def test_unsupported_vision_keeps_gap_and_rejects_empty_citation(self):
        _, runner = await self.prepare(vision=False)
        await runner.read({'documentId': DOC_ID})
        self.assertFalse(reading_complete(runner.coverage[DOC_ID]))
        self.assertFalse(runner.check_citation(Citation(sourceId=DOC_ID, page=3)))

    async def test_visual_budget_preserves_text_and_unread_page(self):
        _, runner = await self.prepare(limit=0)
        with self.assertRaises(ToolError):
            await runner.read({'documentId': DOC_ID})
        self.assertEqual(runner.coverage[DOC_ID]['processedPages'], [1,2,3])
        self.assertFalse(reading_complete(runner.coverage[DOC_ID]))

    async def test_ready_cannot_start_writer_while_selected_scan_is_unread(self):
        model = VisualModel()
        _, runner = await self.prepare(vision=False, model=model)
        await runner.read({'documentId': DOC_ID})
        assistant = {'role': 'assistant', 'content': '{"ready":true}'}
        runner.messages.append(assistant)
        self.assertFalse(await runner.finish(assistant))
        self.assertIsNone(runner.writing_state)
        self.assertEqual(model.count('compose'), 0)
        self.assertIn('证据尚未就绪', runner.messages[-1]['content'])

    async def test_resume_defers_premature_draft_and_preserves_reading(self):
        model = VisualModel()
        job, runner = await self.prepare(model=model)
        await runner.read({'documentId': DOC_ID})
        runner.coverage[DOC_ID]['visuallyProcessedPages'] = []
        runner.coverage[DOC_ID]['readingComplete'] = False
        runner.visual_readings = []
        runner.writing_state = {'sections': [{'heading': '过早草稿', 'content': '旧内容'}]}
        runner.checkpoint()
        restored_model = VisualModel()
        restored_model.script = [[('read_document', {'documentId': DOC_ID})], 'final']
        restored_model.final = report([section('证据', '原文事实', page=1), section('图像页', '实际查看图像', page=3)])
        from app.services.research_jobs import ResearchJob
        child = ResearchJob(job.request)
        restored = AgentRunner(child, self.tools, runner.settings, completion=restored_model, recovery=load_recovery(self.tools, job.task_id))
        await restored.run()
        self.assertEqual(child.status, 'completed', child.error)
        self.assertTrue(any(e['type'] == 'writing_deferred' for e in child.events))
        self.assertEqual(restored_model.count('reading'), 0)


if __name__ == '__main__':
    unittest.main()
