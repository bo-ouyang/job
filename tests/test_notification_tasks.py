import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from tasks import notification_tasks  # noqa: E402
from tasks import agent_tasks  # noqa: E402
from core.celery_app import celery_app  # noqa: E402


@pytest.mark.asyncio
async def test_agent_terminal_task_creates_a_career_notification_and_skips_market_questions(monkeypatch):
    created = []

    async def create_and_publish(notification):
        created.append(notification)
        return object()

    monkeypatch.setattr(
        notification_tasks.notification_service,
        "create_and_publish",
        create_and_publish,
    )

    await notification_tasks.save_agent_run_message(
        user_id=7,
        run_id=101,
        status="completed",
        input_message_type="career_question",
    )
    await notification_tasks.save_agent_run_message(
        user_id=7,
        run_id=102,
        status="completed",
        input_message_type="market_question",
    )

    assert len(created) == 1
    assert created[0].action_data == {"route": "/career-analysis", "runId": "101"}


@pytest.mark.asyncio
async def test_agent_notification_resolves_the_persisted_input_type_and_deduplicates_terminal_retries(monkeypatch):
    """Worker retries must re-use the run's source type, never notify market chat."""
    created = []

    async def resolve_type(run_id, user_id):
        return "career_report_request"

    async def create_and_publish(notification):
        created.append(notification)
        return object()

    monkeypatch.setattr(notification_tasks, "_resolve_agent_message_type", resolve_type)
    monkeypatch.setattr(
        notification_tasks.notification_service,
        "create_and_publish",
        create_and_publish,
    )

    await notification_tasks.save_agent_run_message(
        user_id=7, run_id=101, status="failed", error_message="model timeout"
    )
    # Simulate a retry after the first DB transaction reached its terminal state.
    await notification_tasks.save_agent_run_message(
        user_id=7, run_id=101, status="failed", error_message="model timeout"
    )

    # The durable service owns the actual UPSERT; this entry point must retain
    # exactly the same idempotency key across Celery retries.
    assert [item.dedupe_key for item in created] == [
        "agent_run:101:failed",
        "agent_run:101:failed",
    ]
    assert created[0].action_data == {"route": "/career-analysis", "runId": "101"}


@pytest.mark.asyncio
async def test_agent_terminal_task_skips_market_question_after_resolving_source_type(monkeypatch):
    published = []

    async def resolve_type(run_id, user_id):
        return "market_question"

    async def create_and_publish(notification):
        published.append(notification)

    monkeypatch.setattr(notification_tasks, "_resolve_agent_message_type", resolve_type)
    monkeypatch.setattr(
        notification_tasks.notification_service,
        "create_and_publish",
        create_and_publish,
    )

    result = await notification_tasks.save_agent_run_message(
        user_id=7, run_id=102, status="cancelled"
    )

    assert result is None
    assert published == []


@pytest.mark.asyncio
async def test_agent_notification_reconciliation_repairs_missing_terminal_notification_and_skips_market(monkeypatch):
    """A broker outage must not make a committed terminal AgentRun invisible forever."""
    persisted = []

    async def list_missing():
        return [
            {"run_id": 101, "user_id": 7, "status": "cancelled", "message_type": "career_question", "error_message": None},
            {"run_id": 102, "user_id": 7, "status": "completed", "message_type": "market_question", "error_message": None},
        ]

    async def save_agent_run_message(**kwargs):
        persisted.append(kwargs)
        return object()

    monkeypatch.setattr(notification_tasks, "_list_unnotified_terminal_agent_runs", list_missing)
    monkeypatch.setattr(notification_tasks, "save_agent_run_message", save_agent_run_message)

    result = await notification_tasks.reconcile_agent_run_notifications_async()

    assert result == {"scanned": 2, "repaired": 1, "skipped": 1}
    assert persisted == [{
        "run_id": 101,
        "user_id": 7,
        "status": "cancelled",
        "input_message_type": "career_question",
        "error_message": None,
    }]


def test_agent_notification_reconciliation_is_registered_with_celery_beat():
    schedule = celery_app.conf.beat_schedule
    assert any(
        entry["task"] == "tasks.notification_tasks.reconcile_agent_run_notifications"
        for entry in schedule.values()
    )


@pytest.mark.asyncio
async def test_agent_worker_notifies_after_a_committed_terminal_run(monkeypatch):
    notified = []

    class _Run:
        status = "completed"
        error_message = None

    async def get_run(db, *, run_id, user_id):
        return _Run()

    async def save_agent_run_message(**kwargs):
        notified.append(kwargs)

    monkeypatch.setattr(agent_tasks.crud_agent, "get_run", get_run)
    monkeypatch.setattr(
        notification_tasks,
        "save_agent_run_message",
        save_agent_run_message,
    )

    await agent_tasks._notify_terminal_run(object(), run_id=101, user_id=7)

    assert notified == [{"run_id": 101, "user_id": 7, "status": "completed", "error_message": None}]


def test_cancelled_agent_run_is_enqueued_for_retryable_notification_persistence(monkeypatch):
    dispatched = []

    def apply_async(**kwargs):
        dispatched.append(kwargs)

    monkeypatch.setattr(notification_tasks.persist_agent_run_message, "apply_async", apply_async)

    notification_tasks.enqueue_agent_run_message(user_id=7, run_id=101, status="cancelled")

    assert dispatched == [{
        "kwargs": {"user_id": 7, "run_id": 101, "status": "cancelled", "error_message": None},
        "queue": "batch",
        "routing_key": "batch",
    }]


@pytest.mark.asyncio
async def test_agent_failure_sse_error_still_notifies_after_terminal_commit(monkeypatch):
    commits = []
    notifications = []
    failed_run = type("Run", (), {"id": 101, "conversation_id": 11})()

    class _Session:
        async def commit(self):
            commits.append("failed_run_committed")

    class _SessionContext:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    async def get_session():
        return _SessionContext()

    async def transition_run(*args, **kwargs):
        return failed_run

    async def publisher_failure(**kwargs):
        raise RuntimeError("redis event stream unavailable")

    async def notify_after_commit(*args, **kwargs):
        assert commits == ["failed_run_committed"]
        notifications.append(kwargs)

    monkeypatch.setattr(agent_tasks.db_manager, "get_session", get_session)
    monkeypatch.setattr(agent_tasks.crud_agent, "transition_run", transition_run)
    monkeypatch.setattr(agent_tasks.agent_event_publisher, "publish", publisher_failure)
    monkeypatch.setattr(agent_tasks, "_notify_terminal_run", notify_after_commit)

    await agent_tasks._mark_failed(
        run_id=101,
        user_id=7,
        error=RuntimeError("model unavailable"),
        execution_token="token-1",
    )

    assert notifications == [{"run_id": 101, "user_id": 7}]
