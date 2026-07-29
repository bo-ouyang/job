import asyncio
import sys
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
)
from agent.policies import AgentPolicies
from agent.runtime import AgentRuntime
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


class FakePublisher:
    def __init__(self):
        self.events = []

    async def publish(self, **kwargs):
        self.events.append(kwargs)
        return None


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
        return self.run

    async def get_conversation(self, db, **kwargs):
        return SimpleNamespace(id=200, user_id=300)

    async def list_messages(self, db, **kwargs):
        return self.messages

    async def get_profile(self, db, **kwargs):
        return None

    async def transition_run(self, db, **kwargs):
        self.transitions.append(kwargs)
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
    assert [event["event"].value for event in publisher.events] == [
        "run_started",
        "plan_created",
        "tool_started",
        "tool_completed",
        "message_completed",
        "run_completed",
    ]


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
    runtime = AgentRuntime(
        db,
        client=ScriptedClient(analyze_plan(), answer_result()),
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(),
        publisher=FakePublisher(),
        repository=repository,
        billing_service=billing,
    )

    with pytest.raises(AgentCancelledError):
        asyncio.run(runtime.execute(100, 300))

    assert billing.committed_charges == 0
    assert db.rollbacks == 1


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
    runtime = AgentRuntime(
        FakeDB(),
        client=ScriptedClient(analyze_plan(), answer_result()),
        registry=make_registry(FailedSearchTool()),
        policies=make_policies(),
        publisher=FakePublisher(),
        repository=FakeRepository(),
    )

    with pytest.raises(AgentEvidenceUnavailableError):
        asyncio.run(runtime.execute(100, 300))


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
    runtime = AgentRuntime(
        FakeDB(),
        client=ScriptedClient(analyze_plan(), answer_result()),
        registry=make_registry(SuccessfulSearchTool()),
        policies=make_policies(run_timeout_seconds=-1),
        publisher=FakePublisher(),
        repository=FakeRepository(),
    )
    with pytest.raises(AgentDeadlineExceededError):
        asyncio.run(runtime.execute(100, 300))


def test_production_llm_client_rejects_mock_provider(monkeypatch):
    from services import llm_client as llm_module

    monkeypatch.setattr(llm_module.settings, "AI_PROVIDER", "mock")
    monkeypatch.setattr(llm_module.settings, "AI_API_KEY", "test")
    with pytest.raises(LLMConfigurationError):
        LLMClient()._ensure_configured()
