"""AgentRun 的核心编排器。

运行时采用“理解与规划 -> 调用受控工具 -> 校验证据 -> 生成结构化回答 -> 原子保存”
的两阶段 LLM 流程。数据库检查点负责取消与恢复，Redis 事件负责向前端实时展示进度。
"""

import asyncio
import json
import time
import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from common.databases.PostgresManager import db_manager
from agent.errors import (
    AgentCancelledError,
    AgentDeadlineExceededError,
    AgentEvidenceUnavailableError,
    AgentLimitExceededError,
    LLMTimeoutError,
)
from agent.event_store import AgentEventPublisher, agent_event_publisher
from agent.events import AgentEventType
from agent.graph import AgentNode
from agent.markdown_stream import chunk_markdown
from agent.policies import AgentPolicies
from agent.prompts import ANSWER_SYSTEM_PROMPT, PLANNER_SYSTEM_PROMPT
from agent.state import (
    APPROVED_TOOL_NAMES,
    AgentAnswer,
    AgentPlan,
    PlannedToolCall,
    RuntimeState,
)
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
from core.logger import sys_logger as logger
from services.llm_client import LLMClient, llm_client
from services.ai_access_service import ai_access_service


class AgentRuntime:
    """执行一条 AgentRun，并协调模型、工具、数据库、计费和实时事件。

    该对象应按一次任务创建，不应在多个并发运行之间共享，因为 ``deadline`` 和
    ``execution_token`` 都是本次运行的可变状态。
    """

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
        """注入运行依赖；默认值用于生产，注入参数便于隔离测试。"""

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
        """执行完整的 Agent 状态机并返回最终状态和消息 id。

        ``claim_run`` 通过执行 token 和租约抢占任务；抢占失败表示其他 worker 已处理，
        此时返回 ``ignored``。成功后依次读取上下文、生成计划、执行去重后的工具调用、
        检查真实证据并生成答案。澄清分支会保存问题后返回 ``waiting_user``。

        异常由 Celery 任务层统一转换为 failed/cancelled 状态；本方法不会吞掉核心错误。
        """

        # deadline 使用单调时钟，避免系统时间调整影响超时判断。
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
        # 先提交任务租约，再执行耗时操作；后续检查点会验证租约仍属于本 worker。
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
        orm_messages = await self.repository.list_messages(
            self.db,
            conversation_id=run.conversation_id,
            user_id=user_id,
            limit=self.policies.max_context_messages,
        )
        # 工具查询可能提交事务并使 ORM 对象过期，因此先复制成普通内存对象。
        messages = self._snapshot_messages(orm_messages)
        # 首页行业问数只应使用用户本次明确给出的过滤条件，不能暗中套用个人资料条件。
        market_question = next(
            (
                message
                for message in reversed(messages)
                if message.role == "user"
                and getattr(message, "message_type", None) == "market_question"
            ),
            None,
        )
        profile_data = self._profile_data(
            await self.repository.get_profile(self.db, user_id=user_id)
        )

        # 重试时保留累计澄清次数，防止借助任务重试绕过交互上限。
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

        planner_input = self._build_planner_input(messages, profile_data)
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
        if market_question is not None:
            planned_calls = self._broaden_market_question_calls(
                planned_calls,
                market_question.content,
            )
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
            # 模型偶尔会生成完全相同的工具调用，只执行一次以节省时间和查询压力。
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
            # 状态快照只保存裁剪后的证据，既供回答阶段使用，也避免数据库字段无限增长。
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
        # 严格禁止在没有真实样本的情况下让模型“凭常识”生成市场结论。
        if successful_results == 0:
            raise AgentEvidenceUnavailableError("所有市场数据工具均不可用")

        await self._checkpoint(state, AgentNode.COMPOSE_ANSWER)
        answer = await self._call_structured(
            ANSWER_SYSTEM_PROMPT,
            self._build_answer_input(messages, profile_data, state),
            AgentAnswer,
        )
        await self._ensure_current_execution_owner(run, user_id, state)
        # The model result is validated as AgentAnswer before anything is shown.
        # Convert it to final Markdown exactly once, then stream deterministic
        # chunks. This is intentionally not raw model-token streaming.
        final_markdown = answer.to_markdown()
        chunks = chunk_markdown(final_markdown)
        stream_available = await self._publish_stream_event(
            run,
            state,
            AgentEventType.MESSAGE_STARTED,
            {
                "streamId": self.execution_token,
                "streamMode": "validated_markdown_chunks",
                "contentType": "text/markdown",
                "deltaCount": len(chunks),
            },
        )
        published_delta_count = 0
        if stream_available:
            for index, delta in enumerate(chunks):
                stream_available = await self._publish_stream_event(
                    run,
                    state,
                    AgentEventType.MESSAGE_DELTA,
                    {
                        "streamId": self.execution_token,
                        "index": index,
                        "delta": delta,
                    },
                )
                if not stream_available:
                    break
                published_delta_count += 1

        self._check_budget(state)

        result = await self._save_answer(
            run,
            user_id,
            answer,
            final_markdown,
            state,
        )
        await self._publish_post_commit(
            run,
            AgentEventType.MESSAGE_COMPLETED,
            {
                "message_id": result["message_id"],
                "streamId": self.execution_token,
                "content": final_markdown,
                "result": answer.model_dump(mode="json"),
                "deltaCount": published_delta_count,
            },
        )
        await self._publish_post_commit(
            run,
            AgentEventType.RUN_COMPLETED,
            {"status": "completed", "message_id": result["message_id"]},
            allow_expired_attempt=True,
        )
        agent_runs_completed.inc()
        agent_run_duration.observe(time.monotonic() - run_started_monotonic)
        return result

    def _validate_tool_plan(self, plan: AgentPlan):
        """校验模型计划的数量和工具白名单，并返回允许执行的调用。"""

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
        """推进节点并把运行快照持久化。

        状态更新带有 ``from_statuses`` 和 ``execution_token`` 条件，可检测用户取消、
        worker 租约丢失或重复执行；条件更新失败时回滚并抛出取消异常。
        """

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
        """在同一事务中保存澄清消息，并把运行切换到 waiting_user。"""

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
        final_markdown: str,
        state: RuntimeState,
    ) -> Dict[str, Any]:
        """原子完成扣费、回答入库和运行终态更新。

        只有生成有效答案后才进入此方法。扣费使用稳定的 ``agent_run:{id}`` 订单号保证
        幂等，并与回答、completed 状态在同一数据库事务中提交；任何后续条件更新失败
        都会整体回滚，因此失败或取消的运行不会扣余额。
        """

        self._check_budget(state)
        owned_run = await self.repository.lock_owned_running_run(
            self.db,
            run_id=run.id,
            user_id=user_id,
            execution_token=self.execution_token,
        )
        if owned_run is None:
            await self.db.rollback()
            raise AgentCancelledError("保存结果时运行已取消或执行租约已转移")
        self._check_budget(state)

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
            content=final_markdown,
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
        # 指标不参与事务，只在数据库提交成功后记录，避免把回滚扣款计入使用量。
        if charged_now:
            record_metrics = getattr(self.billing_service, "record_charge_metrics", None)
            if record_metrics is not None:
                record_metrics(
                    getattr(run, "billing_feature_key", None) or "career_advice",
                    charge_amount,
                )
        return {"run_id": str(run.id), "status": "completed", "message_id": str(message.id)}

    def _check_budget(self, state: RuntimeState) -> None:
        """检查整次运行的时间、步骤数和工具次数预算。"""

        if time.monotonic() >= self.deadline:
            raise AgentDeadlineExceededError("AgentRun 超过最大执行时间")
        if state.step_count >= self.policies.max_steps:
            raise AgentLimitExceededError("AgentRun 超过最大步骤数")
        if state.tool_call_count > self.policies.max_tool_calls:
            raise AgentLimitExceededError("AgentRun 超过最大工具调用数")

    def _remaining_seconds(self) -> float:
        """返回总运行预算中的剩余秒数，耗尽时直接抛出超时异常。"""

        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise AgentDeadlineExceededError("AgentRun 超过最大执行时间")
        return remaining

    async def _call_structured(self, system_prompt: str, user_prompt: str, schema):
        """在总预算内调用结构化 LLM，并对瞬时超时最多重试一次。"""

        for attempt in range(2):
            try:
                return await asyncio.wait_for(
                    self.client.complete_structured(system_prompt, user_prompt, schema),
                    timeout=min(self.policies.llm_timeout_seconds, self._remaining_seconds()),
                )
            except (asyncio.TimeoutError, LLMTimeoutError) as exc:
                remaining = self._remaining_seconds()
                # 只有剩余预算还装得下一次完整 LLM 调用时才重试，否则这次重试注定失败，
                # 只会白白烧掉剩余预算。
                if attempt == 0 and remaining >= max(2, self.policies.llm_timeout_seconds // 2):
                    logger.warning(
                        "Agent LLM timed out; retrying once within run budget: "
                        f"schema={schema.__name__}, remaining={remaining:.1f}s"
                    )
                    continue
                raise AgentDeadlineExceededError("AgentRun 模型调用超过时限") from exc

    async def _publish(self, run, event: AgentEventType, data: Dict[str, Any]) -> None:
        """发布前端进度事件；发布器自身会隔离 Redis 故障。"""

        await self.publisher.publish(
            run_id=run.id,
            conversation_id=run.conversation_id,
            event=event,
            data=data,
        )

    async def _publish_stream_event(
        self,
        run,
        state: RuntimeState,
        event: AgentEventType,
        data: Dict[str, Any],
    ) -> bool:
        """Publish one answer frame without opening a database transaction.

        Ordering against cancellation and competing attempts is enforced by
        the EventStore's atomic Redis gate. A timeout or rejected event opens a
        run-local stream circuit breaker in ``execute``; other publisher errors
        remain visible as programming/integration failures.
        """

        self._check_budget(state)
        published = await self._publish_bounded(run, event, data)
        self._check_budget(state)
        return published

    async def _ensure_current_execution_owner(
        self,
        run,
        user_id: int,
        state: RuntimeState,
    ) -> None:
        """Freshly verify ownership before allowing this attempt to open a stream.

        Production uses a separate short-lived read-only session, so ORM identity
        caching in the runtime session cannot hide a newer lease owner. Test
        repositories use their injected in-memory session without adding commits.
        Delta ordering after this check remains entirely Redis-gated.
        """

        self._check_budget(state)
        if self.repository is crud_agent:
            async with await db_manager.get_session() as ownership_db:
                is_owner = await self.repository.is_run_owned_and_running(
                    ownership_db,
                    run_id=run.id,
                    user_id=user_id,
                    execution_token=self.execution_token,
                )
        else:
            is_owner = await self.repository.is_run_owned_and_running(
                self.db,
                run_id=run.id,
                user_id=user_id,
                execution_token=self.execution_token,
            )
        self._check_budget(state)
        if not is_owner:
            raise AgentCancelledError(
                "开始流式输出前运行已取消或执行租约已转移"
            )

    async def _publish_bounded(
        self,
        run,
        event: AgentEventType,
        data: Dict[str, Any],
    ) -> bool:
        """Bound pre-commit stream latency by both policy and run budget."""

        try:
            published = await asyncio.wait_for(
                self.publisher.publish(
                    run_id=run.id,
                    conversation_id=run.conversation_id,
                    event=event,
                    data=data,
                ),
                timeout=min(
                    self.policies.stream_publish_timeout_seconds,
                    self._remaining_seconds(),
                ),
            )
            return published is not None
        except asyncio.TimeoutError:
            logger.warning(
                "Agent event publish timed out; continuing with database snapshot: "
                f"run_id={run.id}, event={event.value}"
            )
            return False

    async def _publish_post_commit(
        self,
        run,
        event: AgentEventType,
        data: Dict[str, Any],
        *,
        allow_expired_attempt: bool = False,
    ) -> bool:
        """Best-effort terminal publishing that cannot undo committed business state."""

        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            if not allow_expired_attempt:
                return False
            # ``run_completed`` owns the Redis terminal gate, so make one very
            # short attempt even after the business deadline has elapsed.
            timeout = min(self.policies.stream_publish_timeout_seconds, 0.01)
        else:
            timeout = min(self.policies.stream_publish_timeout_seconds, remaining)
        try:
            published = await asyncio.wait_for(
                self.publisher.publish(
                    run_id=run.id,
                    conversation_id=run.conversation_id,
                    event=event,
                    data=data,
                ),
                timeout=timeout,
            )
            return published is not None
        except asyncio.TimeoutError:
            logger.warning(
                "Post-commit Agent event publish timed out: "
                f"run_id={run.id}, event={event.value}"
            )
            return False
        except Exception as exc:
            # The answer, completed status and charge are already committed.
            # Event infrastructure must not turn that success into task failure.
            logger.warning(
                "Post-commit Agent event publish failed: "
                f"run_id={run.id}, event={event.value}, error={exc}"
            )
            return False

    @staticmethod
    def _has_usable_evidence(result) -> bool:
        """判断工具结果是否包含可支撑回答的非空真实样本。"""

        if not result.ok or result.sample_size <= 0:
            return False
        data = result.data
        if data is None:
            return False
        if isinstance(data, (list, dict)) and not data:
            return False
        return True

    @staticmethod
    def _snapshot_messages(messages):
        """把 ORM 消息复制为轻量对象，避免事务提交后的属性过期问题。"""

        return [
            SimpleNamespace(
                role=str(message.role),
                content=str(message.content),
                message_type=getattr(message, "message_type", None),
            )
            for message in messages
        ]

    @staticmethod
    def _broaden_market_question_calls(
        calls: List[PlannedToolCall],
        user_content: str,
    ) -> List[PlannedToolCall]:
        """移除首页行业问数中并未由用户明确提及的个人资料过滤条件。

        规划器可以看到已确认个人资料，可能自动加入学历、经验或技能；这对职业规划有用，
        但会把“上海 Python 岗位行情”错误缩窄成个人匹配查询，因此首页问数需要放宽。
        """

        normalized_content = str(user_content or "").lower()
        normalized_calls = []
        for call in calls:
            arguments = dict(call.arguments)
            for field in ("education", "experience"):
                value = str(arguments.get(field) or "").strip()
                if value and value.lower() not in normalized_content:
                    arguments.pop(field, None)

            skills = arguments.get("skills")
            if isinstance(skills, list):
                arguments["skills"] = [
                    skill
                    for skill in skills
                    if str(skill).strip().lower() in normalized_content
                ]
            normalized_calls.append(call.model_copy(update={"arguments": arguments}))
        return normalized_calls

    def _build_planner_input(self, messages, profile_data) -> str:
        """构造规划器输入：有限对话上下文、已确认资料和工具 JSON Schema。"""

        payload = {
            "messages": [
                {"role": message.role, "content": str(message.content)[:1500]}
                for message in messages[-self.policies.max_context_messages :]
            ],
            "confirmed_profile": profile_data,
            "available_tools": self.registry.definitions(),
        }
        return json.dumps(payload, ensure_ascii=False, default=str)

    def _build_answer_input(self, messages, profile_data, state: RuntimeState) -> str:
        """构造回答器输入，只提供最新问题、确认资料和已裁剪工具证据。"""

        payload = {
            "latest_user_message": next(
                (str(message.content)[:2000] for message in reversed(messages) if message.role == "user"),
                "",
            ),
            "confirmed_profile": profile_data,
            "intent": state.intent,
            "tool_evidence": state.tool_summaries,
        }
        return json.dumps(payload, ensure_ascii=False, default=str)

    @staticmethod
    def _profile_data(profile) -> Dict[str, Any]:
        """提取可交给模型的已确认用户资料。

        课程和标准化技能只有 ``confirmation_status=confirmed`` 时才会使用；若没有
        标准化技能，则兼容旧版 ``profile.skills`` 快照。
        """

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
        """递归裁剪工具参数和结果，限制状态快照及实时事件的体积。

        岗位 description/requirements 文本体积大且不适合进入模型证据摘要，因此从字典
        中删除；字符串、列表、字典数量和嵌套深度也都有上限。
        """

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
