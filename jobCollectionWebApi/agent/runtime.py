import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from agent.errors import (
    AgentCancelledError,
    AgentDeadlineExceededError,
    AgentEvidenceUnavailableError,
    AgentLimitExceededError,
)
from agent.event_store import AgentEventPublisher, agent_event_publisher
from agent.events import AgentEventType
from agent.graph import AgentNode
from agent.policies import AgentPolicies
from agent.prompts import ANSWER_SYSTEM_PROMPT, PLANNER_SYSTEM_PROMPT
from agent.state import APPROVED_TOOL_NAMES, AgentAnswer, AgentPlan, RuntimeState
from agent.tools.base import ToolContext
from agent.tools.registry import AgentToolRegistry, agent_tool_registry
from crud import agent as crud_agent
from core.metrics import (
    agent_first_event_latency,
    agent_run_duration,
    agent_runs_completed,
    agent_tool_calls,
    agent_tool_failures,
)
from services.llm_client import LLMClient, llm_client
from services.ai_access_service import ai_access_service


class AgentRuntime:
    def __init__(
        self,
        db: AsyncSession,
        *,
        client: Optional[LLMClient] = None,
        registry: Optional[AgentToolRegistry] = None,
        policies: Optional[AgentPolicies] = None,
        publisher: Optional[AgentEventPublisher] = None,
        repository=crud_agent,
        billing_service=ai_access_service,
    ):
        self.db = db
        self.client = client or llm_client
        self.registry = registry or agent_tool_registry
        self.policies = policies or AgentPolicies.from_settings()
        self.publisher = publisher or agent_event_publisher
        self.repository = repository
        self.billing_service = billing_service
        self.deadline = 0.0
        self.execution_token = None

    async def execute(
        self,
        run_id: int,
        user_id: int,
        execution_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.deadline = time.monotonic() + self.policies.run_timeout_seconds
        run_started_monotonic = time.monotonic()
        self.execution_token = execution_token or uuid.uuid4().hex
        run = await self.repository.claim_run(
            self.db,
            run_id=run_id,
            user_id=user_id,
            execution_token=self.execution_token,
            lease_seconds=max(self.policies.run_timeout_seconds + 30, 90),
        )
        if run is None:
            return {"run_id": str(run_id), "status": "ignored"}
        await self.db.commit()
        if run.created_at:
            latency = max(0.0, (datetime.utcnow() - run.created_at).total_seconds())
            agent_first_event_latency.observe(latency)
        await self._publish(
            run,
            AgentEventType.RUN_STARTED,
            {"status": "running", "resumed": bool(run.state_snapshot)},
        )

        conversation = await self.repository.get_conversation(
            self.db,
            conversation_id=run.conversation_id,
            user_id=user_id,
        )
        if conversation is None:
            raise AgentEvidenceUnavailableError("Agent 会话不存在")
        messages = await self.repository.list_messages(
            self.db,
            conversation_id=run.conversation_id,
            user_id=user_id,
            limit=self.policies.max_context_messages,
        )
        profile = await self.repository.get_profile(self.db, user_id=user_id)

        previous_snapshot = run.state_snapshot or {}
        state = RuntimeState(
            run_id=str(run.id),
            conversation_id=str(run.conversation_id),
            user_id=str(user_id),
            current_node=AgentNode.LOAD_CONTEXT.value,
            step_count=int(run.step_count or 0),
            tool_call_count=int(run.tool_call_count or 0),
            clarification_count=int(previous_snapshot.get("clarification_count", 0) or 0),
        )
        await self._checkpoint(state, AgentNode.UNDERSTAND_AND_PLAN)

        planner_input = self._build_planner_input(messages, profile)
        plan = await self._call_structured(
            PLANNER_SYSTEM_PROMPT,
            planner_input,
            AgentPlan,
        )
        state.intent = plan.intent
        state.profile_candidates = self._sanitize(plan.profile_candidates)
        state.plan = self._sanitize(plan.model_dump(mode="json"))

        if plan.action == "clarify":
            if state.clarification_count >= self.policies.max_clarifications:
                raise AgentLimitExceededError("Agent 澄清轮数已达到上限")
            state.clarification_count += 1
            result = await self._save_clarification(
                run,
                user_id,
                plan.clarification_question,
                state,
            )
            await self._publish(
                run,
                AgentEventType.PLAN_CREATED,
                {"intent": plan.intent, "action": plan.action, "missing_information": plan.missing_information},
            )
            await self._publish(
                run,
                AgentEventType.CLARIFICATION_REQUIRED,
                {"message_id": result["message_id"], "question": plan.clarification_question},
            )
            return result

        planned_calls = self._validate_tool_plan(plan)
        await self._checkpoint(state, AgentNode.EXECUTE_TOOLS)
        await self._publish(
            run,
            AgentEventType.PLAN_CREATED,
            {
                "intent": plan.intent,
                "action": plan.action,
                "tools": [{"name": call.name} for call in planned_calls],
            },
        )
        successful_results = 0
        seen_calls = set()
        for call in planned_calls:
            self._check_budget(state)
            signature = json.dumps(
                {"name": call.name, "arguments": call.arguments},
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            )
            if signature in seen_calls:
                continue
            seen_calls.add(signature)
            await self._publish(
                run,
                AgentEventType.TOOL_STARTED,
                {"tool": call.name, "arguments": self._sanitize(call.arguments)},
            )
            try:
                result = await asyncio.wait_for(
                    self.registry.invoke(
                        call.name,
                        call.arguments,
                        ToolContext(db=self.db, user_id=user_id),
                    ),
                    timeout=self._remaining_seconds(),
                )
            except asyncio.TimeoutError as exc:
                raise AgentDeadlineExceededError("AgentRun 工具执行超过总时限") from exc
            state.tool_call_count += 1
            agent_tool_calls.labels(tool_name=call.name, source=result.source).inc()
            if not result.ok:
                agent_tool_failures.labels(
                    tool_name=call.name,
                    failure_kind=result.error_code or "unknown",
                ).inc()
            summary = {
                "tool": call.name,
                "ok": result.ok,
                "sample_size": result.sample_size,
                "source": result.source,
                "filters": self._sanitize(result.filters),
                "data_as_of": result.data_as_of.isoformat() if result.data_as_of else None,
                "warnings": result.warnings[:5],
                "data": self._sanitize(result.data),
            }
            state.tool_summaries.append(summary)
            if self._has_usable_evidence(result):
                successful_results += 1
            await self._checkpoint(state, AgentNode.EXECUTE_TOOLS)
            await self._publish(
                run,
                AgentEventType.TOOL_COMPLETED,
                {
                    "tool": call.name,
                    "ok": result.ok,
                    "sample_size": result.sample_size,
                    "source": result.source,
                    "warnings": result.warnings[:5],
                },
            )

        await self._checkpoint(state, AgentNode.EVALUATE_EVIDENCE)
        if successful_results == 0:
            raise AgentEvidenceUnavailableError("所有市场数据工具均不可用")

        await self._checkpoint(state, AgentNode.COMPOSE_ANSWER)
        answer = await self._call_structured(
            ANSWER_SYSTEM_PROMPT,
            self._build_answer_input(messages, profile, state),
            AgentAnswer,
        )
        result = await self._save_answer(run, user_id, answer, state)
        await self._publish(
            run,
            AgentEventType.MESSAGE_COMPLETED,
            {"message_id": result["message_id"], "result": answer.model_dump(mode="json")},
        )
        await self._publish(
            run,
            AgentEventType.RUN_COMPLETED,
            {"status": "completed", "message_id": result["message_id"]},
        )
        agent_runs_completed.inc()
        agent_run_duration.observe(time.monotonic() - run_started_monotonic)
        return result

    def _validate_tool_plan(self, plan: AgentPlan):
        calls = plan.tools[: self.policies.max_tool_calls]
        if len(plan.tools) > self.policies.max_tool_calls:
            raise AgentLimitExceededError("Agent 工具调用数量超过限制")
        for call in calls:
            if call.name not in APPROVED_TOOL_NAMES or call.name not in self.registry.names():
                raise AgentLimitExceededError("Agent 请求了未授权工具")
        if not calls:
            raise AgentEvidenceUnavailableError("Agent 未选择市场数据工具")
        return calls

    async def _checkpoint(self, state: RuntimeState, node: AgentNode) -> None:
        self._check_budget(state)
        state.current_node = node.value
        state.step_count += 1
        updated = await self.repository.transition_run(
            self.db,
            run_id=int(state.run_id),
            user_id=int(state.user_id),
            from_statuses=("running",),
            to_status="running",
            values={
                "current_node": node.value,
                "step_count": state.step_count,
                "tool_call_count": state.tool_call_count,
                "state_snapshot": state.model_dump(mode="json"),
            },
            execution_token=self.execution_token,
        )
        if updated is None:
            await self.db.rollback()
            raise AgentCancelledError("AgentRun 已取消或不再处于运行状态")
        await self.db.commit()

    async def _save_clarification(
        self,
        run,
        user_id: int,
        question: str,
        state: RuntimeState,
    ) -> Dict[str, Any]:
        message = await self.repository.create_runtime_message(
            self.db,
            conversation_id=run.conversation_id,
            user_id=user_id,
            role="assistant",
            message_type="clarification_required",
            content=question,
            metadata={"run_id": str(run.id), "missing_information": state.plan.get("missing_information", [])},
        )
        state.current_node = AgentNode.CLARIFICATION.value
        state.step_count += 1
        updated = await self.repository.transition_run(
            self.db,
            run_id=run.id,
            user_id=user_id,
            from_statuses=("running",),
            to_status="waiting_user",
            values={
                "current_node": AgentNode.CLARIFICATION.value,
                "step_count": state.step_count,
                "state_snapshot": state.model_dump(mode="json"),
            },
            execution_token=self.execution_token,
        )
        if updated is None:
            await self.db.rollback()
            raise AgentCancelledError("保存澄清问题时运行已取消")
        await self.db.commit()
        return {"run_id": str(run.id), "status": "waiting_user", "message_id": str(message.id)}

    async def _save_answer(
        self,
        run,
        user_id: int,
        answer: AgentAnswer,
        state: RuntimeState,
    ) -> Dict[str, Any]:
        result_data = answer.model_dump(mode="json")
        charge_amount = float(getattr(run, "charge_amount", 0) or 0)
        charged_at = getattr(run, "charged_at", None)
        charged_now = charge_amount > 0 and charged_at is None
        if charged_now:
            order_no = f"agent_run:{run.id}"
            await self.billing_service.charge_usage(
                self.db,
                user_id=user_id,
                feature_key=getattr(run, "billing_feature_key", None) or "career_advice",
                amount=charge_amount,
                detail_suffix=order_no,
                order_no=order_no,
                commit=False,
            )
            charged_at = datetime.utcnow()
        message = await self.repository.create_runtime_message(
            self.db,
            conversation_id=run.conversation_id,
            user_id=user_id,
            role="assistant",
            message_type="analysis_result",
            content=answer.to_markdown(),
            metadata={
                "run_id": str(run.id),
                "schema_version": "1.0",
                "result": result_data,
                "evidence": state.tool_summaries,
            },
        )
        state.current_node = AgentNode.COMPLETED.value
        state.step_count += 1
        updated = await self.repository.transition_run(
            self.db,
            run_id=run.id,
            user_id=user_id,
            from_statuses=("running",),
            to_status="completed",
            values={
                "current_node": AgentNode.COMPLETED.value,
                "step_count": state.step_count,
                "tool_call_count": state.tool_call_count,
                "state_snapshot": state.model_dump(mode="json"),
                "charged_at": charged_at,
            },
            execution_token=self.execution_token,
        )
        if updated is None:
            await self.db.rollback()
            raise AgentCancelledError("保存结果时运行已取消")
        await self.db.commit()
        if charged_now:
            record_metrics = getattr(self.billing_service, "record_charge_metrics", None)
            if record_metrics is not None:
                record_metrics(
                    getattr(run, "billing_feature_key", None) or "career_advice",
                    charge_amount,
                )
        return {"run_id": str(run.id), "status": "completed", "message_id": str(message.id)}

    def _check_budget(self, state: RuntimeState) -> None:
        if time.monotonic() >= self.deadline:
            raise AgentDeadlineExceededError("AgentRun 超过最大执行时间")
        if state.step_count >= self.policies.max_steps:
            raise AgentLimitExceededError("AgentRun 超过最大步骤数")
        if state.tool_call_count > self.policies.max_tool_calls:
            raise AgentLimitExceededError("AgentRun 超过最大工具调用数")

    def _remaining_seconds(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise AgentDeadlineExceededError("AgentRun 超过最大执行时间")
        return remaining

    async def _call_structured(self, system_prompt: str, user_prompt: str, schema):
        try:
            return await asyncio.wait_for(
                self.client.complete_structured(system_prompt, user_prompt, schema),
                timeout=min(self.policies.llm_timeout_seconds, self._remaining_seconds()),
            )
        except asyncio.TimeoutError as exc:
            raise AgentDeadlineExceededError("AgentRun 模型调用超过时限") from exc

    async def _publish(self, run, event: AgentEventType, data: Dict[str, Any]) -> None:
        await self.publisher.publish(
            run_id=run.id,
            conversation_id=run.conversation_id,
            event=event,
            data=data,
        )

    @staticmethod
    def _has_usable_evidence(result) -> bool:
        if not result.ok or result.sample_size <= 0:
            return False
        data = result.data
        if data is None:
            return False
        if isinstance(data, (list, dict)) and not data:
            return False
        return True

    def _build_planner_input(self, messages, profile) -> str:
        payload = {
            "messages": [
                {"role": message.role, "content": str(message.content)[:1500]}
                for message in messages[-self.policies.max_context_messages :]
            ],
            "confirmed_profile": self._profile_data(profile),
            "available_tools": self.registry.definitions(),
        }
        return json.dumps(payload, ensure_ascii=False, default=str)

    def _build_answer_input(self, messages, profile, state: RuntimeState) -> str:
        payload = {
            "latest_user_message": next(
                (str(message.content)[:2000] for message in reversed(messages) if message.role == "user"),
                "",
            ),
            "confirmed_profile": self._profile_data(profile),
            "intent": state.intent,
            "tool_evidence": state.tool_summaries,
        }
        return json.dumps(payload, ensure_ascii=False, default=str)

    @staticmethod
    def _profile_data(profile) -> Dict[str, Any]:
        if profile is None:
            return {}
        profile_data = {
            key: getattr(profile, key, None)
            for key in (
                "education",
                "experience",
                "preferences",
                "constraints",
                "goals",
            )
            if getattr(profile, key, None) is not None
        }
        courses = [
            {
                "name": item.name,
                "category": item.category,
                "level": item.level,
                "evidence": item.evidence,
            }
            for item in (getattr(profile, "courses", None) or [])
            if getattr(item, "confirmation_status", None) == "confirmed"
        ]
        normalized_skills = [
            {
                "name": item.name,
                "category": item.category,
                "proficiency_level": item.proficiency_level,
                "years_experience": (
                    float(item.years_experience)
                    if item.years_experience is not None
                    else None
                ),
                "evidence": item.evidence,
            }
            for item in (getattr(profile, "normalized_skills", None) or [])
            if getattr(item, "confirmation_status", None) == "confirmed"
        ]
        if courses:
            profile_data["courses"] = courses
        if normalized_skills:
            profile_data["skills"] = normalized_skills
        elif getattr(profile, "skills", None) is not None:
            profile_data["skills"] = profile.skills
        return profile_data

    @classmethod
    def _sanitize(cls, value: Any, depth: int = 0) -> Any:
        if depth >= 4:
            return "[truncated]"
        if isinstance(value, str):
            return value[:500]
        if isinstance(value, dict):
            result = {}
            for key, item in list(value.items())[:30]:
                if key in {"description", "requirements"}:
                    continue
                result[str(key)] = cls._sanitize(item, depth + 1)
            return result
        if isinstance(value, list):
            return [cls._sanitize(item, depth + 1) for item in value[:10]]
        return value
