import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from api.v2.endpoints import message_controller  # noqa: E402
from common.databases.PostgresManager import db_manager  # noqa: E402
from dependencies import get_current_user  # noqa: E402


def test_v2_messages_accepts_camel_case_unread_only_query(monkeypatch):
    captured = {}

    async def get_page(db, **kwargs):
        captured.update(kwargs)
        return [], 0

    async def fake_db():
        yield object()

    monkeypatch.setattr(message_controller.crud_message, "get_my_messages_page", get_page)
    app = FastAPI()
    app.include_router(message_controller.router, prefix="/messages")
    app.dependency_overrides[db_manager.get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)

    response = TestClient(app).get("/messages/", params={"unreadOnly": "true"})

    assert response.status_code == 200
    assert captured["unread_only"] is True


@pytest.mark.asyncio
async def test_v2_messages_endpoint_forwards_pagination_filters_and_serializes_snowflake_ids(monkeypatch):
    captured = {}
    row = SimpleNamespace(
        id=9007199254740993,
        title="职业分析报告已完成",
        content="报告已经生成",
        type="system",
        is_read=False,
        category="career",
        status="completed",
        action_type="navigate",
        action_data={"route": "/career-analysis", "runId": "101"},
        source_type="agent_run",
        source_id="101",
        created_at=datetime(2026, 8, 8, 10, 0, 0),
    )

    async def get_my_messages_page(db, **kwargs):
        captured.update(kwargs)
        return [row], 31

    monkeypatch.setattr(
        message_controller.crud_message,
        "get_my_messages_page",
        get_my_messages_page,
    )

    page = await message_controller.list_messages(
        skip=20,
        limit=10,
        unread_only=True,
        category="career",
        status="completed",
        db=object(),
        current_user=SimpleNamespace(id=7),
    )

    assert captured == {
        "receiver_id": 7,
        "skip": 20,
        "limit": 10,
        "unread_only": True,
        "category": "career",
        "status": "completed",
    }
    assert page.model_dump(by_alias=True) == {
        "items": [{
            "id": "9007199254740993",
            "title": "职业分析报告已完成",
            "content": "报告已经生成",
            "type": "system",
            "isRead": False,
            "category": "career",
            "status": "completed",
            "actionType": "navigate",
            "actionData": {"route": "/career-analysis", "runId": "101"},
            "sourceType": "agent_run",
            "sourceId": "101",
            "createdAt": datetime(2026, 8, 8, 10, 0, 0),
        }],
        "total": 31,
        "skip": 20,
        "limit": 10,
    }
