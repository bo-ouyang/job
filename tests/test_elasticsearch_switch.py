import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from config import Settings
from common.search import conn
from tasks import es_sync


def test_elasticsearch_switch_defaults_to_disabled():
    field = Settings.model_fields.get("ES_ENABLED")

    assert field is not None
    assert field.default is False


def test_disabled_elasticsearch_never_creates_a_client(monkeypatch):
    monkeypatch.setattr(
        conn,
        "settings",
        SimpleNamespace(
            ES_ENABLED=False,
            ES_URL="http://localhost:9200",
            ES_USER="elastic",
            ES_PASSWORD="",
        ),
    )
    manager = conn.ESManager()
    connect = AsyncMock()
    monkeypatch.setattr(manager, "connect", connect)

    assert asyncio.run(manager.health_check()) is False
    connect.assert_not_awaited()
    with pytest.raises(RuntimeError, match="disabled"):
        asyncio.run(manager.get_es())


def test_disabled_elasticsearch_skips_sync_task_dependencies(monkeypatch):
    monkeypatch.setattr(es_sync, "settings", SimpleNamespace(ES_ENABLED=False))
    initialize = AsyncMock()
    monkeypatch.setattr(es_sync.db_manager, "initialize", initialize)

    result = asyncio.run(es_sync._sync_job_logic(123))

    assert result == {"job_id": "123", "status": "disabled"}
    initialize.assert_not_awaited()


def test_disabled_elasticsearch_skips_delete_task_event_loop(monkeypatch):
    monkeypatch.setattr(es_sync, "settings", SimpleNamespace(ES_ENABLED=False))
    get_event_loop = Mock()
    monkeypatch.setattr(es_sync, "_get_event_loop", get_event_loop)

    result = es_sync.delete_job_from_es.run(123)

    assert result == {"job_id": "123", "status": "disabled"}
    get_event_loop.assert_not_called()
