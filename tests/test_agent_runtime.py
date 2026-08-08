import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from agent.errors import (
    AgentCancelledError,
    AgentDeadlineExceededError,
    AgentEvidenceUnavailableError,
    AgentLimitExceededError,
    LLMConfigurationError,
    LLMTimeoutError,
)
from agent.policies import AgentPolicies
from agent.runtime import AgentRuntime
from agent.event_store import AgentEventPublisher
from agent.events import AgentEventType
from agent.state import AgentAnswer, AgentPlan
from agent.tools.base import AgentTool
from agent.tools.registry import AgentToolRegistry
from agent.tools.schemas import SearchJobsInput, ToolResult
from services.llm_client import LLMClient


class FakeDB:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class DeadlineExpiringDB(FakeDB):
    def __init__(self):
        super().__init__()
        self.on_final_commit = None

    async def commit(self):
        await super().commit()
        if self.commits == 7 and self.on_final_commit is not None:
            self.on_final_commit()


class FakePublisher:
    def __init__(self):
        self.events = []

    async def publish(self, **kwargs):
        self.events.append(kwargs)
        return SimpleNamespace(**kwargs)


class ExplodingEventStore:
    async def append(self, **kwargs):
        raise ConnectionError("redis unavailable")


class ExplodingPublisher:
    async def publish(self, **kwargs):
        raise RuntimeError("invalid test publisher")


class SlowStreamingPublisher(FakePublisher):
    def __init__(self, delay_seconds=0.1):
        super().__init__()
        self.delay_seconds = delay_seconds
        self.slow_waits = 0

    async def publish(self, **kwargs):
        if kwargs["event"].value in {"message_started", "message_delta"}:
            self.slow_waits += 1
            await asyncio.sleep(self.delay_seconds)
        return await super().publish(**kwargs)


class SlowRunCompletedPublisher(FakePublisher):
    def __init__(self, delay_seconds=0.2):
        super().__init__()
        self.delay_seconds = delay_seconds
        self.slow_waits = 0

    async def publish(self, **kwargs):
        if kwargs["event"].value == "run_completed":
            self.slow_waits += 1
            await asyncio.sleep(self.delay_seconds)
        return await super().publish(**kwargs)


class OwnershipLosingPublisher(FakePublisher):
    def __init__(self, repository, *, emit_cancelled=False):
        super().__init__()
        self.repository = repository
        self.emit_cancelled = emit_cancelled
        self.triggered = False
        self.active_stream_id = None
        self.terminal = False

    async def publish(self, **kwargs):
        event_name = kwargs["event"].value
        stream_id = kwargs["data"].get("streamId")
        if self.terminal and event_name in {
            "message_started",
            "message_delta",
            "message_completed",
        }:
            return None
        if event_name == "message_started":
            self.active_stream_id = stream_id
        elif event_name in {"message_delta", "message_completed"}:
            if not stream_id or stream_id != self.active_stream_id:
                return None

        accepted = await super().publish(**kwargs)
        if event_name == "message_delta" and not self.triggered:
            self.triggered = True
            self.repository.run.status = "cancelled" if self.emit_cancelled else "running"
            self.repository.run.execution_token = None if self.emit_cancelled else "new-owner"
            if self.emit_cancelled:
                self.terminal = True
                self.events.append(
                    {
                        **kwargs,
                        "event": AgentEventType.RUN_CANCELLED,
                        "data": {"status": "cancelled"},
                    }
                )
            else:
                # Emulate a newer attempt winning the atomic active-stream gate
                # before the stale worker tries to publish its next delta.
                self.active_stream_id = "attempt-two"
        return accepted


class FakeBillingService:
    def __init__(self):
        self.charges = []
        self.committed_charges = 0

    async def charge_usage(self, db, **kwargs):
        self.charges.append(kwargs)
        if kwargs.get("commit", True):
            self.committed_charges += 1


class FakeRepository:
    def __init__(self, cancel_on_status=None):
        self.run = SimpleNamespace(
            id=100,
            conversation_id=200,
            user_id=300,
            status="queued",
            step_count=0,
            tool_call_count=0,
            state_snapshot=None,
            created_at=None,
        )
        self.messages = [SimpleNamespace(role="user", content="我想做数据分析，应该怎么准备？")]
        self.transitions = []
        self.created_messages = []
        self.cancel_on_status = cancel_on_status

    async def claim_run(self, db, **kwargs):
        self.run.status = "running"
        self.run.execution_token = kwargs["execution_token"]
        return self.run

    async def get_conversation(self, db, **kwargs):
        return SimpleNamespace(id=200, user_id=300)

    async def list_messages(self, db, **kwargs):
        return self.messages

    async def get_profile(self, db, **kwargs):
        return None

    async def lock_owned_running_run(self, db, **kwargs):
        if self.run.status != "running":
            return None
        if self.run.execution_token != kwargs["execution_token"]:
            return None
        return self.run

    async def is_run_owned_and_running(self, db, **kwargs):
        return (
            self.run.status == "running"
            and self.run.execution_token == kwargs["execution_token"]
        )

    async def transition_run(self, db, **kwargs):
        self.transitions.append(kwargs)
        if self.run.status not in kwargs["from_statuses"]:
            return None
        expected_token = kwargs.get("execution_token")
        if expected_token is not None and self.run.execution_token != expected_token:
            return None
        if kwargs["to_status"] == self.cancel_on_status:
            return None
        self.run.status = kwargs["to_status"]
        return self.run

    async def create_runtime_message(self, db, **kwargs):
        message = SimpleNamespace(id=900 + len(self.created_messages), **kwargs)
        self.created_messages.append(message)
        return message


class ScriptedClient:
    def __init__(self, plan, answer=None):
        self.plan = plan
        self.answer = answer
        self.calls = []

    async def complete_structured(self, system_prompt, user_prompt, schema):
        self.calls.append(schema)
        if schema is AgentPlan:
            return self.plan
        if schema is AgentAnswer:
            return self.answer
        raise AssertionError("unexpected schema")


class TimeoutOnceAnswerClient(ScriptedClient):
    def __init__(self, plan, answer):
        super().__init__(plan, answer)
        self.answer_attempts = 0

    async def complete_structured(self, system_prompt, user_prompt, schema):
        self.calls.append(schema)
        if schema is AgentPlan:
            return self.plan
        if schema is AgentAnswer:
            self.answer_attempts += 1
            if self.answer_attempts == 1:
                raise LLMTimeoutError("transient model timeout")
            return self.answer
        raise AssertionError("unexpected schema")


class OwnershipStealingAnswerClient(ScriptedClient):
    def __init__(self, plan, answer, repository):
        super().__init__(plan, answer)
        self.repository = repository

    async def complete_structured(self, system_prompt, user_prompt, schema):
        result = await super().complete_structured(system_prompt, user_prompt, schema)
        if schema is AgentAnswer:
            self.repository.run.execution_token = "new-owner"
        return result


class SuccessfulSearchTool(AgentTool[SearchJobsInput]):
    name = "search_jobs"
    description = "test search"
    input_model = SearchJobsInput

    async def execute(self, input_data, context):
        return ToolResult.success(
            data={"total": 20, "top_titles": [{"name": "数据分析师", "count": 12}]},
            sample_size=20,
            filters=input_data.model_dump(),
            source="mock",
        )


class CapturingSearchTool(SuccessfulSearchTool):
    def __init__(self):
        self.input_data = None

    async def execute(self, input_data, context):
        self.input_data = input_data
        return await super().execute(input_data, context)


class FailedSearchTool(SuccessfulSearchTool):
    async def execute(self, input_data, context):
        return ToolResult.failure(error_code="TEST_FAILURE", warning="测试数据不可用")


class EmptySearchTool(SuccessfulSearchTool):
    async def execute(self, input_data, context):
        return ToolResult.success(
            data={"total": 0, "jobs": []},
            sample_size=0,
            filters=input_data.model_dump(),
            source="mock",
        )


class ExpiringMessage:
    def __init__(self, role, content):
        self._role = role
        self._content = content
        self.expired = False

    @property
    def role(self):
        if self.expired:
            raise RuntimeError("message ORM state expired")
        return self._role

    @property
    def content(self):
        if self.expired:
            raise RuntimeError("message ORM state expired")
        return self._content


class ExpiringSearchTool(SuccessfulSearchTool):
    def __init__(self, message):
        self.message = message

    async def execute(self, input_data, context):
        self.message.expired = True
        return await super().execute(input_data, context)


def make_registry(tool):
    registry = AgentToolRegistry()
    registry.register(tool)
    return registry


def make_policies(**overrides):
    values = {
        "run_timeout_seconds": 10,
        "llm_timeout_seconds": 2,
        "max_tool_calls": 6,
        "max_steps": 12,
        "max_clarifications": 2,
        "max_output_tokens": 500,
        "max_context_messages": 10,
    }
    values.update(overrides)
    return AgentPolicies(**values)


def analyze_plan(tool_count=1):
    return AgentPlan.model_validate(
        {
            "intent": "数据分析职业规划",
            "action": "analyze",
            "tools": [
                {"name": "search_jobs", "arguments": {"keyword": "数据分析"}}
                for _ in range(tool_count)
            ],
        }
    )


def answer_result():
    return AgentAnswer(
        summary="数据分析方向有真实岗位需求，建议先补齐 SQL。",
        directions=[{"title": "数据分析师", "reason": "与当前目标一致"}],
        next_actions=[{"title": "完成 SQL 基础学习"}],
        evidence_summary=[{"source": "mock", "sample_size": 20}],
    )


def test_agent_answer_formats_alternate_skill_gap_fields_without_placeholder_repetition():
    answer = AgentAnswer(
        summary="当前市场更看重框架和部署经验。",
        skill_gaps=[
            {"skill": "Django", "reason": "高频岗位要求，但目前缺少项目经验"},
            {"title": "Redis", "description": "需要补充缓存与队列实战"},
            {"name": "Linux 部署", "gap": "尚未独立完成线上部署"},
            {},
        ],
    )

    markdown = answer.to_markdown()

    assert "**Django**：高频岗位要求，但目前缺少项目经验" in markdown
    assert "**Redis**：需要补充缓存与队列实战" in markdown
    assert "**Linux 部署**：尚未独立完成线上部署" in markdown
    assert "待提升能力" not in markdown


def test_runtime_completes_with_real_tool_evidence():
    db = FakeDB()
    repository = FakeRepository()
    client = ScriptedClient(analyze_plan(), answer_result())
    publisher = FakePublisher()
    runtime = AgentRuntime(
        db,
        client=client,
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(),
        publisher=publisher,
        repository=repository,
    )

    result = asyncio.run(runtime.execute(100, 300))

    assert result["status"] == "completed"
    assert repository.created_messages[-1].message_type == "analysis_result"
    assert repository.transitions[-1]["to_status"] == "completed"
    assert len(client.calls) == 2
    assert publisher.events[-1]["event"].value == "run_completed"


def test_runtime_streams_final_markdown_as_ordered_bounded_message_deltas():
    answer = answer_result()
    publisher = FakePublisher()
    runtime = AgentRuntime(
        FakeDB(),
        client=ScriptedClient(analyze_plan(), answer),
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(),
        publisher=publisher,
        repository=FakeRepository(),
    )

    result = asyncio.run(runtime.execute(100, 300))

    assert result["status"] == "completed"
    indexed_events = list(enumerate(publisher.events))
    started_indexes = [
        index
        for index, event in indexed_events
        if event["event"].value == "message_started"
    ]
    delta_events = [
        (index, event)
        for index, event in indexed_events
        if event["event"].value == "message_delta"
    ]
    completed_indexes = [
        index
        for index, event in indexed_events
        if event["event"].value == "message_completed"
    ]

    assert len(started_indexes) == 1
    assert len(delta_events) >= 2
    assert len(completed_indexes) == 1
    assert all(
        isinstance(event["data"].get("delta"), str)
        and 0 < len(event["data"]["delta"]) <= 256
        for _, event in delta_events
    )
    assert started_indexes[0] < min(index for index, _ in delta_events)
    assert max(index for index, _ in delta_events) < completed_indexes[0]
    assert "".join(event["data"]["delta"] for _, event in delta_events) == answer.to_markdown()
    assert [event["data"]["index"] for _, event in delta_events] == list(
        range(len(delta_events))
    )
    completed = publisher.events[completed_indexes[0]]["data"]
    assert completed["content"] == answer.to_markdown()
    assert completed["result"] == answer.model_dump(mode="json")
    assert completed["deltaCount"] == len(delta_events)
    run_completed_index = next(
        index
        for index, event in indexed_events
        if event["event"].value == "run_completed"
    )
    assert completed_indexes[0] < run_completed_index
    stream_events = [
        event
        for event in publisher.events
        if event["event"].value in {
            "message_started",
            "message_delta",
            "message_completed",
        }
    ]
    assert {event["data"]["streamId"] for event in stream_events} == {
        runtime.execution_token
    }


def test_new_attempt_restarts_delta_indexes_with_a_new_stream_id():
    repository = FakeRepository()
    publisher = OwnershipLosingPublisher(repository)
    first_runtime = AgentRuntime(
        FakeDB(),
        client=ScriptedClient(analyze_plan(), answer_result()),
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(),
        publisher=publisher,
        repository=repository,
    )

    with pytest.raises(AgentCancelledError):
        asyncio.run(first_runtime.execute(100, 300, execution_token="attempt-one"))

    repository.run.status = "queued"
    repository.run.execution_token = None
    second_runtime = AgentRuntime(
        FakeDB(),
        client=ScriptedClient(analyze_plan(), answer_result()),
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(),
        publisher=publisher,
        repository=repository,
    )
    result = asyncio.run(
        second_runtime.execute(100, 300, execution_token="attempt-two")
    )

    assert result["status"] == "completed"
    deltas_by_stream = {}
    for event in publisher.events:
        if event["event"].value != "message_delta":
            continue
        deltas_by_stream.setdefault(event["data"]["streamId"], []).append(
            event["data"]["index"]
        )
    assert deltas_by_stream["attempt-one"] == [0]
    assert deltas_by_stream["attempt-two"][0] == 0
    assert len(deltas_by_stream["attempt-two"]) >= 2


def test_stale_attempt_does_not_publish_started_after_answer_model_returns():
    repository = FakeRepository()
    publisher = FakePublisher()
    stale_runtime = AgentRuntime(
        FakeDB(),
        client=OwnershipStealingAnswerClient(
            analyze_plan(),
            answer_result(),
            repository,
        ),
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(),
        publisher=publisher,
        repository=repository,
    )

    with pytest.raises(AgentCancelledError):
        asyncio.run(
            stale_runtime.execute(100, 300, execution_token="old-owner")
        )

    assert not {
        "message_started",
        "message_delta",
        "message_completed",
    } & {event["event"].value for event in publisher.events}

    repository.run.status = "queued"
    repository.run.execution_token = None
    fresh_runtime = AgentRuntime(
        FakeDB(),
        client=ScriptedClient(analyze_plan(), answer_result()),
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(),
        publisher=publisher,
        repository=repository,
    )
    result = asyncio.run(
        fresh_runtime.execute(100, 300, execution_token="new-owner")
    )

    assert result["status"] == "completed"
    fresh_stream_events = [
        event
        for event in publisher.events
        if event["event"].value in {
            "message_started",
            "message_delta",
            "message_completed",
        }
    ]
    assert fresh_stream_events
    assert {event["data"]["streamId"] for event in fresh_stream_events} == {
        "new-owner"
    }


def test_cancellation_after_a_delta_prevents_every_later_delta_and_completion():
    repository = FakeRepository()
    publisher = OwnershipLosingPublisher(repository, emit_cancelled=True)
    runtime = AgentRuntime(
        FakeDB(),
        client=ScriptedClient(analyze_plan(), answer_result()),
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(),
        publisher=publisher,
        repository=repository,
    )

    with pytest.raises(AgentCancelledError):
        asyncio.run(runtime.execute(100, 300, execution_token="cancelled-attempt"))

    names = [event["event"].value for event in publisher.events]
    cancelled_index = names.index("run_cancelled")
    assert "message_delta" not in names[cancelled_index + 1 :]
    assert "message_completed" not in names
    assert "run_completed" not in names


def test_slow_stream_publisher_times_out_once_then_saves_and_charges():
    db = FakeDB()
    repository = FakeRepository()
    repository.run.billing_feature_key = "career_advice"
    repository.run.charge_amount = 1.5
    repository.run.charged_at = None
    billing = FakeBillingService()
    publisher = SlowStreamingPublisher(delay_seconds=0.1)
    runtime = AgentRuntime(
        db,
        client=ScriptedClient(analyze_plan(), answer_result()),
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(stream_publish_timeout_seconds=0.01),
        publisher=publisher,
        repository=repository,
        billing_service=billing,
    )

    started = time.monotonic()
    result = asyncio.run(runtime.execute(100, 300))

    assert time.monotonic() - started < 1
    assert result["status"] == "completed"
    assert publisher.slow_waits == 1
    assert len(billing.charges) == 1
    assert repository.created_messages[-1].content == answer_result().to_markdown()
    assert [event["event"].value for event in publisher.events][-2:] == [
        "message_completed",
        "run_completed",
    ]


def test_streaming_chunk_count_does_not_add_database_commits():
    short_db = FakeDB()
    short_publisher = FakePublisher()
    short_runtime = AgentRuntime(
        short_db,
        client=ScriptedClient(analyze_plan(), answer_result()),
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(),
        publisher=short_publisher,
        repository=FakeRepository(),
    )
    long_answer = answer_result().model_copy(
        update={"summary": "长期职业规划与市场证据。" * 250}
    )
    long_db = FakeDB()
    long_publisher = FakePublisher()
    long_runtime = AgentRuntime(
        long_db,
        client=ScriptedClient(analyze_plan(), long_answer),
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(),
        publisher=long_publisher,
        repository=FakeRepository(),
    )

    asyncio.run(short_runtime.execute(100, 300, execution_token="short-attempt"))
    asyncio.run(long_runtime.execute(100, 300, execution_token="long-attempt"))

    short_deltas = sum(
        event["event"].value == "message_delta" for event in short_publisher.events
    )
    long_deltas = sum(
        event["event"].value == "message_delta" for event in long_publisher.events
    )
    assert long_deltas > short_deltas
    assert short_db.commits == long_db.commits == 7


def test_post_commit_terminal_publish_is_extremely_bounded_after_deadline():
    db = DeadlineExpiringDB()
    publisher = SlowRunCompletedPublisher(delay_seconds=0.2)
    runtime = AgentRuntime(
        db,
        client=ScriptedClient(analyze_plan(), answer_result()),
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(stream_publish_timeout_seconds=0.5),
        publisher=publisher,
        repository=FakeRepository(),
    )
    db.on_final_commit = lambda: setattr(runtime, "deadline", time.monotonic() - 1)

    started = time.monotonic()
    result = asyncio.run(runtime.execute(100, 300))

    assert result["status"] == "completed"
    assert publisher.slow_waits == 1
    assert time.monotonic() - started < 0.1


def test_safe_event_publisher_isolates_redis_failure_from_success_and_billing():
    db = FakeDB()
    repository = FakeRepository()
    repository.run.billing_feature_key = "career_advice"
    repository.run.charge_amount = 1.5
    repository.run.charged_at = None
    billing = FakeBillingService()
    runtime = AgentRuntime(
        db,
        client=ScriptedClient(analyze_plan(), answer_result()),
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(),
        publisher=AgentEventPublisher(ExplodingEventStore()),
        repository=repository,
        billing_service=billing,
    )

    result = asyncio.run(runtime.execute(100, 300))

    assert result["status"] == "completed"
    assert repository.created_messages[-1].message_type == "analysis_result"
    assert repository.transitions[-1]["to_status"] == "completed"
    assert len(billing.charges) == 1


def test_runtime_does_not_hide_an_invalid_injected_publisher():
    repository = FakeRepository()
    runtime = AgentRuntime(
        FakeDB(),
        client=ScriptedClient(analyze_plan(), answer_result()),
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(),
        publisher=ExplodingPublisher(),
        repository=repository,
    )

    with pytest.raises(RuntimeError, match="invalid test publisher"):
        asyncio.run(runtime.execute(100, 300))

    assert repository.created_messages == []


def test_runtime_retries_one_transient_answer_model_timeout_within_run_budget():
    client = TimeoutOnceAnswerClient(analyze_plan(), answer_result())
    runtime = AgentRuntime(
        FakeDB(),
        client=client,
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(),
        publisher=FakePublisher(),
        repository=FakeRepository(),
    )

    result = asyncio.run(runtime.execute(100, 300))

    assert result["status"] == "completed"
    assert client.answer_attempts == 2


def test_answer_model_timeout_is_not_retried_when_remaining_budget_is_too_small():
    # 剩余预算装不下下一次完整 LLM 调用时，重试注定失败，应立即放弃而非烧掉尾款预算。
    client = TimeoutOnceAnswerClient(analyze_plan(), answer_result())
    runtime = AgentRuntime(
        FakeDB(),
        client=client,
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(llm_timeout_seconds=90),
        publisher=FakePublisher(),
        repository=FakeRepository(),
    )
    runtime.deadline = time.monotonic() + 1

    with pytest.raises(AgentDeadlineExceededError):
        asyncio.run(runtime._call_structured("system", "user", AgentAnswer))

    assert client.answer_attempts == 1


def test_market_question_does_not_inherit_unmentioned_profile_filters():
    repository = FakeRepository()
    repository.messages = [
        SimpleNamespace(
            role="user",
            content="我现在想去上海应聘 Python 后端开发，分析当前市场行情",
            message_type="market_question",
        )
    ]
    plan = AgentPlan.model_validate(
        {
            "intent": "上海 Python 后端市场行情",
            "action": "analyze",
            "tools": [
                {
                    "name": "search_jobs",
                    "arguments": {
                        "keyword": "Python 后端",
                        "cities": ["上海"],
                        "education": "本科",
                        "experience": "应届生",
                        "skills": ["Django"],
                    },
                }
            ],
        }
    )
    tool = CapturingSearchTool()
    runtime = AgentRuntime(
        FakeDB(),
        client=ScriptedClient(plan, answer_result()),
        registry=make_registry(tool),
        policies=make_policies(),
        publisher=FakePublisher(),
        repository=repository,
    )

    result = asyncio.run(runtime.execute(100, 300))

    assert result["status"] == "completed"
    assert tool.input_data.cities == ["上海"]
    assert tool.input_data.education is None
    assert tool.input_data.experience is None
    assert tool.input_data.skills == []


def test_runtime_does_not_reuse_expired_orm_messages_after_tool_transactions():
    db = FakeDB()
    repository = FakeRepository()
    message = ExpiringMessage("user", "杭州人工智能岗位趋势如何？")
    repository.messages = [message]
    runtime = AgentRuntime(
        db,
        client=ScriptedClient(analyze_plan(), answer_result()),
        registry=make_registry(ExpiringSearchTool(message)),
        policies=make_policies(),
        publisher=FakePublisher(),
        repository=repository,
    )

    result = asyncio.run(runtime.execute(100, 300))

    assert message.expired is True
    assert result["status"] == "completed"


def test_runtime_charges_successful_run_once_with_stable_order_number():
    db = FakeDB()
    repository = FakeRepository()
    repository.run.billing_feature_key = "career_advice"
    repository.run.charge_amount = 1.5
    repository.run.charged_at = None
    billing = FakeBillingService()
    runtime = AgentRuntime(
        db,
        client=ScriptedClient(analyze_plan(), answer_result()),
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(),
        publisher=FakePublisher(),
        repository=repository,
        billing_service=billing,
    )

    result = asyncio.run(runtime.execute(100, 300))

    assert result["status"] == "completed"
    assert billing.charges == [
        {
            "user_id": 300,
            "feature_key": "career_advice",
            "amount": 1.5,
            "detail_suffix": "agent_run:100",
            "order_no": "agent_run:100",
            "commit": False,
        }
    ]
    assert billing.committed_charges == 0
    assert repository.transitions[-1]["values"]["charged_at"] is not None


def test_late_cancellation_rolls_back_agent_charge_with_result():
    db = FakeDB()
    repository = FakeRepository(cancel_on_status="completed")
    repository.run.billing_feature_key = "career_advice"
    repository.run.charge_amount = 1.5
    repository.run.charged_at = None
    billing = FakeBillingService()
    publisher = FakePublisher()
    runtime = AgentRuntime(
        db,
        client=ScriptedClient(analyze_plan(), answer_result()),
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(),
        publisher=publisher,
        repository=repository,
        billing_service=billing,
    )

    with pytest.raises(AgentCancelledError):
        asyncio.run(runtime.execute(100, 300))

    assert billing.committed_charges == 0
    assert db.rollbacks == 1
    assert not {
        "message_completed",
        "run_completed",
    } & {event["event"].value for event in publisher.events}


def test_runtime_requests_one_clarification():
    plan = AgentPlan(
        intent="职业方向不明确",
        action="clarify",
        missing_information=["目标城市"],
        clarification_question="你优先考虑哪个城市？",
    )
    db = FakeDB()
    repository = FakeRepository()
    runtime = AgentRuntime(
        db,
        client=ScriptedClient(plan),
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(),
        publisher=FakePublisher(),
        repository=repository,
    )

    result = asyncio.run(runtime.execute(100, 300))

    assert result["status"] == "waiting_user"
    assert repository.created_messages[-1].message_type == "clarification_required"
    assert repository.transitions[-1]["to_status"] == "waiting_user"


def test_runtime_refuses_to_answer_when_all_tools_fail():
    publisher = FakePublisher()
    runtime = AgentRuntime(
        FakeDB(),
        client=ScriptedClient(analyze_plan(), answer_result()),
        registry=make_registry(FailedSearchTool()),
        policies=make_policies(),
        publisher=publisher,
        repository=FakeRepository(),
    )

    with pytest.raises(AgentEvidenceUnavailableError):
        asyncio.run(runtime.execute(100, 300))
    assert not {
        "message_started",
        "message_completed",
        "run_completed",
    } & {event["event"].value for event in publisher.events}


def test_runtime_refuses_empty_success_as_evidence():
    runtime = AgentRuntime(
        FakeDB(),
        client=ScriptedClient(analyze_plan(), answer_result()),
        registry=make_registry(EmptySearchTool()),
        policies=make_policies(),
        publisher=FakePublisher(),
        repository=FakeRepository(),
    )
    with pytest.raises(AgentEvidenceUnavailableError):
        asyncio.run(runtime.execute(100, 300))


def test_runtime_enforces_tool_call_limit():
    runtime = AgentRuntime(
        FakeDB(),
        client=ScriptedClient(analyze_plan(tool_count=2), answer_result()),
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(max_tool_calls=1),
        publisher=FakePublisher(),
        repository=FakeRepository(),
    )

    with pytest.raises(AgentLimitExceededError):
        asyncio.run(runtime.execute(100, 300))


def test_runtime_rolls_back_late_answer_after_cancellation():
    db = FakeDB()
    repository = FakeRepository(cancel_on_status="completed")
    runtime = AgentRuntime(
        db,
        client=ScriptedClient(analyze_plan(), answer_result()),
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(),
        publisher=FakePublisher(),
        repository=repository,
    )

    with pytest.raises(AgentCancelledError):
        asyncio.run(runtime.execute(100, 300))
    assert db.rollbacks == 1


def test_runtime_enforces_whole_run_deadline():
    publisher = FakePublisher()
    runtime = AgentRuntime(
        FakeDB(),
        client=ScriptedClient(analyze_plan(), answer_result()),
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(run_timeout_seconds=-1),
        publisher=publisher,
        repository=FakeRepository(),
    )
    with pytest.raises(AgentDeadlineExceededError):
        asyncio.run(runtime.execute(100, 300))
    assert not {
        "message_started",
        "message_completed",
        "run_completed",
    } & {event["event"].value for event in publisher.events}


def test_production_llm_client_rejects_mock_provider(monkeypatch):
    from services import llm_client as llm_module

    monkeypatch.setattr(llm_module.settings, "AI_PROVIDER", "mock")
    monkeypatch.setattr(llm_module.settings, "AI_API_KEY", "test")
    with pytest.raises(LLMConfigurationError):
        LLMClient()._ensure_configured()


def test_celery_agent_task_allows_the_extended_model_runtime_budget():
    from tasks.agent_tasks import execute_agent_run

    assert execute_agent_run.soft_time_limit >= 270
    assert execute_agent_run.time_limit >= 300
