"""研究方法计划（AgentRunner 的一部分）。

取证前完整读取按问题/预兆选出的原版方法，让模型形成可调整的研究计划。
- 没选预兆也会按问题选到相关 Skill；选了预兆，计划中必须有标记该预兆的专属检查。
- 方法参考放在请求开头、任务放在最后，固定顺序，便于 DeepSeek 前缀缓存跨研究命中。
- 同一任务、同一组方法与提示的计划结果会缓存复用（派生结果，记录来源运行 ID）。
- 计划失败不再中止整次研究：记录 plan_failed，继续用已加载的基础 Skill 研究，并在报告中说明。
"""

import json

from app.core.agent_prompts import METHOD_SYSTEM
from app.core.config import ModelServiceError
from app.core.omens import selected_omens
from app.core.research_skills import load_method_bundle
from app.schemas.agent import MethodPlan
from app.services.model_json import DerivedCache, ask_json, stable_key, validation_problems


class MethodMixin:
    def method_task(self):
        request = self.job.request
        task = {
            "target": request.target,
            "question": request.question,
            "userStyle": request.user_style,
            "asOfDate": request.as_of_date.isoformat(),
            "omens": [o.id for o in selected_omens(request)],
            "includeFinancials": request.include_financials,
            "includeMarket": request.include_market,
            "includeCurrentPeriod": request.include_current_period,
            "annualHistory": self.annual_context(),
        }
        preferences = self.memory_preferences()
        if preferences:
            task["userMemory"] = {"confirmedPreferences": preferences, "instruction": "仅参考相关偏好；本次问题/风格/截止日优先，记忆不是财务证据。"}
        return task

    async def prepare_methods(self):
        references = load_method_bundle(self.job.request)
        omens = selected_omens(self.job.request)
        paths = {r["reference"] for r in references}
        self.job.emit(
            "methods_started", "阅读相关原版金融方法，形成适合本次研究的方法计划", references=[r["reference"] for r in references]
        )
        # 稳定内容在前（方法全文、工具名），变化内容（预兆、任务）在后。
        body = {
            "references": references,
            "availableTools": [s["function"]["name"] for s in self.declarations()],
            "omenSpecs": [self.omen_brief(o) for o in omens],
            "task": self.method_task(),
            "outputSchema": MethodPlan.model_json_schema(by_alias=True),
        }
        messages = [{"role": "system", "content": METHOD_SYSTEM}, {"role": "user", "content": json.dumps(body, ensure_ascii=False)}]

        def parse(content):
            plan = MethodPlan.model_validate_json(content) if isinstance(content, str) else MethodPlan.model_validate(content)
            for check in plan.checks:
                # 短路径仅在唯一对应已提供文件时展开，绝不接受未加载的方法或模糊猜测。
                if check.method_reference not in paths:
                    candidates = [p for p in paths if p.endswith("/" + check.method_reference)]
                    if len(candidates) != 1:
                        raise ValueError("methodReference 必须唯一对应实际提供的参考文件路径")
                    check.method_reference = candidates[0]
                if check.omen is not None and check.omen not in {o.id for o in omens}:
                    raise ValueError("omen 必须是本次选择的预兆 ID")
            for omen in omens:
                if sum(c.omen == omen.id for c in plan.checks) < 2:
                    raise ValueError(f"{omen.name} 需要至少2项标记 omen={omen.id} 的专属检查")
            return plan

        cache = DerivedCache(self.tools.store.root / "method-plans", "plan")
        key = stable_key(
            {
                "references": [(r["reference"], r["sha256"]) for r in references],
                "omens": [self.omen_brief(o) for o in omens],
                "task": self.method_task(),
                "system": METHOD_SYSTEM,
                "model": self.settings.model,
                "availableTools": body["availableTools"],
            }
        )
        plan, origin = cache.load(key, parse)
        status, diagnostics = "planned", []
        if plan is None:
            repair = lambda error: (
                "请修正为指定JSON结构：checks有3至16项，methodReference须是实际提供的文件路径；"
                "每个所选预兆至少2项带 omen 字段的专属检查。问题：" + "；".join(validation_problems(error))
            )
            def invalid(message, error, attempt):
                problems = validation_problems(error)
                diagnostics.append({"attempt": attempt + 1, "problems": problems})
                self.job.emit(
                    "methods_plan_invalid", "方法计划需修正：" + "；".join(problems), attempt=attempt + 1, problems=problems,
                )

            try:
                plan, _ = await ask_json(self.model, messages, parse, repair, on_invalid=invalid)
                cache.save(key, plan.model_dump(by_alias=True), runId=self.job.task_id)
            except ValueError:
                plan, status = None, "plan_failed"
            except ModelServiceError as error:
                if error.code not in {"MODEL_INVALID_RESPONSE", "MODEL_TIMEOUT", "MODEL_UPSTREAM_ERROR", "MODEL_UNAVAILABLE"}:
                    raise
                diagnostics.append({"errorCode": error.code, "finishReason": getattr(error, "finish_reason", None)})
                plan, status = None, "plan_failed"
        meta = [{k: v for k, v in r.items() if k != "content"} for r in references]
        self.method_usage = {
            "status": status,
            "references": meta,
            "plan": plan.model_dump(by_alias=True) if plan else None,
            "reviewed": False,
            "planCacheReused": origin is not None,
            "originRunId": origin or self.job.task_id,
            "onDemandReads": [],
            "diagnostics": diagnostics,
        }
        if plan is None:
            self.job.emit("methods_plan_failed", "方法计划未通过格式校验；继续用已加载的基础研究方法，报告中会注明。")
            self.messages.append(
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "type": "research_method_plan",
                            "status": "plan_failed",
                            "references": [m["reference"] for m in meta],
                            "instruction": "方法计划未形成；仍按研究问题、所选预兆与已加载方法自主取证分析。",
                        },
                        ensure_ascii=False,
                    ),
                }
            )
            return
        self.messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "type": "research_method_plan",
                        "status": status,
                        "references": [m["reference"] for m in meta],
                        "plan": self.method_usage["plan"],
                        "instruction": "围绕计划主动取证、分析和选图，可依据新证据调整；缺数据明确说明，不机械执行固定配额。",
                    },
                    ensure_ascii=False,
                ),
            }
        )
        reused = "（复用已缓存计划）" if origin else ""
        self.job.emit(
            "methods_planned",
            f"已完整读取{len(references)}份相关原版方法并形成研究计划{reused}",
            references=[r["reference"] for r in references],
            focus=plan.focus,
            checks=[{"question": c.question, "topic": c.topic, "omen": c.omen} for c in plan.checks],
        )
