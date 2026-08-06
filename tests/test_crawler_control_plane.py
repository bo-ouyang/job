import importlib
import inspect
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


def test_crawler_migration_repairs_legacy_task_id_before_creating_run_fk(monkeypatch):
    migration_path = (
        ROOT / "alembic" / "versions" / "20260805_00_add_crawler_control_plane.py"
    )
    spec = importlib.util.spec_from_file_location("crawler_control_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    statements = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration._ensure_boss_crawl_task_id_key()

    ddl = str(statements[0])
    assert "pk_boss_crawl_task_control_plane" in ddl
    assert "PRIMARY KEY (id)" in ddl
    assert "GROUP BY id HAVING count(*) > 1" in ddl

    upgrade_source = inspect.getsource(migration.upgrade)
    assert upgrade_source.index("_ensure_boss_crawl_task_id_key()") < upgrade_source.index(
        '"crawler_runs"'
    )



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
        ("pausing", "resume"),
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


def test_boss_progress_counters_are_monotonic_across_late_agent_heartbeats():
    from services.v2.crawler_control_service import merge_run_metrics

    merged = merge_run_metrics(
        {
            "listSeenCount": 12,
            "jobsDiscovered": 10,
            "detailSuccessCount": 7,
            "detailFailedCount": 2,
        },
        {
            "listSeenCount": 3,
            "jobsDiscovered": 3,
            "detailSuccessCount": 1,
            "detailFailedCount": 0,
        },
    )

    assert merged == {
        "listSeenCount": 12,
        "jobsDiscovered": 10,
        "detailSuccessCount": 7,
        "detailFailedCount": 2,
    }


def test_agent_heartbeat_cannot_write_progress_authoritative_fact_metrics():
    from services.v2.crawler_control_service import merge_agent_heartbeat_metrics

    merged = merge_agent_heartbeat_metrics(
        {
            "itemsScraped": 8,
            "errors": 2,
            "jobsDiscovered": 10,
            "detailSuccessCount": 8,
            "detailFailedCount": 2,
            "retries": 4,
            "responsesReceived": 20,
        },
        {
            "itemsScraped": 999,
            "errors": 0,
            "jobsDiscovered": 999,
            "detailSuccessCount": 999,
            "detailFailedCount": 0,
            "retries": 0,
            "responsesReceived": 25,
            "elapsedSeconds": 30,
        },
    )

    assert merged == {
        "itemsScraped": 8,
        "errors": 2,
        "jobsDiscovered": 10,
        "detailSuccessCount": 8,
        "detailFailedCount": 2,
        "retries": 4,
        "responsesReceived": 25,
        "elapsedSeconds": 30,
    }


def test_late_agent_checkpoint_cannot_regress_durable_boss_progress():
    from services.v2.crawler_control_service import merge_run_checkpoint

    merged = merge_run_checkpoint(
        {
            "taskUrl": "https://example.invalid/jobs",
            "hasMore": False,
            "page": 4,
            "scrollRound": 9,
            "lastCompletedJobId": "job-9",
        },
        {
            "hasMore": True,
            "page": 2,
            "scrollRound": 3,
            "lastCompletedJobId": "job-3",
            "cursor": "resume-cursor",
        },
    )

    assert merged == {
        "taskUrl": "https://example.invalid/jobs",
        "hasMore": False,
        "page": 4,
        "scrollRound": 9,
        "lastCompletedJobId": "job-9",
        "cursor": "resume-cursor",
    }


@pytest.mark.parametrize(
    ("current", "desired", "reported", "expected"),
    [
        ("running", "paused", "running", "running"),
        ("pausing", "paused", "running", "pausing"),
        ("pausing", "paused", "paused", "paused"),
        ("stopping", "stopped", "running", "stopping"),
        ("succeeded", "stopped", "running", "succeeded"),
    ],
)
def test_late_heartbeat_cannot_move_a_run_backwards(
    current, desired, reported, expected
):
    from services.v2.crawler_control_service import heartbeat_run_status

    assert heartbeat_run_status(current, desired, reported) == expected


@pytest.mark.parametrize(
    ("current", "desired", "reported", "expected"),
    [
        ("pausing", "paused", "succeeded", "stopped"),
        ("stopping", "stopped", "succeeded", "stopped"),
        ("running", "stopped", "succeeded", "stopped"),
        ("running", "running", "succeeded", "succeeded"),
        ("pausing", "paused", "failed", "failed"),
    ],
)
def test_finish_cannot_report_success_over_control_plane_stop(
    current, desired, reported, expected
):
    from services.v2.crawler_control_service import finish_run_status

    assert finish_run_status(current, desired, reported) == expected


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


@pytest.mark.asyncio
async def test_terminal_command_locks_run_and_worker_before_releasing_capacity():
    from common.databases.models.boss_crawl_task import BossCrawlTask
    from common.databases.models.crawler_control import CrawlerRun, CrawlerWorker
    from services.v2.crawler_control_service import CrawlerControlService

    task = SimpleNamespace(
        id=201,
        latest_run_id=101,
        desired_status="paused",
        status="paused",
        last_crawl_time=None,
    )
    run = SimpleNamespace(
        id=101,
        task_id=201,
        status="paused",
        desired_status="paused",
        worker_id="worker-1",
        execution_token="token",
        pid=123,
        finished_at=None,
        heartbeat_at=None,
    )
    worker = SimpleNamespace(id="worker-1", active_runs=2)

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    class LockCheckingDb:
        def __init__(self):
            self.locked = []

        async def execute(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            assert statement._for_update_arg is not None
            self.locked.append(entity)
            return Result(
                {
                    BossCrawlTask: task,
                    CrawlerRun: run,
                    CrawlerWorker: worker,
                }[entity]
            )

        async def get(self, model, identity):
            raise AssertionError(f"unlocked get for {model.__name__}")

        def add(self, value):
            return None

        async def flush(self):
            return None

    db = LockCheckingDb()

    result = await CrawlerControlService().command_task(
        db,
        task_id=201,
        command="stop",
        actor=SimpleNamespace(id=1, username="admin"),
    )

    assert result.status == "stopped"
    assert db.locked[:3] == [BossCrawlTask, CrawlerRun, CrawlerWorker]
    assert worker.active_runs == 1


@pytest.mark.asyncio
async def test_resume_releases_previous_worker_capacity_once_and_fences_token():
    from common.databases.models.boss_crawl_task import BossCrawlTask
    from common.databases.models.crawler_control import CrawlerRun, CrawlerWorker
    from services.v2.crawler_control_service import CrawlerControlService

    task = SimpleNamespace(
        id=202,
        latest_run_id=102,
        desired_status="paused",
        status="paused",
        last_crawl_time=None,
    )
    run = SimpleNamespace(
        id=102,
        task_id=202,
        status="paused",
        desired_status="paused",
        worker_id="worker-2",
        execution_token="old-token",
        pid=321,
        finished_at=None,
        heartbeat_at=None,
    )
    worker = SimpleNamespace(id="worker-2", active_runs=1)

    class Result:
        def __init__(self, value): self.value = value
        def scalar_one_or_none(self): return self.value

    class LockCheckingDb:
        def __init__(self): self.locked = []
        async def execute(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            assert statement._for_update_arg is not None
            self.locked.append(entity)
            return Result({BossCrawlTask: task, CrawlerRun: run, CrawlerWorker: worker}[entity])
        def add(self, value): return None
        async def flush(self): return None

    db = LockCheckingDb()
    resumed_at = datetime(2026, 8, 6, 13, 0, tzinfo=timezone.utc)
    result = await CrawlerControlService(now=lambda: resumed_at).command_task(
        db, task_id=202, command="resume", actor=SimpleNamespace(id=1, username="admin")
    )
    assert result.status == "queued"
    assert run.worker_id is None
    assert run.execution_token is None
    assert run.heartbeat_at == resumed_at
    assert worker.active_runs == 0
    assert db.locked == [BossCrawlTask, CrawlerRun, CrawlerWorker]


@pytest.mark.asyncio
async def test_worker_heartbeat_does_not_regress_locked_active_run_fact():
    from common.databases.models.crawler_control import CrawlerWorker
    from schemas.v2.crawler import CrawlerWorkerHeartbeat
    from services.v2.crawler_control_service import CrawlerControlService

    worker = SimpleNamespace(
        id="worker-fact", name="old", hostname="old", platform="linux",
        status="online", capabilities={}, max_concurrency=2, active_runs=3,
        last_heartbeat_at=datetime.now(timezone.utc),
    )

    class Result:
        def scalar_one_or_none(self): return worker

    class Db:
        async def execute(self, statement):
            assert statement._for_update_arg is not None
            return Result()
        def add(self, value): return None
        async def flush(self): return None

    view = await CrawlerControlService().heartbeat_worker(
        Db(),
        CrawlerWorkerHeartbeat(
            worker_id="worker-fact", name="new", hostname="new", platform="linux",
            max_concurrency=2, active_runs=0, capabilities={"boss": True}
        ),
    )
    assert worker.active_runs == 3
    assert view.active_runs == 3


@pytest.mark.asyncio
async def test_new_worker_heartbeat_does_not_seed_client_reported_active_runs():
    from schemas.v2.crawler import CrawlerWorkerHeartbeat
    from services.v2.crawler_control_service import CrawlerControlService

    class Result:
        def scalar_one_or_none(self): return None

    class Db:
        async def execute(self, statement): return Result()
        def add(self, value): self.worker = value
        async def flush(self): return None

    db = Db()
    view = await CrawlerControlService().heartbeat_worker(
        db,
        CrawlerWorkerHeartbeat(
            worker_id="new-worker", name="new", hostname="new", platform="linux",
            max_concurrency=4, active_runs=32, capabilities={},
        ),
    )

    assert db.worker.active_runs == 0
    assert view.active_runs == 0


def test_crawler_sanitizer_preserves_fact_counter_names():
    from services.v2.crawler_control_service import sanitize_crawler_value

    sanitized = sanitize_crawler_value(
        {
            "responsesReceived": 12,
            "requestCount": 7,
            "response_body": "private-body",
            "requestHeaders": {"Cookie": "secret-cookie"},
            "accessToken": "secret-token",
        }
    )

    assert sanitized == {"responsesReceived": 12, "requestCount": 7}


def test_server_text_sanitizer_covers_naked_bearer_and_request_or_generic_body():
    from services.v2.crawler_control_service import sanitize_crawler_value

    values = sanitize_crawler_value(
        [
            "Bearer naked-secret",
            "request body: private-request",
            "body: private-generic",
            "The body is healthy and bearer plants grow here",
        ]
    )

    assert "naked-secret" not in values[0]
    assert "private-request" not in values[1]
    assert "private-generic" not in values[2]
    assert values[3] == "The body is healthy and bearer plants grow here"


@pytest.mark.asyncio
async def test_append_events_locks_run_and_rejects_terminal_execution():
    from schemas.v2.crawler import CrawlerEventBatch
    from services.v2.crawler_control_service import CrawlerControlService, CrawlerExecutionTokenError

    run = SimpleNamespace(id=303, worker_id="worker", execution_token="tok", status="succeeded")

    class Result:
        def scalar_one_or_none(self): return run

    class Db:
        async def execute(self, statement):
            assert statement._for_update_arg is not None
            return Result()
        def add(self, value): raise AssertionError("terminal run must not append")
        async def flush(self): raise AssertionError("terminal run must not flush")

    with pytest.raises(CrawlerExecutionTokenError, match="terminal"):
        await CrawlerControlService().append_events(
            Db(), run_id=303,
            batch=CrawlerEventBatch(execution_token="tok", events=[]),
        )


@pytest.mark.asyncio
async def test_append_events_sanitizes_sensitive_nested_payload_and_message():
    from schemas.v2.crawler import CrawlerEventBatch
    from services.v2.crawler_control_service import CrawlerControlService

    run = SimpleNamespace(id=304, worker_id="worker", execution_token="tok", status="running")
    captured = []

    class Result:
        def scalar_one_or_none(self): return run

    class Db:
        async def execute(self, statement):
            assert statement._for_update_arg is not None
            return Result()
        def add(self, value): captured.append(value)
        async def flush(self): return None

    payload = {
        "safe": {"value": "ok"},
        "Cookie": "session=secret",
        "headers": {"Authorization": "Bearer top-secret", "X": "visible"},
        "request": {"body": "raw-body", "url": "https://safe"},
        "proxy_credentials": "proxy-pass",
    }
    message = "x" * 3960 + " Authorization: bearer-secret"
    await CrawlerControlService().append_events(
        Db(), run_id=304,
        batch=CrawlerEventBatch(
            execution_token="tok",
            events=[{"event_type": "telemetry", "message": message, "payload": payload}],
        ),
    )
    event = captured[0]
    assert len(event.message) <= 4000
    rendered = str(event.payload).lower()
    assert "secret" not in rendered
    assert "authorization" not in rendered
    assert "proxy" not in rendered
    assert event.payload["safe"]["value"] == "ok"


@pytest.mark.asyncio
async def test_reconcile_stale_rechecks_locked_rows_before_marking_offline():
    from common.databases.models.boss_crawl_task import BossCrawlTask
    from common.databases.models.crawler_control import CrawlerRun, CrawlerWorker
    from services.v2.crawler_control_service import CrawlerControlService

    now = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
    worker = SimpleNamespace(
        id="worker-race", status="online", active_runs=1,
        last_heartbeat_at=now,  # became fresh before lock re-check
    )
    run = SimpleNamespace(
        id=401, task_id=501, worker_id="worker-race", status="running",
        desired_status="running", heartbeat_at=now, finished_at=None, pid=123,
        error_msg=None,
    )
    task = SimpleNamespace(id=501, latest_run_id=401)

    class Scalars:
        def __init__(self, values): self.values = values
        def all(self): return self.values
    class Result:
        def __init__(self, value=None, values=None): self.value, self.values = value, values
        def scalar_one_or_none(self): return self.value
        def scalars(self): return Scalars(self.values or [])
        def all(self): return self.values or []
    class Db:
        def __init__(self): self.calls = []
        async def execute(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            self.calls.append((entity, statement._for_update_arg is not None))
            if len(self.calls) == 1:
                return Result(values=["worker-race"])
            if len(self.calls) == 2:
                return Result(values=[(401, 501)])
            assert statement._for_update_arg is not None
            if entity is BossCrawlTask:
                return Result(value=task)
            if entity is CrawlerRun:
                return Result(value=run)
            return Result(value=worker)
        def add(self, value): raise AssertionError("fresh rows must remain unchanged")
        async def flush(self): return None

    service = CrawlerControlService(now=lambda: now, stale_seconds=45)
    result = await service.reconcile_stale(Db())
    assert result == {"workers_offline": 0, "runs_stale": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize("run_status", ["queued", "paused"])
async def test_reconcile_stale_never_terminates_non_executing_or_human_paused_runs(
    run_status,
):
    from common.databases.models.boss_crawl_task import BossCrawlTask
    from common.databases.models.crawler_control import CrawlerRun, CrawlerWorker
    from services.v2.crawler_control_service import CrawlerControlService

    now = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
    old = now - timedelta(minutes=5)
    worker = SimpleNamespace(
        id="worker-idle", status="online", active_runs=0, last_heartbeat_at=now,
    )
    run = SimpleNamespace(
        id=402, task_id=502, worker_id=None, status=run_status,
        desired_status="paused" if run_status == "paused" else "running",
        heartbeat_at=old, finished_at=None, pid=None, error_msg=None,
    )
    task = SimpleNamespace(id=502, latest_run_id=402)

    class Scalars:
        def __init__(self, values): self.values = values
        def all(self): return self.values
    class Result:
        def __init__(self, value=None, values=None): self.value, self.values = value, values
        def scalar_one_or_none(self): return self.value
        def scalars(self): return Scalars(self.values or [])
        def all(self): return self.values or []
    class Db:
        def __init__(self): self.calls = 0
        async def execute(self, statement):
            self.calls += 1
            if self.calls == 1:
                return Result(values=[])
            if self.calls == 2:
                # Simulate a row selected by the old broad ACTIVE status filter.
                return Result(values=[(run.id, run.task_id)])
            entity = statement.column_descriptions[0]["entity"]
            assert statement._for_update_arg is not None
            return Result(value={BossCrawlTask: task, CrawlerRun: run, CrawlerWorker: worker}[entity])
        def add(self, value): raise AssertionError("queued/paused run must remain unchanged")
        async def flush(self): return None

    result = await CrawlerControlService(now=lambda: now, stale_seconds=45).reconcile_stale(Db())

    assert result == {"workers_offline": 0, "runs_stale": 0}
    assert run.status == run_status


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
