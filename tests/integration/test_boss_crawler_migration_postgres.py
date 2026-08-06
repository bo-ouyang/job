"""PostgreSQL smoke test for the incremental BOSS crawler migration.

Run explicitly against a local PostgreSQL database whose ``public`` schema is
at Alembic revision ``20260805_01``::

    RUN_BOSS_CRAWLER_PG_INTEGRATION=1 \
      python -m pytest tests/integration/test_boss_crawler_migration_postgres.py -q

The test only reads table definitions from ``public``. All DDL and fixture data
are created in a random temporary schema and rolled back before a final cleanup
guard verifies that the schema no longer exists.
"""

from __future__ import annotations

import importlib.util
import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.databases.PostgresManager import db_manager


ROOT = Path(__file__).parents[2]
MIGRATION_PATH = (
    ROOT / "alembic" / "versions" / "20260806_00_add_boss_crawler_task_schema.py"
)
RUN_INTEGRATION = os.getenv("RUN_BOSS_CRAWLER_PG_INTEGRATION") == "1"


@pytest_asyncio.fixture(autouse=True)
async def _dispose_shared_engine_pool_after_test():
    """Do not carry asyncpg connections across pytest's per-test loops."""

    yield
    await db_manager.engine.dispose()


def _load_migration():
    module_name = f"boss_crawler_pg_smoke_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MIGRATION_PATH)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    return migration


def _run_upgrade(sync_connection, migration) -> None:
    """Run the migration with Alembic Operations on the current search_path."""

    original_operations = migration.op
    migration.op = Operations(MigrationContext.configure(sync_connection))
    try:
        migration.upgrade()
    finally:
        migration.op = original_operations


@pytest.mark.asyncio
@pytest.mark.skipif(
    not RUN_INTEGRATION,
    reason="set RUN_BOSS_CRAWLER_PG_INTEGRATION=1 to run PostgreSQL migration smoke",
)
async def test_boss_crawler_migration_upgrades_isolated_postgres_schema():
    migration = _load_migration()
    schema = f"boss_crawler_migration_test_{uuid.uuid4().hex[:12]}"
    quoted_schema = f'"{schema}"'
    engine = db_manager.engine
    transaction = None

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            revision = (
                await connection.execute(
                    text("SELECT version_num FROM public.alembic_version")
                )
            ).scalar_one()
            assert revision == "20260805_01", (
                "integration source schema must be at 20260805_01; "
                f"found {revision}"
            )

            await connection.execute(text(f"CREATE SCHEMA {quoted_schema}"))
            await connection.execute(
                text(f"SET LOCAL search_path TO {quoted_schema}, public")
            )
            assert (
                await connection.execute(text("SELECT current_schema()"))
            ).scalar_one() == schema

            legacy_tables = (
                "boss_stu_crawl_urls",
                "majors",
                "position_type",
                "boss_crawl_task",
                "crawler_runs",
                "jobs",
            )
            for table_name in legacy_tables:
                await connection.execute(
                    text(
                        f"CREATE TABLE {quoted_schema}.\"{table_name}\" "
                        f"(LIKE public.\"{table_name}\" "
                        "INCLUDING DEFAULTS INCLUDING GENERATED INCLUDING IDENTITY)"
                    )
                )
                await connection.execute(
                    text(
                        f"ALTER TABLE {quoted_schema}.\"{table_name}\" "
                        f"ADD CONSTRAINT \"pk_test_{table_name}\" PRIMARY KEY (id)"
                    )
                )

            # Reproduce the two legacy URL uniqueness shapes that the migration
            # must preserve (major URL) or replace (crawl task URL).
            await connection.execute(
                text(
                    f"ALTER TABLE {quoted_schema}.boss_stu_crawl_urls "
                    "ADD CONSTRAINT uq_test_boss_stu_url UNIQUE (url)"
                )
            )
            await connection.execute(
                text(
                    f"ALTER TABLE {quoted_schema}.boss_crawl_task "
                    "ADD CONSTRAINT uq_test_boss_task_url UNIQUE (url)"
                )
            )

            major_id = 9_100_000_000_000_000_001
            major_url_id = 9_100_000_000_000_000_002
            position_type_id = 9_100_000_000_000_000_003
            task_id = 9_100_000_000_000_000_004
            legacy_url = (
                "https://www.zhipin.com/web/geek/jobs?"
                "position=210108,999999&experience=102&ka=tracking"
            )
            await connection.execute(
                text(
                    f"INSERT INTO {quoted_schema}.majors "
                    "(id, name, code, parent_id, level, description) "
                    "VALUES (:id, 'Migration Smoke Major', 'SMOKE-01', NULL, 1, '')"
                ),
                {"id": major_id},
            )
            await connection.execute(
                text(
                    f"INSERT INTO {quoted_schema}.position_type "
                    "(id, code, name, level, path) "
                    "VALUES (:id, 210108, 'Migration Smoke Position', 2, '/smoke/210108/')"
                ),
                {"id": position_type_id},
            )
            await connection.execute(
                text(
                    f"INSERT INTO {quoted_schema}.boss_stu_crawl_urls "
                    "(id, url, major_name, status, created_at) "
                    "VALUES (:id, :url, 'Migration Smoke Major', 'pending', CURRENT_DATE)"
                ),
                {"id": major_url_id, "url": legacy_url},
            )
            await connection.execute(
                text(
                    f"INSERT INTO {quoted_schema}.boss_crawl_task "
                    "(id, url, status, spider_name, spider_args, desired_status) "
                    "VALUES (:id, :url, 'pending', 'boss_list_drission', "
                    "'{}'::jsonb, 'stopped')"
                ),
                {
                    "id": task_id,
                    "url": "https://www.zhipin.com/web/geek/jobs?"
                    "city=101010100&industry=100020",
                },
            )

            await connection.run_sync(_run_upgrade, migration)

            defaults = dict(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name, column_default "
                            "FROM information_schema.columns "
                            "WHERE table_schema = :schema "
                            "AND table_name = 'boss_stu_crawl_urls' "
                            "AND column_name IN ('first_seen_at', 'last_seen_at')"
                        ),
                        {"schema": schema},
                    )
                ).all()
            )
            assert defaults == {
                "first_seen_at": "now()",
                "last_seen_at": "now()",
            }

            legacy_row = (
                await connection.execute(
                    text(
                        f"SELECT raw_url, canonical_url, position_codes, "
                        f"major_id, major_code, parse_error "
                        f"FROM {quoted_schema}.boss_stu_crawl_urls WHERE id = :id"
                    ),
                    {"id": major_url_id},
                )
            ).mappings().one()
            assert legacy_row["raw_url"] == legacy_url
            assert legacy_row["canonical_url"] == legacy_url
            assert legacy_row["position_codes"] == ["210108", "999999"]
            assert legacy_row["major_id"] == major_id
            assert legacy_row["major_code"] == "SMOKE-01"
            assert "legacy identity pending Phase2 canonicalization" in legacy_row[
                "parse_error"
            ]
            assert "position code not found: 999999" in legacy_row["parse_error"]

            relation_rows = (
                await connection.execute(
                    text(
                        f"SELECT major_url_id, position_type_id "
                        f"FROM {quoted_schema}.boss_stu_url_position"
                    )
                )
            ).all()
            assert relation_rows == [(major_url_id, position_type_id)]

            inserted_id = 9_100_000_000_000_000_005
            inserted_hash = "f" * 64
            inserted_url = "https://www.zhipin.com/web/geek/jobs?position=210108"
            await connection.execute(
                text(
                    f"INSERT INTO {quoted_schema}.boss_stu_crawl_urls "
                    "(id, url, raw_url, canonical_url, url_hash, position_codes, "
                    "is_active, status) VALUES "
                    "(:id, :url, :url, :url, :url_hash, '[]'::jsonb, true, 'pending')"
                ),
                {
                    "id": inserted_id,
                    "url": inserted_url,
                    "url_hash": inserted_hash,
                },
            )
            inserted_times = (
                await connection.execute(
                    text(
                        f"SELECT first_seen_at, last_seen_at "
                        f"FROM {quoted_schema}.boss_stu_crawl_urls WHERE id = :id"
                    ),
                    {"id": inserted_id},
                )
            ).one()
            assert all(inserted_times)

            unique_savepoint = await connection.begin_nested()
            with pytest.raises(IntegrityError):
                await connection.execute(
                    text(
                        f"INSERT INTO {quoted_schema}.boss_stu_crawl_urls "
                        "(id, url, raw_url, canonical_url, url_hash, position_codes, "
                        "is_active, status) VALUES "
                        "(:id, :url, :url, :url, :url_hash, '[]'::jsonb, true, 'pending')"
                    ),
                    {
                        "id": 9_100_000_000_000_000_006,
                        "url": "https://www.zhipin.com/web/geek/jobs?position=210109",
                        "url_hash": inserted_hash,
                    },
                )
            await unique_savepoint.rollback()

            foreign_key_savepoint = await connection.begin_nested()
            with pytest.raises(IntegrityError):
                await connection.execute(
                    text(
                        f"UPDATE {quoted_schema}.boss_stu_crawl_urls "
                        "SET major_id = -1 WHERE id = :id"
                    ),
                    {"id": inserted_id},
                )
            await foreign_key_savepoint.rollback()
    finally:
        if transaction is not None and transaction.is_active:
            await transaction.rollback()

        # This guard runs even if the migration assertion fails. The schema name
        # is generated internally, so cleanup can never target ``public``.
        async with engine.begin() as cleanup_connection:
            schema_after_rollback = (
                await cleanup_connection.execute(
                    text("SELECT to_regnamespace(:schema)"), {"schema": schema}
                )
            ).scalar_one_or_none()
            if schema_after_rollback is not None:
                await cleanup_connection.execute(
                    text(f"DROP SCHEMA {quoted_schema} CASCADE")
                )
            assert schema_after_rollback is None, (
                "temporary schema survived transaction rollback and required cleanup"
            )


@pytest.mark.asyncio
@pytest.mark.skipif(
    not RUN_INTEGRATION,
    reason="set RUN_BOSS_CRAWLER_PG_INTEGRATION=1 to run PostgreSQL migration smoke",
)
async def test_major_catalog_reconciles_legacy_duplicate_with_unique_url_constraint():
    """A retained legacy UNIQUE(url) must not block canonical reconciliation."""

    from jobCollection.jobCollection.boss.tasks import (
        LEGACY_IDENTITY_PENDING,
        MajorCatalogDraft,
        SqlAlchemyTaskRepository,
        parse_major_candidate,
    )

    migration = _load_migration()
    schema = f"boss_major_reconcile_test_{uuid.uuid4().hex[:12]}"
    quoted_schema = f'"{schema}"'
    engine = db_manager.engine
    transaction = None

    survivor_id = 9_200_000_000_000_000_001
    duplicate_id = 9_200_000_000_000_000_002
    major_id = 9_200_000_000_000_000_003
    position_ids = (
        9_200_000_000_000_000_004,
        9_200_000_000_000_000_005,
    )
    candidate_raw_url = (
        "https://www.zhipin.com/web/geek/jobs?"
        "position=210108,210109&experience=102&ka=major_filter_test_click"
    )
    survivor_legacy_url = (
        "https://www.zhipin.com/web/geek/jobs?"
        "ka=legacy&experience=102&position=210109,210108"
    )
    candidate = parse_major_candidate(candidate_raw_url, "Integration Major", "SMOKE-02")
    draft = MajorCatalogDraft(
        candidate=candidate,
        major_id=major_id,
        position_type_ids=position_ids,
        parse_error=None,
    )

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(text(f"CREATE SCHEMA {quoted_schema}"))
            await connection.execute(
                text(f"SET LOCAL search_path TO {quoted_schema}, public")
            )

            for table_name in (
                "boss_stu_crawl_urls",
                "majors",
                "position_type",
                "boss_crawl_task",
                "crawler_runs",
                "jobs",
            ):
                await connection.execute(
                    text(
                        f"CREATE TABLE {quoted_schema}.\"{table_name}\" "
                        f"(LIKE public.\"{table_name}\" "
                        "INCLUDING DEFAULTS INCLUDING GENERATED INCLUDING IDENTITY)"
                    )
                )
                await connection.execute(
                    text(
                        f"ALTER TABLE {quoted_schema}.\"{table_name}\" "
                        f"ADD CONSTRAINT \"pk_test_{table_name}\" PRIMARY KEY (id)"
                    )
                )
            await connection.execute(
                text(
                    f"ALTER TABLE {quoted_schema}.boss_stu_crawl_urls "
                    "ADD CONSTRAINT uq_test_boss_stu_url UNIQUE (url)"
                )
            )

            await connection.execute(
                text(
                    f"INSERT INTO {quoted_schema}.majors "
                    "(id, name, code, parent_id, level, description) "
                    "VALUES (:id, 'Integration Major', 'SMOKE-02', NULL, 1, '')"
                ),
                {"id": major_id},
            )
            for position_id, code in zip(position_ids, (210108, 210109)):
                await connection.execute(
                    text(
                        f"INSERT INTO {quoted_schema}.position_type "
                        "(id, code, name, level, path) "
                        "VALUES (:id, :code, :name, 2, :path)"
                    ),
                    {
                        "id": position_id,
                        "code": code,
                        "name": f"Position {code}",
                        "path": f"/integration/{code}/",
                    },
                )
            await connection.execute(
                text(
                    f"INSERT INTO {quoted_schema}.boss_stu_crawl_urls "
                    "(id, url, major_name, status, created_at) VALUES "
                    "(:survivor_id, :survivor_url, 'Integration Major', "
                    "'pending', CURRENT_DATE), "
                    "(:duplicate_id, :duplicate_url, 'Integration Major', "
                    "'pending', CURRENT_DATE)"
                ),
                {
                    "survivor_id": survivor_id,
                    "survivor_url": survivor_legacy_url,
                    "duplicate_id": duplicate_id,
                    "duplicate_url": candidate_raw_url,
                },
            )

            await connection.run_sync(_run_upgrade, migration)
            # Split the relationships so successful reconciliation must merge
            # the duplicate's relation into the survivor before catalog refresh.
            await connection.execute(
                text(f"DELETE FROM {quoted_schema}.boss_stu_url_position")
            )
            await connection.execute(
                text(
                    f"INSERT INTO {quoted_schema}.boss_stu_url_position "
                    "(major_url_id, position_type_id) VALUES "
                    "(:survivor_id, :survivor_position_id), "
                    "(:duplicate_id, :duplicate_position_id)"
                ),
                {
                    "survivor_id": survivor_id,
                    "survivor_position_id": position_ids[0],
                    "duplicate_id": duplicate_id,
                    "duplicate_position_id": position_ids[1],
                },
            )

            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                repository = SqlAlchemyTaskRepository(session)
                assert await repository.upsert_major_catalog([draft], "integration-v1") == 0

                rows = (
                    await session.execute(
                        text(
                            f"SELECT id, url, raw_url, canonical_url, url_hash, "
                            f"is_active, parse_error "
                            f"FROM {quoted_schema}.boss_stu_crawl_urls ORDER BY id"
                        )
                    )
                ).mappings().all()
                assert len(rows) == 2
                survivor, duplicate = rows
                assert survivor["id"] == survivor_id
                assert survivor["url"] == candidate.raw_url
                assert survivor["raw_url"] == candidate.raw_url
                assert survivor["canonical_url"] == candidate.canonical_url
                assert survivor["url_hash"] == candidate.url_hash
                assert survivor["is_active"] is True
                assert LEGACY_IDENTITY_PENDING not in (survivor["parse_error"] or "")

                assert duplicate["id"] == duplicate_id
                assert duplicate["raw_url"] == candidate.raw_url
                assert duplicate["url"] != candidate.raw_url
                assert len(duplicate["url"]) <= 255
                assert str(duplicate_id) in duplicate["url"]
                assert duplicate["url_hash"] != candidate.url_hash
                assert duplicate["is_active"] is False
                assert "superseded by canonical discovery" in duplicate["parse_error"]

                relation_rows = (
                    await session.execute(
                        text(
                            f"SELECT major_url_id, position_type_id "
                            f"FROM {quoted_schema}.boss_stu_url_position "
                            f"WHERE major_url_id = :survivor_id "
                            f"ORDER BY position_type_id"
                        ),
                        {"survivor_id": survivor_id},
                    )
                ).all()
                assert relation_rows == [
                    (survivor_id, position_ids[0]),
                    (survivor_id, position_ids[1]),
                ]
                assert sum(bool(row["is_active"]) for row in rows) == 1

                # A repeat discovery is a no-op for identity and row count.
                assert await repository.upsert_major_catalog([draft], "integration-v1") == 0
                repeated_rows = (
                    await session.execute(
                        text(
                            f"SELECT id, url, raw_url, canonical_url, url_hash, "
                            f"is_active, parse_error "
                            f"FROM {quoted_schema}.boss_stu_crawl_urls ORDER BY id"
                        )
                    )
                ).mappings().all()
                assert repeated_rows == rows
    finally:
        if transaction is not None and transaction.is_active:
            await transaction.rollback()
        async with engine.begin() as cleanup_connection:
            if (
                await cleanup_connection.execute(
                    text("SELECT to_regnamespace(:schema)"), {"schema": schema}
                )
            ).scalar_one_or_none() is not None:
                await cleanup_connection.execute(
                    text(f"DROP SCHEMA {quoted_schema} CASCADE")
                )
