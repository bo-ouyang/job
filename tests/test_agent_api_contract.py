import inspect
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from api.v1.api import api_router
from api.v1.endpoints import agent_controller
from services.agent_submission_service import agent_submission_service
from core.exceptions import AppException
from tasks import notification_tasks
from dependencies import get_current_user_id_short_lived


def agent_route_pairs():
    return {
        (method, f"/api/v1{route.path}")
        for route in api_router.routes
        if route.path.startswith("/agent")
        for method in (route.methods or set())
    }


def test_agent_route_surface_is_complete():
    expected = {
        ("GET", "/api/v1/agent/capabilities"),
        ("POST", "/api/v1/agent/conversations"),
        ("GET", "/api/v1/agent/conversations"),
        ("GET", "/api/v1/agent/conversations/{conversation_id}"),
        ("PATCH", "/api/v1/agent/conversations/{conversation_id}"),
        ("POST", "/api/v1/agent/conversations/{conversation_id}/messages"),
        ("GET", "/api/v1/agent/runs/{run_id}"),
        ("GET", "/api/v1/agent/runs/{run_id}/events"),
        ("POST", "/api/v1/agent/runs/{run_id}/cancel"),
        ("GET", "/api/v1/agent/profile"),
        ("PATCH", "/api/v1/agent/profile"),
    }
    assert expected <= agent_route_pairs()


def test_agent_message_submission_requires_idempotency_header():
    parameter = inspect.signature(agent_controller.submit_message).parameters[
        "idempotency_key"
    ]
    assert parameter.default.alias == "Idempotency-Key"
    assert parameter.default.is_required()


def test_agent_sse_uses_short_lived_authentication_dependency():
    route = next(
        route
        for route in api_router.routes
        if route.path == "/agent/runs/{run_id}/events"
    )
    dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
    assert get_current_user_id_short_lived in dependency_calls


def test_agent_capabilities_advertise_validated_markdown_delta_streaming(monkeypatch):
    monkeypatch.setattr(agent_controller, "_agent_enabled_for_user", lambda user_id: True)

    capabilities = asyncio.run(
        agent_controller.get_agent_capabilities(current_user=SimpleNamespace(id=7))
    )

    assert capabilities["supports_sse"] is True
    assert capabilities["supports_message_delta"] is True
    assert capabilities["message_stream_mode"] == "validated_markdown_chunks"


class _DispatchFailureDb:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        raise AssertionError("dispatch failure must not roll back the committed run")


@pytest.mark.asyncio
@pytest.mark.parametrize("waiting_resume", [False, True])
async def test_agent_dispatch_failure_commits_failed_run_then_enqueues_durable_notification(
    monkeypatch, waiting_resume
):
    """Both new and resumed Agent runs must immediately enter notification flow."""
    db = _DispatchFailureDb()
    current_user = SimpleNamespace(id=7)
    conversation = SimpleNamespace(id=11, status="active")
    queued_run = SimpleNamespace(
        id=101,
        conversation_id=11,
        status="waiting_user" if waiting_resume else "queued",
    )
    failed_run = SimpleNamespace(id=101, conversation_id=11, status="failed")
    dispatched_notifications = []
    transitions = []

    async def no_run(*args, **kwargs):
        return None

    async def latest_run(*args, **kwargs):
        return queued_run if waiting_resume else None

    async def create_message(*args, **kwargs):
        return SimpleNamespace(id=1001)

    async def create_run(*args, **kwargs):
        return queued_run

    async def transition_run(*args, **kwargs):
        transitions.append(kwargs)
        return failed_run if len(transitions) > 1 or not waiting_resume else queued_run

    async def noop(*args, **kwargs):
        return None

    async def ensure_access(**kwargs):
        return 0

    async def publish(**kwargs):
        return None

    def enqueue_notification(**kwargs):
        # The second commit is the failed terminal state commit.
        assert db.commits == 2
        dispatched_notifications.append(kwargs)

    def dispatch_failure(**kwargs):
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(agent_submission_service, "_get_owned_conversation", lambda *args: asyncio.sleep(0, result=conversation))
    monkeypatch.setattr(agent_controller.crud_agent, "get_run_by_idempotency_key", no_run)
    monkeypatch.setattr(agent_controller.crud_agent, "get_message_by_idempotency_key", no_run)
    monkeypatch.setattr(agent_controller.crud_agent, "get_latest_run", latest_run)
    monkeypatch.setattr(agent_controller.crud_agent, "create_message", create_message)
    monkeypatch.setattr(agent_controller.crud_agent, "create_run", create_run)
    monkeypatch.setattr(agent_controller.crud_agent, "transition_run", transition_run)
    monkeypatch.setattr(agent_controller.crud_agent, "acquire_user_admission_lock", noop)
    monkeypatch.setattr(agent_controller.crud_agent, "count_active_runs", lambda *args, **kwargs: asyncio.sleep(0, result=0))
    monkeypatch.setattr(
        "services.agent_submission_service.ai_access_service.ensure_access",
        ensure_access,
    )
    monkeypatch.setattr("services.agent_submission_service._ensure_agent_enabled", lambda *args: None)
    monkeypatch.setattr("services.agent_submission_service._enforce_agent_user_rate_limit", noop)
    monkeypatch.setattr(agent_controller.agent_event_publisher, "publish", publish)
    monkeypatch.setattr(
        "services.agent_submission_service.execute_agent_run.apply_async",
        dispatch_failure,
    )
    monkeypatch.setattr("services.agent_submission_service._enqueue_terminal_notification", enqueue_notification)

    with pytest.raises(AppException) as exc_info:
        await agent_controller.submit_message(
            conversation_id=11,
            obj_in=SimpleNamespace(content="分析我的职业", message_type="career_question"),
            idempotency_key="dispatch-failure-001",
            db=db,
            current_user=current_user,
        )

    assert exc_info.value.message == (
        "Agent 运行恢复失败，请稍后重试"
        if waiting_resume
        else "Agent 运行派发失败，请稍后重试"
    )
    assert dispatched_notifications == [{
        "user_id": 7,
        "run_id": 101,
        "status": "failed",
        "error_message": "broker unavailable",
    }]


@pytest.mark.asyncio
async def test_cancel_broker_failure_is_repaired_once_by_terminal_notification_reconciliation(monkeypatch):
    db = _DispatchFailureDb()
    cancelled_run = SimpleNamespace(id=101, conversation_id=11, status="cancelled")
    reconciled_calls = []
    created_results = iter([True, False])

    async def get_run(*args, **kwargs):
        return cancelled_run

    async def cancel_run(*args, **kwargs):
        return cancelled_run

    async def publish(**kwargs):
        return None

    def broker_failure(**kwargs):
        raise RuntimeError("broker unavailable")

    async def list_missing():
        return [{
            "run_id": 101,
            "user_id": 7,
            "status": "cancelled",
            "message_type": "career_question",
            "error_message": None,
        }]

    async def save_agent_run_message(**kwargs):
        reconciled_calls.append(kwargs)
        return SimpleNamespace(created=next(created_results))

    monkeypatch.setattr(agent_controller.crud_agent, "get_run", get_run)
    monkeypatch.setattr(agent_controller.crud_agent, "cancel_run", cancel_run)
    monkeypatch.setattr(agent_controller.agent_event_publisher, "publish", publish)
    monkeypatch.setattr(notification_tasks, "enqueue_agent_run_message", broker_failure)
    monkeypatch.setattr(notification_tasks, "_list_unnotified_terminal_agent_runs", list_missing)
    monkeypatch.setattr(notification_tasks, "save_agent_run_message", save_agent_run_message)

    result = await agent_controller.cancel_run(
        run_id=101,
        db=db,
        current_user=SimpleNamespace(id=7),
    )
    first_reconcile = await notification_tasks.reconcile_agent_run_notifications_async()
    second_reconcile = await notification_tasks.reconcile_agent_run_notifications_async()

    assert result is cancelled_run
    assert db.commits == 1
    assert first_reconcile == {"scanned": 1, "repaired": 1, "skipped": 0}
    assert second_reconcile == {"scanned": 1, "repaired": 0, "skipped": 0}
    assert [call["run_id"] for call in reconciled_calls] == [101, 101]


@pytest.mark.asyncio
async def test_cancel_sse_failure_does_not_turn_committed_cancellation_into_500_or_skip_notification(monkeypatch):
    db = _DispatchFailureDb()
    cancelled_run = SimpleNamespace(id=101, conversation_id=11, status="cancelled")
    notifications = []

    async def get_run(*args, **kwargs):
        return cancelled_run

    async def cancel_run(*args, **kwargs):
        return cancelled_run

    async def publisher_failure(**kwargs):
        raise RuntimeError("redis event stream unavailable")

    def enqueue_notification(**kwargs):
        assert db.commits == 1
        notifications.append(kwargs)

    monkeypatch.setattr(agent_controller.crud_agent, "get_run", get_run)
    monkeypatch.setattr(agent_controller.crud_agent, "cancel_run", cancel_run)
    monkeypatch.setattr(agent_controller.agent_event_publisher, "publish", publisher_failure)
    monkeypatch.setattr(agent_controller, "_enqueue_terminal_notification", enqueue_notification)

    result = await agent_controller.cancel_run(
        run_id=101,
        db=db,
        current_user=SimpleNamespace(id=7),
    )

    assert result is cancelled_run
    assert notifications == [{
        "user_id": 7,
        "run_id": 101,
        "status": "cancelled",
    }]
