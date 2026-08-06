"""PostgreSQL concurrency regressions for crawler run/worker leases.

Every test owns a random schema.  The public schema is used only as a read-only
table template and migration baseline; fixture rows are never written there.
"""

import asyncio
from datetime import timedelta
import importlib.util
import json
import os
from pathlib import Path
import sys
import uuid

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from common.databases.PostgresManager import db_manager


ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))
MIGRATION_PATH = (
    ROOT / "alembic" / "versions" / "20260806_00_add_boss_crawler_task_schema.py"
)
RUN_INTEGRATION = os.getenv("RUN_BOSS_CRAWLER_PG_INTEGRATION") == "1"


def _load_migration():
    name = f"crawler_control_concurrency_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _upgrade(sync_connection, migration):
    original = migration.op
    migration.op = Operations(MigrationContext.configure(sync_connection))
    try:
        migration.upgrade()
    finally:
        migration.op = original


async def _public_fingerprint(connection):
    return (
        await connection.execute(
            text(
                "SELECT md5(coalesce(string_agg(identity, '|' ORDER BY identity), '')) "
                "FROM ("
                " SELECT table_name || ':' || column_name || ':' || data_type || ':' || "
                "        is_nullable || ':' || coalesce(column_default, '') AS identity "
                " FROM information_schema.columns WHERE table_schema = 'public'"
                ") AS public_shape"
            )
        )
    ).scalar_one()


@pytest_asyncio.fixture
async def crawler_control_schema():
    migration = _load_migration()
    schema = f"crawler_control_test_{uuid.uuid4().hex[:12]}"
    quoted_schema = f'"{schema}"'
    engine = db_manager.engine
    initial_fingerprint = None

    try:
        async with engine.begin() as connection:
            initial_fingerprint = await _public_fingerprint(connection)
            revision = (
                await connection.execute(
                    text("SELECT version_num FROM public.alembic_version")
                )
            ).scalar_one()
            assert revision == "20260805_01"
            await connection.execute(text(f"CREATE SCHEMA {quoted_schema}"))
            await connection.execute(
                text(f"SET LOCAL search_path TO {quoted_schema}, public")
            )
            for table_name in (
                "admin_logs",
                "boss_stu_crawl_urls",
                "majors",
                "position_type",
                "boss_crawl_task",
                "crawler_workers",
                "crawler_runs",
                "crawler_events",
                "industries",
                "company",
                "jobs",
            ):
                await connection.execute(
                    text(
                        f"CREATE TABLE {quoted_schema}.\"{table_name}\" "
                        f"(LIKE public.\"{table_name}\" INCLUDING DEFAULTS "
                        "INCLUDING GENERATED INCLUDING IDENTITY)"
                    )
                )
                await connection.execute(
                    text(
                        f"ALTER TABLE {quoted_schema}.\"{table_name}\" "
                        f"ADD CONSTRAINT \"pk_control_{table_name}\" PRIMARY KEY (id)"
                    )
                )
            for statement in (
                "ALTER TABLE boss_stu_crawl_urls ADD UNIQUE (url)",
                "ALTER TABLE boss_crawl_task ADD UNIQUE (url)",
                "ALTER TABLE industries ADD UNIQUE (code)",
                "ALTER TABLE company ADD UNIQUE (source_id)",
                "ALTER TABLE jobs ADD UNIQUE (encrypt_job_id)",
                "ALTER TABLE jobs ADD UNIQUE (source_url)",
            ):
                await connection.execute(text(statement))
            await connection.run_sync(_upgrade, migration)

        yield engine, schema
    finally:
        async with engine.begin() as cleanup:
            if (
                await cleanup.execute(
                    text("SELECT to_regnamespace(:schema)"), {"schema": schema}
                )
            ).scalar_one_or_none() is not None:
                await cleanup.execute(text(f"DROP SCHEMA {quoted_schema} CASCADE"))
            assert await _public_fingerprint(cleanup) == initial_fingerprint
            assert (
                await cleanup.execute(
                    text("SELECT to_regnamespace(:schema)"), {"schema": schema}
                )
            ).scalar_one_or_none() is None
        await engine.dispose()


async def _seed_active_run(
    engine,
    schema,
    *,
    run_status="running",
    desired_status="running",
    worker_active_runs=1,
    worker_stale=False,
    run_stale=False,
):
    values = {
        "task_id": 8_410_000_000_000_000_001,
        "run_id": 8_410_000_000_000_000_002,
        "url": "https://example.invalid/jobs?city=101010100&industry=100020",
        "hash": "c" * 64,
        "run_status": run_status,
        "desired_status": desired_status,
        "worker_active_runs": worker_active_runs,
        "worker_age": timedelta(minutes=5) if worker_stale else timedelta(),
        "run_age": timedelta(minutes=5) if run_stale else timedelta(),
    }
    async with engine.begin() as connection:
        await connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        await connection.execute(
            text(
                "INSERT INTO boss_crawl_task "
                "(id, task_type, source_key, url, url_hash, status, priority, "
                " spider_name, spider_args, desired_status) VALUES "
                "(:task_id, 'city_industry', 'concurrency-fixture', :url, :hash, "
                " :run_status, 0, 'boss_list_drission', '{}'::jsonb, :desired_status)"
            ),
            values,
        )
        await connection.execute(
            text(
                "INSERT INTO crawler_workers "
                "(id, name, hostname, platform, status, max_concurrency, active_runs, "
                " capabilities, last_heartbeat_at) VALUES "
                "('worker-concurrency', 'worker', 'localhost', 'test', 'online', 3, "
                " :worker_active_runs, '{}'::jsonb, now() - CAST(:worker_age AS interval))"
            ),
            values,
        )
        await connection.execute(
            text(
                "INSERT INTO crawler_runs "
                "(id, task_id, worker_id, spider_name, spider_args, desired_status, "
                " status, execution_token, metrics, checkpoint, heartbeat_at) VALUES "
                "(:run_id, :task_id, 'worker-concurrency', 'boss_list_drission', "
                " '{}'::jsonb, :desired_status, :run_status, 'old-token', '{}'::jsonb, "
                " '{}'::jsonb, now() - CAST(:run_age AS interval))"
            ),
            values,
        )
        await connection.execute(
            text(
                "UPDATE boss_crawl_task SET latest_run_id=:run_id WHERE id=:task_id"
            ),
            values,
        )
    return values


async def _set_search_path(session, schema):
    await session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    await session.execute(text("SET LOCAL lock_timeout = '4s'"))
    await session.execute(text("SET LOCAL statement_timeout = '8s'"))


@pytest.mark.asyncio
@pytest.mark.skipif(not RUN_INTEGRATION, reason="set RUN_BOSS_CRAWLER_PG_INTEGRATION=1")
async def test_old_finish_token_cannot_cross_a_committed_resume(crawler_control_schema):
    from schemas.v2.crawler import CrawlerRunFinishRequest
    from services.v2.crawler_control_service import (
        CrawlerControlService,
        CrawlerExecutionTokenError,
    )

    engine, schema = crawler_control_schema
    values = await _seed_active_run(
        engine,
        schema,
        run_status="paused",
        desired_status="paused",
    )
    service = CrawlerControlService()

    old_session = AsyncSession(bind=engine, expire_on_commit=False)
    resume_session = AsyncSession(bind=engine, expire_on_commit=False)
    try:
        old_tx = await old_session.begin()
        await _set_search_path(old_session, schema)
        cached = await service._authorized_run(
            old_session, values["run_id"], "old-token"
        )
        assert cached.status == "paused"

        async with resume_session.begin():
            await _set_search_path(resume_session, schema)
            await resume_session.execute(
                text(
                    "UPDATE crawler_workers SET active_runs=0 "
                    "WHERE id='worker-concurrency'"
                )
            )
            await resume_session.execute(
                text(
                    "UPDATE crawler_runs SET status='queued', desired_status='running', "
                    "worker_id=NULL, execution_token=NULL, pid=NULL, heartbeat_at=now() "
                    "WHERE id=:run_id"
                ),
                values,
            )

        with pytest.raises(CrawlerExecutionTokenError):
            await service.finish_run(
                old_session,
                run_id=values["run_id"],
                payload=CrawlerRunFinishRequest(
                    execution_token="old-token",
                    status="succeeded",
                    exit_code=0,
                    metrics={},
                    checkpoint={},
                ),
            )
        await old_tx.rollback()
    finally:
        await old_session.close()
        await resume_session.close()

    async with engine.connect() as check:
        await check.execute(text(f'SET search_path TO "{schema}", public'))
        row = (
            await check.execute(
                text(
                    "SELECT status, desired_status, worker_id, execution_token "
                    "FROM crawler_runs WHERE id=:run_id"
                ),
                values,
            )
        ).one()
        assert row == ("queued", "running", None, None)


@pytest.mark.asyncio
@pytest.mark.skipif(not RUN_INTEGRATION, reason="set RUN_BOSS_CRAWLER_PG_INTEGRATION=1")
async def test_two_connection_finish_is_idempotent_for_worker_capacity(crawler_control_schema):
    from schemas.v2.crawler import CrawlerRunFinishRequest
    from services.v2.crawler_control_service import CrawlerControlService

    engine, schema = crawler_control_schema
    values = await _seed_active_run(engine, schema, worker_active_runs=2)
    service = CrawlerControlService()
    payload = CrawlerRunFinishRequest(
        execution_token="old-token",
        status="succeeded",
        exit_code=0,
        metrics={},
        checkpoint={},
    )
    sessions = [AsyncSession(bind=engine, expire_on_commit=False) for _ in range(2)]
    transactions = []
    try:
        for session in sessions:
            transactions.append(await session.begin())
            await _set_search_path(session, schema)
            cached = await service._authorized_run(
                session, values["run_id"], "old-token"
            )
            assert cached.status == "running"

        async def finish(index):
            result = await service.finish_run(
                sessions[index], run_id=values["run_id"], payload=payload
            )
            await transactions[index].commit()
            return result

        results = await asyncio.wait_for(
            asyncio.gather(finish(0), finish(1)), timeout=10
        )
        assert [result.status for result in results] == ["succeeded", "succeeded"]
    finally:
        for transaction in transactions:
            if transaction.is_active:
                await transaction.rollback()
        for session in sessions:
            await session.close()

    async with engine.connect() as check:
        await check.execute(text(f'SET search_path TO "{schema}", public'))
        assert (
            await check.execute(
                text(
                    "SELECT active_runs FROM crawler_workers "
                    "WHERE id='worker-concurrency'"
                )
            )
        ).scalar_one() == 1


@pytest.mark.asyncio
@pytest.mark.skipif(not RUN_INTEGRATION, reason="set RUN_BOSS_CRAWLER_PG_INTEGRATION=1")
async def test_reconcile_and_finish_share_task_run_worker_lock_order(crawler_control_schema):
    from common.databases.models.boss_crawl_task import BossCrawlTask
    from common.databases.models.crawler_control import CrawlerRun
    from schemas.v2.crawler import CrawlerRunFinishRequest
    from services.v2.crawler_control_service import CrawlerControlService
    from sqlalchemy import select

    engine, schema = crawler_control_schema
    values = await _seed_active_run(
        engine, schema, worker_stale=True, run_stale=True
    )
    service = CrawlerControlService(stale_seconds=45)
    finish_session = AsyncSession(bind=engine, expire_on_commit=False)
    reaper_session = AsyncSession(bind=engine, expire_on_commit=False)
    finish_tx = await finish_session.begin()
    await _set_search_path(finish_session, schema)
    await finish_session.execute(
        select(BossCrawlTask)
        .where(BossCrawlTask.id == values["task_id"])
        .with_for_update()
    )
    await finish_session.execute(
        select(CrawlerRun)
        .where(CrawlerRun.id == values["run_id"])
        .with_for_update()
    )

    reaper_started = asyncio.Event()

    async def reap():
        async with reaper_session.begin():
            await _set_search_path(reaper_session, schema)
            reaper_started.set()
            return await service.reconcile_stale(reaper_session)

    reaper = asyncio.create_task(reap())
    try:
        await reaper_started.wait()
        # Condition polling: wait until reconciliation is blocked by the rows
        # deliberately held above.  No timing assumption is used to start finish.
        blocked = False
        for _ in range(100):
            async with engine.connect() as observer:
                waiting = (
                    await observer.execute(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE wait_event_type='Lock' "
                            "AND (query LIKE '%boss_crawl_task%' "
                            "OR query LIKE '%crawler_%')"
                        )
                    )
                ).scalar_one()
            if waiting:
                blocked = True
                break
            await asyncio.sleep(0.02)
        assert blocked, "reconciliation never reached the held task/run rows"

        await service.finish_run(
            finish_session,
            run_id=values["run_id"],
            payload=CrawlerRunFinishRequest(
                execution_token="old-token",
                status="succeeded",
                exit_code=0,
                metrics={},
                checkpoint={},
            ),
        )
        await finish_tx.commit()
        await asyncio.wait_for(reaper, timeout=10)
    finally:
        if finish_tx.is_active:
            await finish_tx.rollback()
        if not reaper.done():
            reaper.cancel()
            await asyncio.gather(reaper, return_exceptions=True)
        await finish_session.close()
        await reaper_session.close()


@pytest.mark.asyncio
@pytest.mark.skipif(not RUN_INTEGRATION, reason="set RUN_BOSS_CRAWLER_PG_INTEGRATION=1")
@pytest.mark.parametrize(
    ("worker_stale", "run_stale"),
    [(False, True), (True, False)],
)
async def test_reconcile_stale_atomically_ends_run_and_repairs_worker_slot(
    crawler_control_schema, worker_stale, run_stale
):
    from services.v2.crawler_control_service import CrawlerControlService

    engine, schema = crawler_control_schema
    values = await _seed_active_run(
        engine,
        schema,
        worker_active_runs=1,
        worker_stale=worker_stale,
        run_stale=run_stale,
    )
    service = CrawlerControlService(stale_seconds=45)
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        async with session.begin():
            await _set_search_path(session, schema)
            result = await service.reconcile_stale(session)

    async with engine.connect() as check:
        await check.execute(text(f'SET search_path TO "{schema}", public'))
        row = (
            await check.execute(
                text(
                    "SELECT r.status, r.worker_id, w.status, w.active_runs "
                    "FROM crawler_runs r CROSS JOIN crawler_workers w "
                    "WHERE r.id=:run_id AND w.id='worker-concurrency'"
                ),
                values,
            )
        ).one()
    assert row[0] == "stale"
    assert row[1] is None
    assert row[3] == 0
    assert result["runs_stale"] == 1
    assert (row[2] == "offline") is worker_stale


@pytest.mark.asyncio
@pytest.mark.skipif(not RUN_INTEGRATION, reason="set RUN_BOSS_CRAWLER_PG_INTEGRATION=1")
async def test_reconcile_does_not_lock_or_stale_a_queued_run_before_claim(
    crawler_control_schema,
):
    from common.databases.models.crawler_control import CrawlerRun
    from services.v2.crawler_control_service import CrawlerControlService
    from sqlalchemy import select

    engine, schema = crawler_control_schema
    values = await _seed_active_run(
        engine,
        schema,
        run_status="queued",
        desired_status="running",
        worker_active_runs=0,
        run_stale=True,
    )
    async with engine.begin() as connection:
        await connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        await connection.execute(
            text(
                "UPDATE crawler_runs SET worker_id=NULL, execution_token=NULL "
                "WHERE id=:run_id"
            ),
            values,
        )

    locker = AsyncSession(bind=engine, expire_on_commit=False)
    reaper = AsyncSession(bind=engine, expire_on_commit=False)
    try:
        locker_tx = await locker.begin()
        await _set_search_path(locker, schema)
        await locker.execute(
            select(CrawlerRun)
            .where(CrawlerRun.id == values["run_id"])
            .with_for_update()
        )

        async with reaper.begin():
            await _set_search_path(reaper, schema)
            result = await asyncio.wait_for(
                CrawlerControlService(stale_seconds=45).reconcile_stale(reaper),
                timeout=3,
            )
        assert result["runs_stale"] == 0
        await locker_tx.commit()

        async with AsyncSession(bind=engine, expire_on_commit=False) as claim_session:
            async with claim_session.begin():
                await _set_search_path(claim_session, schema)
                assignment = await CrawlerControlService().claim_run(
                    claim_session,
                    worker_id="worker-concurrency",
                    allowed_spiders=["boss_list_drission"],
                )
        assert assignment is not None
        assert int(assignment.run_id) == values["run_id"]
    finally:
        if 'locker_tx' in locals() and locker_tx.is_active:
            await locker_tx.rollback()
        await locker.close()
        await reaper.close()

    async with engine.connect() as check:
        await check.execute(text(f'SET search_path TO "{schema}", public'))
        assert (
            await check.execute(
                text("SELECT status FROM crawler_runs WHERE id=:run_id"), values
            )
        ).scalar_one() == "starting"


@pytest.mark.asyncio
@pytest.mark.skipif(not RUN_INTEGRATION, reason="set RUN_BOSS_CRAWLER_PG_INTEGRATION=1")
async def test_pause_ack_atomically_releases_worker_and_proxy_lease(
    crawler_control_schema,
):
    from schemas.v2.crawler import CrawlerRunHeartbeat
    from services.v2.crawler_control_service import CrawlerControlService

    engine, schema = crawler_control_schema
    values = await _seed_active_run(
        engine,
        schema,
        run_status="pausing",
        desired_status="paused",
        worker_active_runs=1,
    )
    async with engine.begin() as connection:
        await connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        await connection.execute(
            text(
                "UPDATE crawler_runs SET proxy_identity_hash='proxy-lease' "
                "WHERE id=:run_id"
            ),
            values,
        )

    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        async with session.begin():
            await _set_search_path(session, schema)
            response = await CrawlerControlService().heartbeat_run(
                session,
                run_id=values["run_id"],
                heartbeat=CrawlerRunHeartbeat(
                    execution_token="old-token",
                    status="paused",
                    metrics={},
                    checkpoint={"page": 3},
                ),
            )
            assert response.status == "paused"

    async with engine.connect() as check:
        await check.execute(text(f'SET search_path TO "{schema}", public'))
        row = (
            await check.execute(
                text(
                    "SELECT r.status, r.worker_id, r.execution_token, "
                    "r.proxy_identity_hash, w.active_runs "
                    "FROM crawler_runs r CROSS JOIN crawler_workers w "
                    "WHERE r.id=:run_id AND w.id='worker-concurrency'"
                ),
                values,
            )
        ).one()
    assert row == ("paused", None, None, None, 0)


@pytest.mark.asyncio
@pytest.mark.skipif(not RUN_INTEGRATION, reason="set RUN_BOSS_CRAWLER_PG_INTEGRATION=1")
async def test_agent_heartbeat_preserves_progress_fact_metrics_in_database(
    crawler_control_schema,
):
    from schemas.v2.crawler import CrawlerRunHeartbeat
    from services.v2.crawler_control_service import CrawlerControlService

    engine, schema = crawler_control_schema
    values = await _seed_active_run(engine, schema)
    async with engine.begin() as connection:
        await connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        await connection.execute(
            text(
                "UPDATE crawler_runs SET metrics=CAST(:initial_metrics AS jsonb) "
                "WHERE id=:run_id"
            ),
            {
                **values,
                "initial_metrics": json.dumps(
                    {
                        "itemsScraped": 8,
                        "errors": 2,
                        "jobsDiscovered": 10,
                        "detailSuccessCount": 8,
                        "detailFailedCount": 2,
                        "retries": 4,
                        "responsesReceived": 20,
                    }
                ),
            },
        )

    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        async with session.begin():
            await _set_search_path(session, schema)
            await CrawlerControlService().heartbeat_run(
                session,
                run_id=values["run_id"],
                heartbeat=CrawlerRunHeartbeat(
                    execution_token="old-token",
                    status="running",
                    metrics={
                        "itemsScraped": 999,
                        "errors": 0,
                        "jobsDiscovered": 999,
                        "detailSuccessCount": 999,
                        "detailFailedCount": 0,
                        "retries": 0,
                        "responsesReceived": 25,
                        "elapsedSeconds": 30,
                    },
                    checkpoint={},
                ),
            )

    async with engine.connect() as check:
        await check.execute(text(f'SET search_path TO "{schema}", public'))
        metrics = (
            await check.execute(
                text("SELECT metrics FROM crawler_runs WHERE id=:run_id"), values
            )
        ).scalar_one()
    assert metrics == {
        "itemsScraped": 8,
        "errors": 2,
        "jobsDiscovered": 10,
        "detailSuccessCount": 8,
        "detailFailedCount": 2,
        "retries": 4,
        "responsesReceived": 25,
        "elapsedSeconds": 30,
    }


@pytest.mark.asyncio
@pytest.mark.skipif(not RUN_INTEGRATION, reason="set RUN_BOSS_CRAWLER_PG_INTEGRATION=1")
async def test_finish_sanitizes_errors_checkpoint_and_preserves_fact_counters(
    crawler_control_schema,
):
    from schemas.v2.crawler import CrawlerRunFinishRequest
    from services.v2.crawler_control_service import CrawlerControlService

    engine, schema = crawler_control_schema
    values = await _seed_active_run(engine, schema)
    secret_error = (
        "Cookie: a=1; session=private Authorization: Bearer auth-secret "
        "response body: private-response"
    )
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        async with session.begin():
            await _set_search_path(session, schema)
            await CrawlerControlService().finish_run(
                session,
                run_id=values["run_id"],
                payload=CrawlerRunFinishRequest(
                    execution_token="old-token",
                    status="failed",
                    exit_code=1,
                    error_msg=secret_error,
                    metrics={
                        "responsesReceived": 9,
                        "requestCount": 7,
                        "accessToken": "metric-secret",
                    },
                    checkpoint={
                        "requestCount": 7,
                        "lastFailure": {"error": secret_error},
                    },
                ),
            )

    async with engine.connect() as check:
        await check.execute(text(f'SET search_path TO "{schema}", public'))
        run_row = (
            await check.execute(
                text(
                    "SELECT error_msg, metrics, checkpoint FROM crawler_runs "
                    "WHERE id=:run_id"
                ),
                values,
            )
        ).mappings().one()
        task_error = (
            await check.execute(
                text("SELECT error_msg FROM boss_crawl_task WHERE id=:task_id"),
                values,
            )
        ).scalar_one()

    rendered = str((run_row["error_msg"], run_row["checkpoint"], task_error))
    assert "private" not in rendered
    assert "auth-secret" not in rendered
    assert "metric-secret" not in str(run_row["metrics"])
    assert run_row["metrics"]["responsesReceived"] == 9
    assert run_row["metrics"]["requestCount"] == 7
    assert run_row["checkpoint"]["requestCount"] == 7
