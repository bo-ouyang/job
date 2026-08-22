import asyncio
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from services.ai_task_lifecycle_service import AiTaskLifecycle
from tasks import ai_tasks, resume_parser


def _lifecycle(events, *, completion_result=True, notification_result=None):
    def persist_completed(**kwargs):
        events.append("completed_persisted")
        return completion_result

    def persist_failed(**kwargs):
        events.append("failed_persisted")
        return True

    def save_notification(**kwargs):
        events.append("notification_saved")
        return notification_result

    def enqueue_notification(**kwargs):
        events.append("notification_compensated")

    def publish_event(user_id, event_type, data):
        events.append(event_type)

    return AiTaskLifecycle(
        persist_completed=persist_completed,
        persist_failed=persist_failed,
        save_notification=save_notification,
        enqueue_notification=enqueue_notification,
        publish_event=publish_event,
        feature_display=lambda _feature: "AI task",
        record_metrics=lambda **_kwargs: events.append("metrics_recorded"),
    )


def test_completed_lifecycle_persists_before_notification_and_generic_event():
    events = []
    lifecycle = _lifecycle(events, notification_result={"message_id": "1", "content": "done"})

    lifecycle.complete(
        user_id=7,
        feature_key="career_advice",
        celery_task_id="career-123",
        result_data='{"advice":"done"}',
        started_at=None,
        charge_amount=0.5,
    )

    assert events == [
        "completed_persisted",
        "metrics_recorded",
        "notification_saved",
        "ai_task_completed",
    ]


def test_completed_lifecycle_does_not_emit_success_when_persistence_is_rejected():
    events = []
    lifecycle = _lifecycle(events, completion_result=False)

    with pytest.raises(RuntimeError, match="was not persisted"):
        lifecycle.complete(
            user_id=7,
            feature_key="career_advice",
            celery_task_id="career-123",
            result_data='{"advice":"done"}',
            started_at=None,
        )

    assert events == ["completed_persisted"]


def test_completed_lifecycle_compensates_notification_failure_before_generic_event():
    events = []
    lifecycle = _lifecycle(events)

    lifecycle.complete(
        user_id=7,
        feature_key="resume_parse",
        celery_task_id="resume-123",
        result_data='{"name":"test"}',
        started_at=None,
    )

    assert events == [
        "completed_persisted",
        "metrics_recorded",
        "notification_saved",
        "notification_compensated",
        "ai_task_completed",
    ]


def test_completed_lifecycle_treats_metrics_failure_as_best_effort(caplog):
    events = []

    def persist_completed(**_kwargs):
        events.append("completed_persisted")
        return True

    def persist_failed(**_kwargs):
        events.append("failed_persisted")
        return True

    def record_metrics(**_kwargs):
        raise RuntimeError("metrics unavailable")

    lifecycle = AiTaskLifecycle(
        persist_completed=persist_completed,
        persist_failed=persist_failed,
        save_notification=lambda **_kwargs: {"message_id": "1", "content": "done"},
        enqueue_notification=lambda **_kwargs: events.append("notification_compensated"),
        publish_event=lambda _user_id, event_type, _data: events.append(event_type),
        feature_display=lambda _feature: "AI task",
        record_metrics=record_metrics,
    )

    lifecycle.complete(
        user_id=7,
        feature_key="career_advice",
        celery_task_id="career-123",
        result_data='{"advice":"done"}',
    )

    assert events == ["completed_persisted", "ai_task_completed"]
    assert "metrics unavailable" in caplog.text


def test_failed_lifecycle_treats_metrics_failure_as_best_effort(caplog):
    events = []

    def persist_failed(**_kwargs):
        events.append("failed_persisted")
        return True

    def record_metrics(**_kwargs):
        raise RuntimeError("metrics unavailable")

    lifecycle = AiTaskLifecycle(
        persist_completed=lambda **_kwargs: True,
        persist_failed=persist_failed,
        save_notification=lambda **_kwargs: {"message_id": "1", "content": "failed"},
        enqueue_notification=lambda **_kwargs: events.append("notification_compensated"),
        publish_event=lambda _user_id, event_type, _data: events.append(event_type),
        feature_display=lambda _feature: "AI task",
        record_metrics=record_metrics,
    )

    assert lifecycle.fail(
        user_id=7,
        feature_key="career_advice",
        celery_task_id="career-123",
        error_message="provider unavailable",
    ) is True

    assert events == ["failed_persisted", "ai_task_failed"]
    assert "metrics unavailable" in caplog.text


def test_resume_task_publishes_resume_payload_after_generic_completion(monkeypatch):
    events = []

    async def extract_text(_file_path):
        return "Candidate Name"

    async def parse_resume_text(_text):
        return {"name": "Candidate"}

    monkeypatch.setattr(resume_parser, "_extract_text_from_pdf", extract_text)
    monkeypatch.setattr(resume_parser.ai_service, "parse_resume_text", parse_resume_text)
    monkeypatch.setattr(
        resume_parser,
        "_mark_completed",
        lambda *args: events.append("ai_task_completed"),
    )
    monkeypatch.setattr(
        resume_parser,
        "_publish_ws",
        lambda _user_id, event_type, _data: events.append(event_type),
    )

    resume_parser.parse_resume_task.run(7, "resume.pdf")

    assert events == ["ai_task_completed", "resume_parsed"]


def test_resume_parse_logic_leaves_terminal_events_to_task_wrapper(monkeypatch):
    events = []

    async def extract_text(_file_path):
        return "Candidate Name"

    async def parse_resume_text(_text):
        return {"name": "Candidate"}

    monkeypatch.setattr(resume_parser, "_extract_text_from_pdf", extract_text)
    monkeypatch.setattr(resume_parser.ai_service, "parse_resume_text", parse_resume_text)
    monkeypatch.setattr(
        resume_parser,
        "_publish_ws",
        lambda _user_id, event_type, _data: events.append(event_type),
    )

    result = asyncio.run(resume_parser._parse_resume_logic(7, "resume.pdf"))

    assert json.loads(result) == {"name": "Candidate"}
    assert events == []


def test_resume_task_publishes_specific_error_only_after_generic_failure(monkeypatch):
    events = []

    async def raise_parse_error(_user_id, _file_path):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(resume_parser, "_parse_resume_logic", raise_parse_error)
    monkeypatch.setattr(
        resume_parser,
        "_mark_failed",
        lambda *args: events.append("ai_task_failed") or True,
    )
    monkeypatch.setattr(
        resume_parser,
        "_publish_ws",
        lambda _user_id, event_type, _data: events.append(event_type),
    )

    resume_parser.parse_resume_task.run(7, "resume.pdf")

    assert events == ["ai_task_failed", "resume_parse_error"]


def test_career_task_publishes_specific_error_after_generic_failure(monkeypatch):
    events = []

    async def raise_generation_error(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(ai_tasks, "_career_advice_logic", raise_generation_error)
    monkeypatch.setattr(
        ai_tasks,
        "_mark_task_failed",
        lambda *args: events.append("ai_task_failed") or True,
    )
    monkeypatch.setattr(
        ai_tasks,
        "_publish_error",
        lambda _user_id, event_type, _message: events.append(event_type),
    )

    task = type("Task", (), {"request": type("Request", (), {"id": "career-123"})()})()
    result = ai_tasks.career_advice_task.run(task, 7, "Computer Science", ["Python"])

    assert result == {"status": "error", "error": "provider unavailable"}
    assert events == ["ai_task_failed", "career_advice_error"]
