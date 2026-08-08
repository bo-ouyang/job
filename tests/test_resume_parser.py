import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from tasks import resume_parser  # noqa: E402
from crud import ai_task as crud_ai_task  # noqa: E402


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "parsed_data",
    [
        {},
        {"error": "provider unavailable"},
        {"message": "provider unavailable"},
        {"skills": [None]},
    ],
)
async def test_resume_parser_rejects_empty_or_error_ai_results(monkeypatch, parsed_data):
    published_events = []

    async def extract_text(file_path):
        return "Candidate Name\nUniversity\nPython"

    async def parse_resume_text(text):
        return parsed_data

    monkeypatch.setattr(resume_parser, "_extract_text_from_pdf", extract_text)
    monkeypatch.setattr(resume_parser.ai_service, "parse_resume_text", parse_resume_text)
    monkeypatch.setattr(
        resume_parser,
        "_publish_ws",
        lambda user_id, event_type, data: published_events.append((event_type, data)),
    )

    with pytest.raises(RuntimeError):
        await resume_parser._parse_resume_logic(100, "resume.pdf")

    assert not any(event_type == "resume_parsed" for event_type, _ in published_events)


def test_resume_task_persists_structured_notification_only_after_task_commit(monkeypatch):
    events = []

    async def mark_completed(**kwargs):
        events.append("resume_task_committed")

    def save_message(**kwargs):
        assert events == ["resume_task_committed"]
        assert kwargs["status"] == "completed"
        return {"message_id": "9002", "title": "完成", "content": "简历已解析"}

    def publish_ws(user_id, event_type, data):
        events.append(event_type)
        assert data["message_id"] == "9002"

    monkeypatch.setattr(crud_ai_task, "mark_completed", mark_completed)
    monkeypatch.setattr(resume_parser, "_save_resume_message", save_message)
    monkeypatch.setattr(resume_parser, "_publish_ws", publish_ws)

    resume_parser._mark_completed(
        user_id=7,
        celery_task_id="resume-123",
        result_data='{"name":"测试"}',
        started_at=None,
    )

    assert events == ["resume_task_committed", "ai_task_completed"]
