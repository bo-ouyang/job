import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from services.notification_service import (  # noqa: E402
    NotificationInput,
    NotificationPersistenceError,
    NotificationService,
    build_agent_run_notification,
)
from schemas.v2.message import MessagePageResponse, MessageView  # noqa: E402


class _Session:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _MemoryRepository:
    def __init__(self):
        self.rows = {}

    async def create_or_get(self, db, payload):
        message = self.rows.get(payload.dedupe_key)
        if message is not None:
            return message, False
        message = SimpleNamespace(id=9007199254740993, is_read=False, **payload.to_model_values())
        self.rows[payload.dedupe_key] = message
        return message, True


class _RecordingPublisher:
    def __init__(self, failure=None):
        self.events = []
        self.failure = failure

    async def publish_new_message(self, user_id, message):
        if self.failure:
            raise self.failure
        self.events.append((user_id, message))


@pytest.mark.asyncio
async def test_notification_service_deduplicates_before_publishing_and_serializes_ids_as_strings():
    session = _Session()
    repository = _MemoryRepository()
    publisher = _RecordingPublisher()
    service = NotificationService(
        session_factory=lambda: _SessionContext(session),
        repository=repository,
        publisher=publisher,
    )
    payload = NotificationInput(
        receiver_id=7,
        title="简历解析完成",
        content="简历信息已更新",
        category="resume",
        status="completed",
        source_type="resume_parse",
        source_id="celery-resume-1",
        dedupe_key="resume_parse:celery-resume-1:completed",
        action_type="navigate",
        action_data={"route": "/my/resume"},
    )

    first = await service.create_and_publish(payload)
    second = await service.create_and_publish(payload)

    assert first.message_id == "9007199254740993"
    assert first.created is True
    assert second.created is False
    assert session.commits == 2
    assert len(publisher.events) == 1
    assert publisher.events[0][1]["id"] == "9007199254740993"
    assert publisher.events[0][1]["actionData"] == {"route": "/my/resume"}


@pytest.mark.asyncio
async def test_notification_service_commits_before_ws_and_keeps_persisted_message_when_ws_fails():
    session = _Session()
    repository = _MemoryRepository()
    service = NotificationService(
        session_factory=lambda: _SessionContext(session),
        repository=repository,
        publisher=_RecordingPublisher(failure=RuntimeError("redis offline")),
    )

    result = await service.create_and_publish(
        NotificationInput(
            receiver_id=7,
            title="职业分析完成",
            content="报告已生成",
            category="career",
            status="completed",
            source_type="agent_run",
            source_id="101",
            dedupe_key="agent_run:101:completed",
            action_type="navigate",
            action_data={"route": "/career-analysis", "runId": "101"},
        )
    )

    assert result.created is True
    assert session.commits == 1
    assert result.ws_published is False


@pytest.mark.asyncio
async def test_notification_service_never_publishes_a_message_when_database_persistence_fails():
    class _FailingRepository:
        async def create_or_get(self, db, payload):
            raise RuntimeError("database unavailable")

    session = _Session()
    publisher = _RecordingPublisher()
    service = NotificationService(
        session_factory=lambda: _SessionContext(session),
        repository=_FailingRepository(),
        publisher=publisher,
    )

    with pytest.raises(NotificationPersistenceError, match="database unavailable"):
        await service.create_and_publish(
            NotificationInput(
                receiver_id=7,
                title="失败",
                content="失败",
                category="career",
                status="failed",
                source_type="agent_run",
                source_id="101",
                dedupe_key="agent_run:101:failed",
            )
        )

    assert session.rollbacks == 1
    assert publisher.events == []


@pytest.mark.asyncio
async def test_notification_service_wraps_session_open_failures_without_attempting_ws_publish():
    """A transient DB connection failure must remain retryable, not leak UnboundLocalError."""

    class _FailingSessionContext:
        async def __aenter__(self):
            raise RuntimeError("database connection unavailable")

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    publisher = _RecordingPublisher()
    service = NotificationService(
        session_factory=lambda: _FailingSessionContext(),
        repository=_MemoryRepository(),
        publisher=publisher,
    )

    with pytest.raises(NotificationPersistenceError, match="database connection unavailable"):
        await service.create_and_publish(
            NotificationInput(
                receiver_id=7,
                title="失败",
                content="失败",
                category="career",
                status="failed",
                source_type="agent_run",
                source_id="101",
                dedupe_key="agent_run:101:failed",
            )
        )

    assert publisher.events == []


def test_agent_terminal_notifications_only_cover_career_requests_and_use_whitelisted_action_data():
    assert build_agent_run_notification(
        user_id=7,
        run_id=101,
        input_message_type="market_question",
        status="completed",
    ) is None

    notification = build_agent_run_notification(
        user_id=7,
        run_id=101,
        input_message_type="career_report_request",
        status="completed",
    )

    assert notification is not None
    assert notification.dedupe_key == "agent_run:101:completed"
    assert notification.action_data == {"route": "/career-analysis", "runId": "101"}


def test_v2_message_view_uses_camel_case_and_preserves_snowflake_ids():
    message = MessageView.model_validate(
        {
            "id": 9007199254740993,
            "title": "职业分析报告已完成",
            "content": "报告已生成",
            "type": "system",
            "is_read": False,
            "category": "career",
            "status": "completed",
            "action_type": "navigate",
            "action_data": {"route": "/career-analysis", "runId": "101"},
            "source_type": "agent_run",
            "source_id": "101",
            "created_at": "2026-08-07T12:00:00",
        }
    )
    page = MessagePageResponse(items=[message], total=1, skip=0, limit=20)

    assert page.model_dump(by_alias=True)["items"][0]["id"] == "9007199254740993"
    assert page.model_dump(by_alias=True)["items"][0]["actionData"]["runId"] == "101"
