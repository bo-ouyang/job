import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import CheckConstraint
from types import SimpleNamespace


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))


def _column_names(model) -> set[str]:
    return set(model.__table__.columns.keys())


def _check_expressions(model) -> set[str]:
    return {
        str(constraint.sqltext)
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }


def test_crawler_control_models_persist_workers_runs_and_events():
    from common.databases.models.crawler_control import (
        CrawlerEvent,
        CrawlerRun,
        CrawlerWorker,
    )

    assert CrawlerWorker.__tablename__ == "crawler_workers"
    assert {
        "id",
        "name",
        "hostname",
        "platform",
        "status",
        "capabilities",
        "max_concurrency",
        "active_runs",
        "last_heartbeat_at",
        "created_at",
        "updated_at",
    } <= _column_names(CrawlerWorker)

    assert CrawlerRun.__tablename__ == "crawler_runs"
    assert {
        "id",
        "task_id",
        "worker_id",
        "spider_name",
        "spider_args",
        "desired_status",
        "status",
        "execution_token",
        "pid",
        "metrics",
        "checkpoint",
        "exit_code",
        "error_msg",
        "started_at",
        "heartbeat_at",
        "finished_at",
        "created_at",
        "updated_at",
    } <= _column_names(CrawlerRun)

    assert CrawlerEvent.__tablename__ == "crawler_events"
    assert {
        "id",
        "run_id",
        "worker_id",
        "event_type",
        "level",
        "message",
        "payload",
        "created_at",
    } <= _column_names(CrawlerEvent)

    assert any("status" in expression for expression in _check_expressions(CrawlerWorker))
    assert any("desired_status" in expression for expression in _check_expressions(CrawlerRun))


def test_boss_crawl_task_exposes_generic_control_fields():
    from common.databases.models.boss_crawl_task import BossCrawlTask

    assert {
        "spider_name",
        "spider_args",
        "desired_status",
        "latest_run_id",
    } <= _column_names(BossCrawlTask)


@pytest.mark.parametrize(
    ("current_status", "command", "desired_status", "next_status"),
    [
        (None, "start", "running", "queued"),
        ("running", "pause", "paused", "pausing"),
        ("paused", "resume", "running", "queued"),
        ("running", "stop", "stopped", "stopping"),
        ("queued", "stop", "stopped", "stopped"),
        ("paused", "stop", "stopped", "stopped"),
        ("failed", "retry", "running", "queued"),
        ("stale", "retry", "running", "queued"),
        (None, "retry", "running", "queued"),
    ],
)
def test_crawler_run_state_machine(current_status, command, desired_status, next_status):
    from services.v2.crawler_control_service import transition_for_command

    transition = transition_for_command(current_status, command)

    assert transition.desired_status == desired_status
    assert transition.status == next_status


@pytest.mark.parametrize(
    ("current_status", "command"),
    [
        ("running", "start"),
        ("queued", "retry"),
        ("succeeded", "pause"),
        ("failed", "resume"),
    ],
)
def test_crawler_run_state_machine_rejects_invalid_transitions(current_status, command):
    from services.v2.crawler_control_service import (
        CrawlerTransitionError,
        transition_for_command,
    )

    with pytest.raises(CrawlerTransitionError):
        transition_for_command(current_status, command)


def test_crawler_metrics_keep_counters_monotonic_and_reserve_extra_dimensions():
    from services.v2.crawler_control_service import merge_run_metrics

    merged = merge_run_metrics(
        {
            "itemsScraped": 20,
            "pagesProcessed": 3,
            "errors": 2,
            "currentUrl": "page-3",
        },
        {
            "itemsScraped": 18,
            "pagesProcessed": 4,
            "responsesReceived": 9,
            "errors": 1,
            "captchaCount": 1,
            "currentUrl": "page-4",
        },
    )

    assert merged == {
        "itemsScraped": 20,
        "pagesProcessed": 4,
        "responsesReceived": 9,
        "errors": 2,
        "captchaCount": 1,
        "currentUrl": "page-4",
    }


def test_worker_online_status_uses_configured_stale_window():
    from services.v2.crawler_control_service import worker_is_online

    now = datetime(2026, 8, 5, 15, 0, tzinfo=timezone.utc)

    assert worker_is_online(now - timedelta(seconds=29), now=now, stale_seconds=30)
    assert not worker_is_online(now - timedelta(seconds=31), now=now, stale_seconds=30)


def test_worker_capacity_prevents_over_claiming_runs():
    from services.v2.crawler_control_service import worker_has_capacity

    assert worker_has_capacity(active_runs=0, max_concurrency=1)
    assert not worker_has_capacity(active_runs=1, max_concurrency=1)
    assert not worker_has_capacity(active_runs=3, max_concurrency=2)


def test_legacy_boss_task_timestamp_is_timezone_naive_for_existing_column():
    from services.v2.crawler_control_service import legacy_task_timestamp

    aware = datetime(2026, 8, 5, 15, 0, tzinfo=timezone.utc)
    converted = legacy_task_timestamp(aware)

    assert converted.tzinfo is None
    assert converted == datetime(2026, 8, 5, 15, 0)


def test_crawler_v2_schema_serializes_reserved_progress_fields_as_camel_case():
    from schemas.v2.crawler import CrawlerRunHeartbeat

    heartbeat = CrawlerRunHeartbeat(
        execution_token="token-123",
        status="running",
        pid=1234,
        metrics={"itemsScraped": 10, "customDimension": "reserved"},
        checkpoint={"page": 2},
    )

    payload = heartbeat.model_dump(by_alias=True)
    assert payload["executionToken"] == "token-123"
    assert payload["metrics"]["itemsScraped"] == 10
    assert payload["checkpoint"] == {"page": 2}


def test_v2_router_exposes_crawler_admin_and_agent_routes():
    from api.v2.api import api_router

    paths = {route.path for route in api_router.routes}
    assert {
        "/admin/crawlers/overview",
        "/admin/crawlers/workers",
        "/admin/crawlers/tasks",
        "/admin/crawlers/tasks/{task_id}/commands",
        "/admin/crawlers/runs/{run_id}",
        "/admin/crawlers/runs/{run_id}/events",
        "/crawler-agent/workers/heartbeat",
        "/crawler-agent/runs/claim",
        "/crawler-agent/runs/{run_id}/desired-state",
        "/crawler-agent/runs/{run_id}/heartbeat",
        "/crawler-agent/runs/{run_id}/events",
        "/crawler-agent/runs/{run_id}/finish",
    } <= paths


@pytest.mark.asyncio
async def test_crawler_admin_dependency_rejects_non_admin_users():
    from api.v2.endpoints.crawler_controller import require_crawler_admin

    with pytest.raises(HTTPException) as exc_info:
        await require_crawler_admin(SimpleNamespace(role="user"))
    assert exc_info.value.status_code == 403

    admin = SimpleNamespace(role="admin")
    assert await require_crawler_admin(admin) is admin


@pytest.mark.asyncio
async def test_crawler_agent_dependency_requires_configured_constant_time_token(monkeypatch):
    from api.v2.endpoints.crawler_agent_controller import require_crawler_agent
    from config import settings

    monkeypatch.setattr(settings, "CRAWLER_AGENT_TOKEN", "agent-secret")
    with pytest.raises(HTTPException) as exc_info:
        await require_crawler_agent("wrong-token")
    assert exc_info.value.status_code == 401

    assert await require_crawler_agent("agent-secret") is True

    monkeypatch.setattr(settings, "CRAWLER_AGENT_TOKEN", "")
    with pytest.raises(HTTPException) as disabled_info:
        await require_crawler_agent("agent-secret")
    assert disabled_info.value.status_code == 503


def test_crawler_agent_configuration_is_safe_by_default():
    from config import settings

    assert settings.CRAWLER_AGENT_DRY_RUN is True
    assert settings.CRAWLER_AGENT_HEARTBEAT_SECONDS >= 3
    assert settings.CRAWLER_AGENT_STALE_SECONDS > settings.CRAWLER_AGENT_HEARTBEAT_SECONDS
    assert "boss_list_drission" in settings.CRAWLER_AGENT_ALLOWED_SPIDERS

    from services.v2.crawler_control_service import crawler_control_service

    assert crawler_control_service.stale_seconds == settings.CRAWLER_AGENT_STALE_SECONDS


def test_crawler_run_arguments_always_reserve_the_task_url_for_remote_agent():
    from services.v2.crawler_control_service import spider_args_for_task

    task = SimpleNamespace(
        url="https://www.zhipin.com/web/geek/jobs?city=101210100",
        spider_args={"accountIndex": "2"},
    )

    assert spider_args_for_task(task) == {
        "accountIndex": "2",
        "taskUrl": task.url,
    }


def test_crawler_monitor_admin_views_are_read_only():
    from jobCollectionWebApi.admin.views.crawler import (
        CrawlerEventAdminView,
        CrawlerRunAdminView,
        CrawlerWorkerAdminView,
    )

    for view in (CrawlerWorkerAdminView, CrawlerRunAdminView, CrawlerEventAdminView):
        assert view.can_create is False
        assert view.can_edit is False
        assert view.can_delete is False


@pytest.mark.asyncio
async def test_legacy_admin_buttons_dispatch_to_remote_control_plane(monkeypatch):
    import jobCollectionWebApi.admin.views.crawler as crawler_admin

    calls = []

    class Session:
        async def commit(self):
            calls.append("commit")

    class SessionContext:
        async def __aenter__(self):
            return Session()

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    async def command_task(db, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(run_id="301", status="pausing")

    monkeypatch.setattr(crawler_admin.db_manager, "async_session", lambda: SessionContext())
    monkeypatch.setattr(crawler_admin.crawler_control_service, "command_task", command_task)
    request = SimpleNamespace(
        state=SimpleNamespace(user_obj=SimpleNamespace(id=1, username="admin")),
        client=SimpleNamespace(host="127.0.0.1"),
    )

    result = await crawler_admin.dispatch_crawler_control_command(
        request,
        task_id="201",
        command="pause",
    )

    assert calls[0]["task_id"] == 201
    assert calls[0]["command"] == "pause"
    assert calls[0]["actor"].username == "admin"
    assert calls[1] == "commit"
    assert result.run_id == "301"
