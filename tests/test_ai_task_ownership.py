import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from api.v1.endpoints import ai_controller
from core.exceptions import PermissionDeniedException
from crud import ai_task as crud_ai_task


@pytest.mark.asyncio
async def test_task_result_passes_current_user_id_to_owned_task_lookup(monkeypatch):
    calls = []

    async def get_task_result(task_id, *, db, user_id):
        calls.append({"task_id": task_id, "db": db, "user_id": user_id})
        return {"status": "completed", "result_data": '{"summary": "private"}'}

    monkeypatch.setattr(crud_ai_task, "get_task_result", get_task_result)

    db = object()
    result = await ai_controller.get_ai_task_result(
        task_id="owned-task",
        db=db,
        current_user=SimpleNamespace(id=101),
    )

    assert calls == [{"task_id": "owned-task", "db": db, "user_id": 101}]
    assert result["status"] == "completed"
    assert result["result"]["summary"] == "private"


@pytest.mark.asyncio
async def test_task_result_rejects_another_users_persisted_task_before_celery_fallback(
    monkeypatch,
):
    async def get_task_result(task_id, *, db, user_id):
        return None

    async def get_task_owner_id(task_id, *, db):
        return 202

    monkeypatch.setattr(crud_ai_task, "get_task_result", get_task_result)
    monkeypatch.setattr(crud_ai_task, "get_task_owner_id", get_task_owner_id)

    with pytest.raises(PermissionDeniedException):
        await ai_controller.get_ai_task_result(
            task_id="another-users-task",
            db=object(),
            current_user=SimpleNamespace(id=101),
        )


@pytest.mark.asyncio
async def test_task_result_keeps_celery_fallback_for_unknown_task(monkeypatch):
    async def get_task_result(task_id, *, db, user_id):
        return None

    async def get_task_owner_id(task_id, *, db):
        return None

    celery_app = SimpleNamespace(
        AsyncResult=lambda task_id: SimpleNamespace(state="PENDING")
    )
    monkeypatch.setattr(crud_ai_task, "get_task_result", get_task_result)
    monkeypatch.setattr(crud_ai_task, "get_task_owner_id", get_task_owner_id)
    monkeypatch.setitem(sys.modules, "core.celery_app", SimpleNamespace(celery_app=celery_app))

    result = await ai_controller.get_ai_task_result(
        task_id="unknown-task",
        db=object(),
        current_user=SimpleNamespace(id=101),
    )

    assert result == {"task_id": "unknown-task", "status": "pending"}


@pytest.mark.asyncio
async def test_crud_task_result_scopes_database_lookup_to_requesting_user(monkeypatch):
    class Result:
        def scalar_one_or_none(self):
            return None

    class Db:
        def __init__(self):
            self.statement = None

        async def execute(self, statement):
            self.statement = statement
            return Result()

    db = Db()
    monkeypatch.setattr(crud_ai_task.redis_manager, "redis_client", None)

    result = await crud_ai_task.get_task_result(
        "another-users-task",
        db=db,
        user_id=101,
    )

    compiled = str(db.statement.compile(compile_kwargs={"literal_binds": True}))
    assert result is None
    assert "ai_tasks.user_id = 101" in compiled
    assert "ai_tasks.celery_task_id = 'another-users-task'" in compiled
