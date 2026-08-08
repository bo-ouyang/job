import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from crud import ai_task as crud_ai_task
from tasks import ai_tasks


class AsyncSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeSession:
    def __init__(self):
        self.events = []

    async def execute(self, statement):
        self.events.append("task_completed")
        return SimpleNamespace(rowcount=1)

    async def commit(self):
        self.events.append("commit")

    async def rollback(self):
        self.events.append("rollback")


def test_career_advice_generation_does_not_charge_before_result_is_persisted(monkeypatch):
    charges = []

    async def generate(*args, **kwargs):
        return "completed answer"

    async def charge_usage(*args, **kwargs):
        charges.append(kwargs)

    async def get_session():
        return AsyncSessionContext(SimpleNamespace())

    monkeypatch.setattr("services.ai_service.ai_service.generate_career_advice", generate)
    monkeypatch.setattr("services.ai_access_service.ai_access_service.charge_usage", charge_usage)
    monkeypatch.setattr("common.databases.PostgresManager.db_manager.get_session", get_session)

    result = asyncio.run(
        ai_tasks._career_advice_logic(7, "Computer Science", ["Python"], "auto", 0.5)
    )

    assert result == "completed answer"
    assert charges == []


def test_task_completion_and_wallet_charge_commit_atomically(monkeypatch):
    session = FakeSession()

    async def get_session():
        return AsyncSessionContext(session)

    async def charge_usage(*args, **kwargs):
        session.events.append("charged")
        assert kwargs["commit"] is False
        assert kwargs["order_no"] == "ai_task:task-123"

    monkeypatch.setattr("common.databases.PostgresManager.db_manager.get_session", get_session)
    monkeypatch.setattr("services.ai_access_service.ai_access_service.charge_usage", charge_usage)
    monkeypatch.setattr(crud_ai_task.redis_manager, "redis_client", None)

    asyncio.run(
        crud_ai_task.mark_completed(
            user_id=7,
            feature_key="career_advice",
            celery_task_id="task-123",
            result_data='{"advice":"done"}',
            charge_amount=0.5,
        )
    )

    assert session.events == ["task_completed", "charged", "commit"]


def test_task_completion_rolls_back_when_wallet_charge_fails(monkeypatch):
    session = FakeSession()

    async def get_session():
        return AsyncSessionContext(session)

    async def charge_usage(*args, **kwargs):
        raise RuntimeError("wallet unavailable")

    monkeypatch.setattr("common.databases.PostgresManager.db_manager.get_session", get_session)
    monkeypatch.setattr("services.ai_access_service.ai_access_service.charge_usage", charge_usage)

    with pytest.raises(RuntimeError, match="wallet unavailable"):
        asyncio.run(
            crud_ai_task.mark_completed(
                user_id=7,
                feature_key="career_advice",
                celery_task_id="task-123",
                result_data='{"advice":"done"}',
                charge_amount=0.5,
            )
        )

    assert "commit" not in session.events
    assert session.events[-1] == "rollback"


def test_completion_callback_rejects_a_result_that_was_not_persisted(monkeypatch):
    async def mark_completed(**kwargs):
        return False

    monkeypatch.setattr(crud_ai_task, "mark_completed", mark_completed)
    monkeypatch.setattr(ai_tasks, "_save_ai_task_message", lambda **kwargs: None)
    monkeypatch.setattr(ai_tasks, "_enqueue_ai_task_message", lambda **kwargs: None)
    monkeypatch.setattr(ai_tasks, "_publish_result", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="was not persisted"):
        ai_tasks._mark_task_completed(
            user_id=7,
            feature_key="career_advice",
            celery_task_id="missing-task",
            result_data='{"advice":"done"}',
            started_at=0,
            charge_amount=0.5,
        )


def test_legacy_ai_task_persists_structured_notification_only_after_task_commit(monkeypatch):
    events = []

    async def mark_completed(**kwargs):
        events.append("ai_task_committed")
        return True

    def save_message(**kwargs):
        assert events == ["ai_task_committed"]
        assert kwargs["status"] == "completed"
        assert kwargs["feature_key"] == "career_advice"
        return {"message_id": "9001", "title": "完成", "content": "已完成"}

    def publish_result(user_id, event_type, data):
        events.append(event_type)
        assert data["message_id"] == "9001"

    monkeypatch.setattr(crud_ai_task, "mark_completed", mark_completed)
    monkeypatch.setattr(ai_tasks, "_save_ai_task_message", save_message)
    monkeypatch.setattr(ai_tasks, "_publish_result", publish_result)

    ai_tasks._mark_task_completed(
        user_id=7,
        feature_key="career_advice",
        celery_task_id="task-123",
        result_data='{"advice":"done"}',
        started_at=None,
    )

    assert events == ["ai_task_committed", "ai_task_completed"]
