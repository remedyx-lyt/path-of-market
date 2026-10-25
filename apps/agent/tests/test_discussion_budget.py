"""真实故障回归：大报告追问、旧检查点、取证预算收尾与新增资料引用。无网络/模型费用。"""
from copy import deepcopy
import json
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from support import RunnerFixture, SETTINGS, USAGE, DOC_ID, report, tool_call
from app.schemas.discussion import FollowupRequest
from app.services.discussion_context import partial_answer, report_view, select_history
from app.services.report_discussion import DiscussionRunner, SupplementRequired
from app.services.research_jobs import ResearchJob
from app.services.research_recovery import STATE_FIELDS, pending_calls, load_recovery
from app.services.runtime import BudgetStop, RunLimits
from app.services.session_recorder import SessionRecorder


WEB = "web-new-article"


def response(citations=None):
    return {"role": "assistant", "content": json.dumps({"answer": "新读报道补充了项目进展，公告计划仍需后续核实。",
            "citations": citations or [{"sourceId": WEB, "page": None}], "sectionEdits": [], "summary": None}, ensure_ascii=False)}


class DiscussionBudget(RunnerFixture, unittest.IsolatedAsyncioTestCase):
    async def make_discussion(self, completion=None, message="多查阅公开资料，补充后直接文字给我", limits=None):
        old_job, old = self.runner()
        old.messages += [{"role": "user", "content": "RESEARCH_TRACE" * 20000}]
        base = {**report(), "sources": [{"sourceId": DOC_ID}], "marketData": {"series": ["HEAVY_MARKET" * 50000]},
                "financialData": {"values": ["HEAVY_FINANCIAL" * 30000]}}
        parent = str(uuid4())
        node = {"id": parent, "parentId": None, "type": "report", "runId": old_job.task_id, "report": base}
        recovery = {"messages": old.messages, "messageEntryIds": [str(uuid4()) for _ in old.messages],
                    "state": {name: deepcopy(getattr(old, name)) for name in STATE_FIELDS}, "taskId": old_job.task_id}
        prepared = {"entries": [node], "base": node, "recovery": recovery, "rootTaskId": old_job.task_id, "nextVersion": 2}
        request = FollowupRequest(message=message, parentId=parent, requestId=uuid4())
        job = ResearchJob(old_job.request)
        with patch.object(SessionRecorder, "start"), patch.object(SessionRecorder, "close", new=AsyncMock(return_value=True)):
            runner = DiscussionRunner(job, self.tools, SETTINGS, prepared, request,
                                      completion=completion or AsyncMock(return_value=(response(), USAGE)), limits=limits)
        runner.load_user_memory = AsyncMock()
        runner.sources[DOC_ID] = {"sourceId": DOC_ID, "title": "旧报告", "kind": "document", "pageCount": 2}
        runner.coverage[DOC_ID] = {"processedPages": [1, 2], "textComplete": True}
        runner.sources[WEB] = {"sourceId": WEB, "title": "本次新增报道", "kind": "web", "publishedAt": "2026-10-22", "citationEligible": True}
        runner.coverage[WEB] = {"textComplete": True, "readingComplete": True, "unit": "segment"}
        runner.notes[WEB] = [{"summary": "新增报道中的项目进展", "facts": [{"text": "待核实的后续计划", "pages": [1]}], "gaps": []}]
        return job, runner

    async def run_local(self, runner):
        with patch.object(SessionRecorder, "close", new=AsyncMock(return_value=True)):
            await runner.run()

    async def test_large_research_and_chart_payload_not_replayed_but_evidence_retained(self):
        _, runner = await self.make_discussion()
        text = json.dumps(runner.reply_context(), ensure_ascii=False)
        self.assertNotIn("RESEARCH_TRACE", text)
        self.assertNotIn("HEAVY_MARKET", text)
        self.assertNotIn("HEAVY_FINANCIAL", text)
        self.assertIn("新增报道中的项目进展", text)
        self.assertIn("本次新增报道", text)
        self.assertIn("HEAVY_MARKET", json.dumps(runner.base))
        self.assertEqual(runner.discussion_context_version, 1)

    def test_legacy_failed_chat_keeps_chat_tool_pair_and_ids_only_on_selected_branch(self):
        history = [{"role": "system", "content": "system"}, {"role": "user", "content": "task"},
                   {"role": "assistant", "content": "old research"}, {"role": "user", "content": "first chat"},
                   {"role": "assistant", "tool_calls": [tool_call(0, 0, "read_web_document", {})]},
                   {"role": "tool", "tool_call_id": "call_0_0", "content": "saved new source"}]
        recovery = {"messages": history, "messageEntryIds": list("abcdef"), "state": {}}
        chain = [{"id": "follow", "type": "followup", "runId": "chat"},
                 {"id": "d", "type": "message", "runId": "chat"}]
        kept, ids, migrated = select_history(recovery, chain, 2)
        self.assertTrue(migrated)
        self.assertEqual(ids, list("abdef"))
        self.assertNotIn(history[2], kept)
        self.assertFalse(pending_calls(kept))
        self.assertEqual(history, recovery["messages"])

    def test_missing_boundary_does_not_discard_conversation(self):
        recovery = {"messages": [{"role": "user", "content": "preserve"}], "state": {}}
        kept, _, migrated = select_history(recovery, [{"type": "followup", "runId": "unknown"}], 0)
        self.assertFalse(migrated)
        self.assertEqual(kept, recovery["messages"])

    def test_migrated_checkpoint_keeps_history_and_summary_boundary(self):
        recovery = {"messages": [{"role": "user", "content": "prior chat"}], "messageEntryIds": ["id"],
                    "state": {"discussion_context_version": 1}}
        self.assertEqual(select_history(recovery, [], 2), (recovery["messages"], ["id"], False))

    async def test_token_reserve_answers_with_saved_new_material_instead_of_failure(self):
        model = AsyncMock(return_value=(response(), USAGE))
        job, runner = await self.make_discussion(model)
        job.usage["total_tokens"] = 940000
        await self.run_local(runner)
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(model.await_count, 1)
        self.assertIsNone(model.call_args.kwargs["tools"])
        self.assertTrue(any(e["type"] == "discussion_wrapup" for e in job.events))
        self.assertIn("新增报道中的项目进展", json.dumps(model.call_args.args[1], ensure_ascii=False))
        self.assertEqual(job.followup["citations"][0]["sourceId"], WEB)
        self.assertTrue(load_recovery(self.tools, job.task_id, allow_completed=True)["state"]["discussion_context_version"])

    async def test_model_call_reserve_also_finishes(self):
        model = AsyncMock(return_value=(response(), USAGE))
        job, runner = await self.make_discussion(model)
        job.model_calls = 68
        await self.run_local(runner)
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(job.model_calls, 69)

    async def test_time_reserve_answers_before_timeout(self):
        model = AsyncMock(return_value=(response(), USAGE))
        job, runner = await self.make_discussion(model)
        runner.began -= runner.limits.max_seconds - 45
        await self.run_local(runner)
        self.assertEqual(job.status, "completed", job.error)
        self.assertIsNone(model.call_args.kwargs["tools"])

    async def test_budget_failed_retry_uses_saved_supplement_without_search(self):
        model = AsyncMock(return_value=(response(), USAGE))
        job, runner = await self.make_discussion(model)
        parent = runner.prepared["entries"][-1]
        parent.update(type="chat_turn", status="failed", userMessage=runner.followup_request.message,
                      error={"message": "原因：token_budget"})
        await self.run_local(runner)
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(model.await_count, 1)
        self.assertIsNone(model.call_args.kwargs["tools"])
        self.assertIn("新增报道中的项目进展", json.dumps(model.call_args.args[1], ensure_ascii=False))

    async def test_budget_mid_tool_group_closes_every_pending_call_before_answer(self):
        calls = [tool_call(0, i, "read_web_document", {"sourceId": WEB}) for i in range(2)]
        model = AsyncMock(side_effect=[({"role": "assistant", "content": None, "tool_calls": calls}, USAGE), (response(), USAGE)])
        job, runner = await self.make_discussion(model)
        runner.run_tool_call = AsyncMock(side_effect=BudgetStop("research_token_budget"))
        await self.run_local(runner)
        self.assertEqual(job.status, "completed", job.error)
        self.assertFalse(pending_calls(runner.messages))
        self.assertEqual(sum(m["role"] == "tool" for m in runner.messages), 2)
        self.assertIsNone(model.call_args.kwargs["tools"])

    async def test_plaintext_answer_gets_json_only_repair_not_more_search(self):
        model = AsyncMock(side_effect=[({"role": "assistant", "content": "裸文字"}, USAGE), (response(), USAGE)])
        job, runner = await self.make_discussion(model)
        await self.run_local(runner)
        self.assertEqual(job.status, "completed", job.error)
        self.assertIsNone(model.call_args.kwargs["tools"])
        self.assertTrue(any(e.get("diagnostics") for e in job.events if e["type"] == "report_validation_failed"))

    async def test_old_only_answer_rejected_when_new_evidence_exists(self):
        _, runner = await self.make_discussion()
        with self.assertRaisesRegex(ValueError, "未引用任何新读资料"):
            runner.validate_answer(response([{"sourceId": DOC_ID, "page": 1}]))
        self.assertTrue(runner.validate_answer(response()))

    async def test_unknown_date_and_unread_citations_identified_without_relaxing_check(self):
        _, runner = await self.make_discussion()
        runner.sources[WEB]["publishedAt"] = ""
        with self.assertRaisesRegex(ValueError, WEB):
            runner.validate_answer(response())
        with self.assertRaisesRegex(ValueError, "web-not-read"):
            runner.validate_answer(response([{"sourceId": "web-not-read", "page": None}]))

    async def test_final_model_input_removes_unread_snippet_numbers_and_undated_notes(self):
        model = AsyncMock(return_value=(response([{"sourceId": DOC_ID, "page": 1}]), USAGE))
        _, runner = await self.make_discussion(model, message="解释报告")
        runner.sources[WEB]["publishedAt"] = ""
        runner.notes[WEB][0]["summary"] = "UNDATED_CLAIM_12345"
        search = {"status": "completed", "data": {"results": [{"sourceId": "web-unread", "title": "待通读文章",
                   "snippet": "UNREAD_CLAIM_98765"}]}}
        runner.messages.append({"role": "assistant", "content": None, "tool_calls": [tool_call(0, 0, "search_public_information", {})]})
        runner.messages.append({"role": "tool", "tool_call_id": "call_0_0", "content": json.dumps(search)})
        before = deepcopy(list(runner.messages))
        await runner.next_turn(final=True)
        text = json.dumps(model.call_args.args[1], ensure_ascii=False)
        self.assertNotIn("UNREAD_CLAIM_98765", text)
        self.assertNotIn("UNDATED_CLAIM_12345", text)
        self.assertIn("待通读文章", text)
        self.assertEqual(before, runner.messages)

    async def test_invalid_answers_stop_after_two_repairs_not_twelve_large_calls(self):
        model = AsyncMock(return_value=({"role": "assistant", "content": "not-json"}, USAGE))
        job, runner = await self.make_discussion(model)
        await self.run_local(runner)
        self.assertEqual(job.status, "failed")
        self.assertEqual(model.await_count, 3)
        self.assertEqual(job.error["code"], "MODEL_INVALID_RESPONSE")

    async def test_simple_question_can_use_original_report_without_search(self):
        model = AsyncMock(return_value=(response([{"sourceId": DOC_ID, "page": 1}]), USAGE))
        job, runner = await self.make_discussion(model, message="解释一下原报告的现金流")
        await self.run_local(runner)
        self.assertEqual(job.status, "completed", job.error)
        self.assertFalse(job.tool_calls)

    async def test_section_tables_can_be_recalled_without_replaying_whole_report(self):
        _, runner = await self.make_discussion()
        runner.base["sections"][0]["tables"] = [{"title": "单章底稿", "rows": [["原表数字"]]}]
        result = await runner.recall_research_context({"kind": "report_section", "sectionIndex": 0})
        self.assertEqual(result["section"]["tables"], runner.base["sections"][0]["tables"])
        self.assertNotIn("HEAVY_MARKET", json.dumps(result))

    def test_streaming_json_only_exposes_complete_answer_characters(self):
        self.assertEqual(partial_answer('{"answer":"正在回答\\n下一段\\u4e2d'), '正在回答\n下一段中')
        self.assertEqual(partial_answer('{"answer":"A\\u4e'), 'A')
        self.assertEqual(partial_answer('{"answer":"A\\ud83d'), 'A')
        self.assertEqual(partial_answer('{"answer":"A\\ud83d\\ude00"}'), 'A😀')
        self.assertEqual(partial_answer('{"answer":"含\\"引号\\"和\\\\路径'), '含"引号"和\\路径')
        self.assertEqual(partial_answer('先读取工具'), '')

    async def test_old_supplement_does_not_count_as_this_turn_new_evidence(self):
        _, runner = await self.make_discussion(message="再查一些公开资料，然后补充行业背景")
        runner.discussion_source_baseline = [DOC_ID, WEB]
        with self.assertRaises(SupplementRequired):
            runner.validate_answer(response())
        self.assertFalse(runner.eligible_supplement())
        self.assertTrue(runner.validate_answer(response(), final=True))

    async def test_missing_new_material_keeps_tools_available_instead_of_format_wrapup(self):
        fresh = 'web-fresh-this-question'
        calls = [tool_call(0, 0, 'read_web_document', {'sourceId': fresh})]
        model = AsyncMock(side_effect=[(response(), USAGE), ({'role': 'assistant', 'content': None, 'tool_calls': calls}, USAGE),
                                     (response([{'sourceId': fresh, 'page': None}]), USAGE)])
        job, runner = await self.make_discussion(model, message="再查一些公开资料")
        runner.discussion_source_baseline = [DOC_ID, WEB]
        async def read(call):
            runner.sources[fresh] = {**runner.sources[WEB], 'sourceId': fresh, 'title': '本次新报道'}
            runner.coverage[fresh] = deepcopy(runner.coverage[WEB])
            runner.notes[fresh] = deepcopy(runner.notes[WEB])
            runner.messages.append({'role':'tool', 'tool_call_id':call['id'], 'content':'{"status":"completed"}'})
        runner.run_tool_call = read
        await self.run_local(runner)
        self.assertEqual(job.status, 'completed', job.error)
        self.assertIsNotNone(model.call_args_list[1].kwargs['tools'])
        self.assertEqual(job.followup['citations'][0]['sourceId'], fresh)

    async def test_final_without_fresh_evidence_explicitly_marks_supplement_incomplete(self):
        job, runner = await self.make_discussion(message="再查公开资料")
        runner.discussion_source_baseline = [DOC_ID, WEB]
        runner.job.usage['total_tokens'] = 940000
        await self.run_local(runner)
        self.assertEqual(job.status, 'completed', job.error)
        self.assertTrue(job.followup['answer'].startswith('【补查未完成】'))

    async def test_streamed_draft_is_visible_then_removed_on_validation_failure(self):
        observations = []
        job, runner = await self.make_discussion()
        async def stream(settings, messages, **options):
            observations.append(job.followup)
            options['on_text']('{"answer":"正在写的新资料补充')
            self.assertTrue(job.snapshot()['followup']['draft'])
            self.assertEqual(job.snapshot()['followup']['answer'], '正在写的新资料补充')
            if len(observations) == 1:
                return {'role':'assistant', 'content':'invalid-json'}, USAGE
            return response(), USAGE
        runner.completion = stream
        await self.run_local(runner)
        self.assertEqual(job.status, 'completed', job.error)
        self.assertEqual(observations, [None, None])
        self.assertNotIn('draft', job.followup)

    async def test_disabled_search_can_only_return_explicit_incomplete_answer(self):
        job, runner = await self.make_discussion(message="再查公开资料")
        runner.discussion_source_baseline = [DOC_ID, WEB]
        self.tools.public_web.gateway.settings = __import__('dataclasses').replace(self.tools.public_web.gateway.settings, enabled=False)
        await self.run_local(runner)
        self.assertEqual(job.status, 'completed', job.error)
        self.assertTrue(job.followup['answer'].startswith('【补查未完成】'))
        self.assertEqual(job.model_calls, 3)

    async def test_explicit_search_requires_native_tool_and_uses_small_context(self):
        _, runner = await self.make_discussion(message="再查行业和大盘")
        runner.discussion_source_baseline = [DOC_ID, WEB]
        runner.base['sections'][0]['content'] = 'LARGE_REPORT' * 10000
        self.assertEqual(runner.supplement_tool_choice()['function']['name'], 'search_public_information')
        context = json.dumps(runner.supplement_context(), ensure_ascii=False)
        self.assertNotIn('LARGE_REPORT', context)
        self.assertNotIn('RESEARCH_TRACE', context)
        self.assertIn('再查行业和大盘', context)
        runner.web_discovered['web-fresh'] = {'format': 'web', 'publishedAt': '2026-10-22'}
        runner.job.tool_calls.append({'name': 'search_public_information', 'status': 'completed'})
        self.assertEqual(runner.supplement_tool_choice()['function']['name'], 'read_web_document')
        runner.job.tool_calls += [{'name': 'read_web_document', 'arguments': {'sourceId': 'web-fresh'}, 'status': 'failed'}] * 2
        self.assertEqual(runner.supplement_tool_choice()['function']['name'], 'search_public_information')

    async def test_discovery_numbers_never_reach_answer_context(self):
        _, runner = await self.make_discussion(message="再查行业和大盘")
        runner.messages.append({'role': 'tool', 'tool_call_id': 'search', 'content': json.dumps({
            'status': 'completed', 'data': {'results': [{'sourceId': 'web-unread', 'title': '待阅读',
                'snippet': 'UNREAD_PRICE_3713.03', 'url': 'https://example.com/page', 'publishedAt': '2026-10-22'}]}})})
        text = json.dumps(runner.supplement_context(), ensure_ascii=False)
        self.assertNotIn('UNREAD_PRICE_3713.03', text)
        self.assertIn('待阅读', text)
        self.assertIn('新增报道中的项目进展', text)

    async def test_provider_ignoring_required_tool_cannot_masquerade_as_searched(self):
        job, runner = await self.make_discussion(message="再查公开资料")
        runner.discussion_source_baseline = [DOC_ID, WEB]
        await self.run_local(runner)
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.error['code'], 'MODEL_INVALID_RESPONSE')
        self.assertEqual(runner.completion.await_count, 3)
        self.assertTrue(all(c.kwargs['tool_choice']['function']['name'] == 'search_public_information' for c in runner.completion.call_args_list))
        self.assertFalse(any(e['type'] == 'discussion_evidence_used' for e in job.events))

    async def test_questions_about_saved_material_or_no_search_do_not_force_new_research(self):
        for message in ['不用再查，解释现金流', '不要搜索公开资料，只解释报告', '上次补查的资料是什么意思']:
            _, runner = await self.make_discussion(message=message)
            self.assertFalse(runner.wants_supplement(), message)
        _, runner = await self.make_discussion(message='不要只看官网，再查一些行业资料')
        self.assertTrue(runner.wants_supplement())

    def test_report_view_preserves_indices_and_content_without_changing_report(self):
        base = report()
        snapshot = deepcopy(base)
        view = report_view(base)
        self.assertEqual([s["index"] for s in view["sections"]], [0, 1])
        self.assertEqual(base, snapshot)
