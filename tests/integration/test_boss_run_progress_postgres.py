"""Real PostgreSQL smoke for transactional BOSS run progress.

The test upgrades and writes only a random temporary schema.  ``public`` is
fingerprinted before and after the test and never receives fixture data.
"""

import asyncio
import importlib.util
import os
import uuid
from pathlib import Path
import sys

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from common.databases.PostgresManager import db_manager
from jobCollection.boss.parsers import BossJobDetail
from jobCollection.boss.progress import SqlAlchemyRunProgress
from jobCollection.boss.workflow import DetailFailure, WorkflowEvent
from jobCollection.boss.writer import BossJobWriter
from jobCollection.items.boss_job_item import BossJobDetailItem, BossJobItem


ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))
MIGRATION_PATH = (
    ROOT / "alembic" / "versions" / "20260806_00_add_boss_crawler_task_schema.py"
)
RUN_INTEGRATION = os.getenv("RUN_BOSS_CRAWLER_PG_INTEGRATION") == "1"


def _load_migration():
    name = f"boss_progress_pg_{uuid.uuid4().hex}"
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


@pytest.mark.asyncio
@pytest.mark.skipif(
    not RUN_INTEGRATION,
    reason="set RUN_BOSS_CRAWLER_PG_INTEGRATION=1 for PostgreSQL progress smoke",
)
async def test_transactional_run_progress_in_isolated_postgres_schema():
    migration = _load_migration()
    schema = f"boss_progress_test_{uuid.uuid4().hex[:12]}"
    quoted_schema = f'"{schema}"'
    engine = db_manager.engine
    transaction = None
    initial_fingerprint = None

    try:
        async with engine.connect() as connection:
            initial_fingerprint = await _public_fingerprint(connection)
            await connection.commit()
            transaction = await connection.begin()
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

            tables = (
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
            )
            for table_name in tables:
                await connection.execute(
                    text(
                        f"CREATE TABLE {quoted_schema}.\"{table_name}\" "
                        f"(LIKE public.\"{table_name}\" INCLUDING DEFAULTS "
                        "INCLUDING GENERATED INCLUDING IDENTITY)"
                    )
                )
                primary_column = "id"
                await connection.execute(
                    text(
                        f"ALTER TABLE {quoted_schema}.\"{table_name}\" "
                        f"ADD CONSTRAINT \"pk_progress_{table_name}\" "
                        f"PRIMARY KEY ({primary_column})"
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

            task_id = 8_300_000_000_000_000_001
            run_id = 8_300_000_000_000_000_002
            account_id = 8_300_000_000_000_000_003
            fixture = {
                "task_id": task_id,
                "run_id": run_id,
                "account_id": account_id,
                "url": "https://www.zhipin.com/web/geek/jobs?city=101010100&industry=100020",
                "hash": "a" * 64,
            }
            await connection.execute(
                text(
                    "INSERT INTO industries (id, code, name, level) "
                    "VALUES (8300000000000000004, 100020, 'Smoke industry', 1)"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO boss_crawl_task "
                    "(id, task_type, source_key, url, url_hash, status, priority, "
                    " spider_name, spider_args, desired_status) VALUES "
                    "(:task_id, 'city_industry', 'progress-smoke', :url, :hash, "
                    " 'running', 0, 'boss_list_drission', '{}'::jsonb, 'running')"
                ),
                fixture,
            )
            await connection.execute(
                text(
                    "INSERT INTO boss_crawler_account "
                    "(id, name, profile_ref, secret_ref, status) VALUES "
                    "(:account_id, 'smoke-account', 'profile://smoke', "
                    " 'secret://smoke', 'in_use')"
                ),
                fixture,
            )
            await connection.execute(
                text(
                    "INSERT INTO crawler_workers "
                    "(id, name, hostname, platform, status, max_concurrency, "
                    "active_runs, capabilities) VALUES "
                    "('worker-smoke', 'Smoke worker', 'localhost', 'test', "
                    "'online', 2, 2, '{}'::jsonb)"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO crawler_runs "
                    "(id, task_id, worker_id, account_id, proxy_identity_hash, spider_name, "
                    " spider_args, desired_status, status, metrics, checkpoint) VALUES "
                    "(:run_id, :task_id, 'worker-smoke', :account_id, 'proxy-smoke', "
                    " 'boss_list_drission', '{}'::jsonb, 'running', 'running', "
                    " '{}'::jsonb, '{}'::jsonb)"
                ),
                fixture,
            )
            await connection.execute(
                text(
                    "UPDATE crawler_runs SET execution_token='execution-smoke' "
                    "WHERE id=:run_id"
                ),
                fixture,
            )

            async def session_factory():
                return AsyncSession(bind=connection, expire_on_commit=False)

            writer = BossJobWriter(session_provider=session_factory)
            dispatched = []
            writer.dispatch_es_sync = dispatched.append
            progress = SqlAlchemyRunProgress(
                run_id=run_id,
                task_id=task_id,
                task_url=(
                    "https://www.zhipin.com/web/geek/jobs?"
                    "city=101010100&industry=100020"
                ),
                execution_token="execution-smoke",
                loop=asyncio.get_running_loop(),
                session_factory=session_factory,
                writer=writer,
                cooldown_seconds=60,
            )
            raw_job = {
                "encryptJobId": "pg-job-1",
                "jobName": "PostgreSQL smoke",
                "salaryDesc": "10-20K",
                "encryptBrandId": "pg-brand-1",
                "brandName": "Smoke company",
            }
            await asyncio.to_thread(
                progress.list_jobs_discovered,
                progress.task_url,
                (raw_job,),
                False,
            )
            await asyncio.to_thread(
                progress.list_jobs_discovered,
                progress.task_url,
                (raw_job,),
                False,
            )
            await asyncio.to_thread(
                progress.detail_succeeded,
                progress.task_url,
                "pg-job-1",
                BossJobDetail(
                    encrypt_job_id="pg-job-1",
                    description="Durable detail",
                    data={"encryptJobId": "pg-job-1", "skills": ["SQL"]},
                ),
            )
            await asyncio.to_thread(
                progress.detail_succeeded,
                progress.task_url,
                "pg-job-1",
                BossJobDetail(
                    encrypt_job_id="pg-job-1",
                    description="Durable detail",
                    data={"encryptJobId": "pg-job-1", "skills": ["SQL"]},
                ),
            )
            await asyncio.to_thread(
                progress.detail_failed,
                DetailFailure(progress.task_url, "pg-job-2", 3, "packet timeout"),
            )
            await asyncio.to_thread(
                progress.emit,
                WorkflowEvent("pause_required", progress.task_url, "captcha"),
            )
            await asyncio.to_thread(progress.close)

            placeholder_session = await session_factory()
            async with placeholder_session:
                async with placeholder_session.begin():
                    await writer.update_details(
                        placeholder_session,
                        [
                            BossJobDetailItem(
                                encrypt_job_id="pg-placeholder-job",
                                job_desc="Detail arrived first",
                                skills=["Python"],
                            )
                        ],
                    )
            list_session = await session_factory()
            async with list_session:
                async with list_session.begin():
                    await writer.upsert_jobs(
                        list_session,
                        [
                            BossJobItem(
                                encrypt_job_id="pg-placeholder-job",
                                job_name="Filled from list",
                                salary_desc="20-30K",
                                city_name="杭州",
                                area_district="西湖区",
                                business_district="文三路",
                                job_experience="3-5年",
                                job_degree="本科",
                                job_labels=["双休"],
                                welfare_list=["五险一金"],
                                encrypt_brand_id="pg-brand-filled",
                                brand_name="Filled company",
                                brand_logo="logo.png",
                                brand_scale_name="100-499人",
                                brand_stage_name="B轮",
                                brand_industry="互联网",
                                industry_code=100020,
                                city_code=101210100,
                                boss_name="招聘者",
                                boss_title="HR",
                                boss_avatar="avatar.png",
                            )
                        ],
                    )
                    # A later sparse list packet must not erase fields already
                    # populated by a richer packet or the detail response.
                    await writer.upsert_jobs(
                        list_session,
                        [
                            BossJobItem(
                                encrypt_job_id="pg-placeholder-job",
                                job_name="",
                                salary_desc="",
                            )
                        ],
                    )
            filled = (
                await connection.execute(
                    text(
                        "SELECT title, location, area_district, business_district, "
                        "experience, education, job_labels, welfare, company_id, "
                        "industry_id, industry_code, city_code, boss_name, boss_title, "
                        "boss_avatar, description, is_crawl FROM jobs "
                        "WHERE encrypt_job_id='pg-placeholder-job'"
                    )
                )
            ).mappings().one()
            assert filled["title"] == "Filled from list"
            assert filled["location"] == "杭州西湖区文三路"
            assert filled["area_district"] == "西湖区"
            assert filled["business_district"] == "文三路"
            assert filled["experience"] == "3-5年"
            assert filled["education"] == "本科"
            assert filled["job_labels"] == ["双休"]
            assert filled["welfare"] == ["五险一金"]
            assert filled["company_id"] is not None
            assert filled["industry_id"] is not None
            assert filled["industry_code"] == 100020
            assert filled["city_code"] == 101210100
            assert filled["boss_name"] == "招聘者"
            assert filled["boss_title"] == "HR"
            assert filled["boss_avatar"] == "avatar.png"
            assert filled["description"] == "Detail arrived first"
            assert filled["is_crawl"] == 1

            from schemas.v2.crawler import (
                CrawlerRunFinishRequest,
                CrawlerRunHeartbeat,
            )
            from services.v2.crawler_control_service import CrawlerControlService

            service = CrawlerControlService()
            service_session = AsyncSession(
                bind=connection, expire_on_commit=False
            )
            await service.heartbeat_run(
                service_session,
                run_id=run_id,
                heartbeat=CrawlerRunHeartbeat(
                    execution_token="execution-smoke",
                    status="running",
                    metrics={
                        "listSeenCount": 0,
                        "detailSuccessCount": 0,
                    },
                    checkpoint={
                        "hasMore": True,
                        "lastCompletedJobId": "stale-job",
                    },
                ),
            )
            paused_row = (
                await connection.execute(
                    text(
                        "SELECT status, metrics, checkpoint FROM crawler_runs "
                        "WHERE id=:run_id"
                    ),
                    {"run_id": run_id},
                )
            ).mappings().one()
            assert paused_row["status"] == "pausing"
            assert paused_row["metrics"]["detailSuccessCount"] == 1
            assert paused_row["checkpoint"]["lastCompletedJobId"] == "pg-job-1"

            finish = CrawlerRunFinishRequest(
                execution_token="execution-smoke",
                status="succeeded",
                exit_code=0,
                metrics={},
                checkpoint={},
            )
            await service.finish_run(service_session, run_id=run_id, payload=finish)
            await service.finish_run(service_session, run_id=run_id, payload=finish)
            await service.heartbeat_run(
                service_session,
                run_id=run_id,
                heartbeat=CrawlerRunHeartbeat(
                    execution_token="execution-smoke",
                    status="running",
                    metrics={},
                    checkpoint={},
                ),
            )
            assert (
                await connection.execute(
                    text(
                        "SELECT status FROM crawler_runs WHERE id=:run_id"
                    ),
                    {"run_id": run_id},
                )
            ).scalar_one() == "stopped"
            assert (
                await connection.execute(
                    text(
                        "SELECT active_runs FROM crawler_workers "
                        "WHERE id='worker-smoke'"
                    )
                )
            ).scalar_one() == 1

            run_row = (
                await connection.execute(
                    text(
                        "SELECT metrics, checkpoint, desired_status, status, "
                        "proxy_identity_hash FROM crawler_runs WHERE id=:run_id"
                    ),
                    {"run_id": run_id},
                )
            ).mappings().one()
            assert run_row["metrics"]["listSeenCount"] == 1
            assert run_row["metrics"]["detailSuccessCount"] == 1
            assert run_row["metrics"]["detailFailedCount"] == 1
            assert run_row["checkpoint"]["lastFailure"]["jobId"] == "pg-job-2"
            assert run_row["desired_status"] == "stopped"
            assert run_row["status"] == "stopped"
            assert run_row["proxy_identity_hash"] is None

            rows = (
                await connection.execute(
                    text(
                        "SELECT encrypt_job_id, detail_status, detail_attempts, "
                        "last_error FROM boss_crawl_run_job "
                        "WHERE run_id=:run_id ORDER BY encrypt_job_id"
                    ),
                    {"run_id": run_id},
                )
            ).all()
            assert rows == [
                ("pg-job-1", "done", 1, None),
                ("pg-job-2", "error", 3, "packet timeout"),
            ]
            assert (
                await connection.execute(
                    text("SELECT count(*) FROM jobs WHERE encrypt_job_id='pg-job-1'")
                )
            ).scalar_one() == 1
            assert (
                await connection.execute(
                    text(
                        "SELECT count(*) FROM crawler_events "
                        "WHERE run_id=:run_id AND event_type IN "
                        "('detail_failed', 'pause_required')"
                    ),
                    {"run_id": run_id},
                )
            ).scalar_one() == 2
            assert len(dispatched) == 4
    finally:
        if transaction is not None and transaction.is_active:
            await transaction.rollback()
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
