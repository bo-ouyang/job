import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from core.exceptions import AppException
from services.agent_submission_service import AgentSubmissionService


@pytest.mark.asyncio
async def test_v2_submission_reuses_user_scoped_idempotent_run_before_creating_conversation(
    monkeypatch,
):
    existing_run = SimpleNamespace(id=301, conversation_id=201, status="queued")
    calls = []

    async def acquire_lock(*args, **kwargs):
        calls.append("lock")

    async def get_existing(*args, **kwargs):
        calls.append(("lookup", kwargs["message_type"]))
        return existing_run

    async def should_not_create(*args, **kwargs):
        raise AssertionError("an idempotent retry must not create a conversation")

    monkeypatch.setattr(
        "services.agent_submission_service.crud_agent.acquire_user_admission_lock",
        acquire_lock,
    )
    monkeypatch.setattr(
        "services.agent_submission_service.crud_agent.get_run_by_user_idempotency_key",
        get_existing,
    )
    monkeypatch.setattr(
        "services.agent_submission_service.crud_agent.create_conversation",
        should_not_create,
    )

    submission = await AgentSubmissionService().submit_new_conversation(
        db=object(),
        user=SimpleNamespace(id=100),
        content="Analyze my career direction",
        filters={"city": "Hangzhou"},
        idempotency_key="career-request-001",
        title="Career report",
        message_type="career_report_request",
    )

    assert submission["run"] is existing_run
    assert calls == ["lock", ("lookup", "career_report_request")]


def test_v1_message_route_delegates_submission_to_application_service():
    from api.v1.endpoints import agent_controller

    source = Path(agent_controller.__file__).read_text(encoding="utf-8")

    assert "agent_submission_service.submit_message(" in source


@pytest.mark.asyncio
async def test_v1_message_route_passes_request_objects_to_submission_service(monkeypatch):
    from api.v1.endpoints import agent_controller

    captured = {}
    db = object()
    current_user = SimpleNamespace(id=7)
    obj_in = SimpleNamespace(content="Analyze my career", message_type="career_question")
    expected = {"message": SimpleNamespace(id=11), "run": SimpleNamespace(id=21)}

    async def submit_message(**kwargs):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(
        agent_controller.agent_submission_service,
        "submit_message",
        submit_message,
    )

    result = await agent_controller.submit_message(
        conversation_id=42,
        obj_in=obj_in,
        idempotency_key="v1-route-forwarding-001",
        db=db,
        current_user=current_user,
    )

    assert result is expected
    assert captured == {
        "conversation_id": 42,
        "obj_in": obj_in,
        "idempotency_key": "v1-route-forwarding-001",
        "db": db,
        "current_user": current_user,
    }


@pytest.mark.asyncio
async def test_submission_service_preserves_original_agent_disabled_message(monkeypatch):
    async def get_conversation(*args, **kwargs):
        return SimpleNamespace(status="active")

    monkeypatch.setattr(
        "services.agent_submission_service.settings.AGENT_ENABLED",
        False,
    )
    monkeypatch.setattr(AgentSubmissionService, "_get_owned_conversation", get_conversation)
    monkeypatch.setattr(
        "services.agent_submission_service.crud_agent.get_run_by_idempotency_key",
        lambda *args, **kwargs: asyncio.sleep(0, result=None),
    )
    monkeypatch.setattr(
        "services.agent_submission_service.crud_agent.get_message_by_idempotency_key",
        lambda *args, **kwargs: asyncio.sleep(0, result=None),
    )

    with pytest.raises(AppException, match="职业规划 Agent 当前未开放"):
        await AgentSubmissionService().submit_message(
            conversation_id=1,
            obj_in=SimpleNamespace(content="question", message_type="career_question"),
            idempotency_key="agent-disabled-001",
            db=object(),
            current_user=SimpleNamespace(id=9),
        )
