import importlib.util
import subprocess
import sys
from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, PrimaryKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable


ROOT = Path(__file__).parents[1]


def _load_migration(filename: str, module_name: str):
    migration_path = ROOT / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(module_name, migration_path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    return migration


def _column_names(model) -> set[str]:
    return set(model.__table__.columns.keys())


def _named_constraints(model, constraint_type) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, constraint_type)
    }


def test_major_url_catalog_has_canonical_identity_and_discovery_metadata():
    from common.databases.models.boss_stu_crawl_url import BossStuCrawlUrl

    assert {
        "major_id",
        "major_code",
        "raw_url",
        "canonical_url",
        "url_hash",
        "position_codes",
        "experience_code",
        "is_active",
        "first_seen_at",
        "last_seen_at",
        "source_version",
        "parse_error",
    } <= _column_names(BossStuCrawlUrl)
    assert BossStuCrawlUrl.__table__.c.raw_url.type.length >= 2048
    assert BossStuCrawlUrl.__table__.c.canonical_url.type.length >= 2048
    assert "uq_boss_stu_crawl_urls_url_hash" in _named_constraints(
        BossStuCrawlUrl, UniqueConstraint
    )
    foreign_keys = {
        (tuple(constraint.column_keys), tuple(element.target_fullname for element in constraint.elements))
        for constraint in BossStuCrawlUrl.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert (("major_id",), ("majors.id",)) in foreign_keys


def test_major_url_position_association_has_composite_identity_and_foreign_keys():
    from common.databases.models.boss_stu_crawl_url import BossStuUrlPosition

    assert BossStuUrlPosition.__tablename__ == "boss_stu_url_position"
    assert {"major_url_id", "position_type_id"} == _column_names(BossStuUrlPosition)
    primary_key = next(
        constraint
        for constraint in BossStuUrlPosition.__table__.constraints
        if isinstance(constraint, PrimaryKeyConstraint)
    )
    assert tuple(primary_key.columns.keys()) == ("major_url_id", "position_type_id")
    targets = {
        element.target_fullname
        for constraint in BossStuUrlPosition.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        for element in constraint.elements
    }
    assert targets == {"boss_stu_crawl_urls.id", "position_type.id"}

    ddl = str(CreateTable(BossStuUrlPosition.__table__).compile(dialect=postgresql.dialect()))
    assert "PRIMARY KEY (major_url_id, position_type_id)" in ddl
    assert "REFERENCES boss_stu_crawl_urls (id) ON DELETE CASCADE" in ddl
    assert "REFERENCES position_type (id) ON DELETE CASCADE" in ddl


def test_major_url_models_are_exported_from_shared_metadata():
    from common.databases import models

    assert models.BossStuCrawlUrl.__tablename__ == "boss_stu_crawl_urls"
    assert models.BossStuUrlPosition.__tablename__ == "boss_stu_url_position"
    assert {"BossStuCrawlUrl", "BossStuUrlPosition"} <= set(models.__all__)


def test_boss_crawl_task_has_stable_source_and_retry_fields():
    from common.databases.models.boss_crawl_task import BossCrawlTask

    assert {
        "task_type",
        "source_key",
        "url_hash",
        "major_url_id",
        "major_id",
        "city_code",
        "industry_code",
        "max_retries",
        "next_retry_at",
        "error_code",
        "spider_name",
        "spider_args",
        "desired_status",
        "latest_run_id",
    } <= _column_names(BossCrawlTask)
    assert BossCrawlTask.__table__.c.url.type.length >= 2048
    assert "uq_boss_crawl_task_source_key" in _named_constraints(
        BossCrawlTask, UniqueConstraint
    )
    assert "ck_boss_crawl_task_type" in _named_constraints(
        BossCrawlTask, CheckConstraint
    )


def test_boss_crawler_account_stores_only_profile_and_secret_references():
    from common.databases.models.boss_crawler_account import BossCrawlerAccount

    assert BossCrawlerAccount.__tablename__ == "boss_crawler_account"
    assert {
        "id",
        "name",
        "profile_ref",
        "secret_ref",
        "status",
        "cooldown_until",
        "last_used_at",
        "created_at",
        "updated_at",
    } <= _column_names(BossCrawlerAccount)
    assert {"cookie", "cookies", "password"}.isdisjoint(
        _column_names(BossCrawlerAccount)
    )
    assert "ck_boss_crawler_account_status" in _named_constraints(
        BossCrawlerAccount, CheckConstraint
    )
    assert "uq_boss_crawler_account_profile_ref" in _named_constraints(
        BossCrawlerAccount, UniqueConstraint
    )
    assert "uq_boss_crawler_account_name" in _named_constraints(
        BossCrawlerAccount, UniqueConstraint
    )


def test_crawler_run_reserves_accounts_and_proxy_identities_for_active_runs():
    from common.databases.models.crawler_control import CrawlerRun

    assert {"account_id", "proxy_identity_hash"} <= _column_names(CrawlerRun)

    indexes = {index.name: index for index in CrawlerRun.__table__.indexes}
    for name, column_name in (
        ("uq_crawler_run_active_account", "account_id"),
        ("uq_crawler_run_active_proxy", "proxy_identity_hash"),
    ):
        index = indexes[name]
        assert index.unique is True
        assert [column.name for column in index.columns] == [column_name]
        predicate = str(index.dialect_options["postgresql"]["where"])
        assert "status IN" in predicate
        assert "running" in predicate


def test_run_job_tracks_per_url_detail_progress_and_resume_position():
    from common.databases.models.boss_crawl_run_job import BossCrawlRunJob

    assert BossCrawlRunJob.__tablename__ == "boss_crawl_run_job"
    assert {
        "id",
        "run_id",
        "task_id",
        "encrypt_job_id",
        "job_id",
        "list_page",
        "scroll_round",
        "card_index",
        "detail_status",
        "detail_attempts",
        "last_error",
        "first_seen_at",
        "detail_completed_at",
        "updated_at",
    } <= _column_names(BossCrawlRunJob)
    assert "uq_boss_crawl_run_job_run_encrypt_job" in _named_constraints(
        BossCrawlRunJob, UniqueConstraint
    )
    assert "ck_boss_crawl_run_job_detail_status" in _named_constraints(
        BossCrawlRunJob, CheckConstraint
    )


def test_new_boss_crawler_models_are_exported_from_shared_metadata():
    from common.databases import models

    assert models.BossCrawlerAccount.__tablename__ == "boss_crawler_account"
    assert models.BossCrawlRunJob.__tablename__ == "boss_crawl_run_job"
    assert {"BossCrawlerAccount", "BossCrawlRunJob"} <= set(models.__all__)


def test_boss_crawler_schema_migration_follows_current_head():
    migration = _load_migration(
        "20260806_00_add_boss_crawler_task_schema.py", "boss_crawler_schema_migration"
    )

    assert migration.revision == "20260806_00"
    assert migration.down_revision == "20260805_01"


def test_legacy_major_url_backfill_uses_one_reproducible_sql_identity_path(monkeypatch):
    migration = _load_migration(
        "20260806_00_add_boss_crawler_task_schema.py", "boss_major_url_backfill"
    )

    class ExecuteOnlyOperations:
        def __init__(self):
            self.statements = []

        def execute(self, statement):
            self.statements.append(statement)

        def get_context(self):
            raise AssertionError("legacy backfill must not branch on online/offline mode")

        def get_bind(self):
            raise AssertionError("legacy backfill must not have a Python row path")

    operations = ExecuteOnlyOperations()
    monkeypatch.setattr(migration, "op", operations)

    migration._backfill_major_urls()

    assert len(operations.statements) == 1
    sql = str(operations.statements[0])
    assert "raw_url = parsed_row.url" in sql
    assert "canonical_url = parsed_row.url" in sql
    assert "legacy identity pending Phase2 canonicalization" in sql
    assert "pg_temp.canonicalize_boss_task_url" not in sql
    assert "row_number() OVER" in sql


def test_legacy_major_url_backfill_extracts_numeric_positions_and_diagnoses_gaps():
    migration = _load_migration(
        "20260806_00_add_boss_crawler_task_schema.py", "boss_major_url_relations"
    )

    identity_sql = str(migration._legacy_major_url_backfill_statement())
    relation_statements = migration._legacy_major_url_relation_backfill_statements()
    relation_sql = "\n".join(str(statement) for statement in relation_statements)

    assert len(relation_statements) == 2
    assert "^[0-9]+$" in identity_sql
    assert "position_codes" in identity_sql
    assert "experience_code" in identity_sql
    assert "major_match_count = 1" in identity_sql
    assert "ambiguous major_name" in identity_sql
    assert "INSERT INTO boss_stu_url_position" in relation_sql
    assert "position_type" in relation_sql
    assert "position code not found" in relation_sql


def test_url_uniqueness_removal_uses_postgresql_catalog_introspection():
    migration = _load_migration(
        "20260806_00_add_boss_crawler_task_schema.py", "boss_url_introspection"
    )

    sql = str(
        migration._drop_legacy_task_url_uniqueness_statement().compile(
            dialect=postgresql.dialect()
        )
    )

    assert "pg_constraint" in sql
    assert "pg_index" in sql
    assert "pg_attribute" in sql
    assert "contype = 'u'" in sql
    assert "indisunique" in sql
    assert "attname = 'url'" in sql
    assert "DROP CONSTRAINT" in sql
    assert "DROP INDEX" in sql


def test_downgrade_guard_rejects_long_or_duplicate_legacy_urls():
    migration = _load_migration(
        "20260806_00_add_boss_crawler_task_schema.py", "boss_url_downgrade_guard"
    )

    sql = str(
        migration._legacy_task_url_downgrade_guard_statement().compile(
            dialect=postgresql.dialect()
        )
    )

    assert "length(url) > 250" in sql
    assert "GROUP BY url HAVING count(*) > 1" in sql
    assert "RAISE EXCEPTION" in sql


def test_phase_one_downgrade_guards_before_changes_and_never_truncates(monkeypatch):
    migration = _load_migration(
        "20260806_00_add_boss_crawler_task_schema.py", "boss_safe_downgrade_operations"
    )

    class RecordingOperations:
        def __init__(self):
            self.calls = []

        def __getattr__(self, name):
            def record(*args, **kwargs):
                self.calls.append((name, args, kwargs))

            return record

    operations = RecordingOperations()
    monkeypatch.setattr(migration, "op", operations)

    migration.downgrade()

    first_name, first_args, _first_kwargs = operations.calls[0]
    assert first_name == "execute"
    assert "length(url) > 250" in str(first_args[0])
    url_alter = next(
        (args, kwargs)
        for name, args, kwargs in operations.calls
        if name == "alter_column" and args[:2] == ("boss_crawl_task", "url")
    )
    assert "left(" not in str(url_alter).lower()


def test_phase_one_upgrade_invokes_major_url_schema_and_non_unique_url_index(monkeypatch):
    migration = _load_migration(
        "20260806_00_add_boss_crawler_task_schema.py", "boss_phase_one_operations"
    )

    class Result:
        def mappings(self):
            return self

        def all(self):
            return []

    class Bind:
        def execute(self, *_args, **_kwargs):
            return Result()

    class RecordingOperations:
        def __init__(self):
            self.calls = []

        def get_bind(self):
            return Bind()

        def __getattr__(self, name):
            def record(*args, **kwargs):
                self.calls.append((name, args, kwargs))

            return record

    operations = RecordingOperations()
    monkeypatch.setattr(migration, "op", operations)

    migration.upgrade()

    added_major_columns = {
        args[1].name
        for name, args, _kwargs in operations.calls
        if name == "add_column" and args[0] == "boss_stu_crawl_urls"
    }
    assert {
        "major_id",
        "major_code",
        "raw_url",
        "canonical_url",
        "url_hash",
        "position_codes",
        "experience_code",
        "is_active",
        "first_seen_at",
        "last_seen_at",
        "source_version",
        "parse_error",
    } <= added_major_columns
    major_columns = {
        args[1].name: args[1]
        for name, args, _kwargs in operations.calls
        if name == "add_column" and args[0] == "boss_stu_crawl_urls"
    }
    for column_name in ("first_seen_at", "last_seen_at"):
        column = major_columns[column_name]
        assert column.server_default is not None
        assert "now()" in str(column.server_default.arg).lower()
    assert any(
        name == "create_table" and args[0] == "boss_stu_url_position"
        for name, args, _kwargs in operations.calls
    )
    assert any(
        name == "create_unique_constraint"
        and args[:2] == ("uq_boss_stu_crawl_urls_url_hash", "boss_stu_crawl_urls")
        for name, args, _kwargs in operations.calls
    )
    assert any(
        name == "create_index"
        and args[:3] == (
            "ix_boss_crawl_task_url",
            "boss_crawl_task",
            ["url"],
        )
        and kwargs.get("unique") is False
        for name, args, kwargs in operations.calls
    )


def test_position_type_downgrade_is_intentionally_non_destructive(monkeypatch):
    migration = _load_migration(
        "20260805_01_add_position_type.py", "position_type_safe_downgrade"
    )

    class FailOnOperation:
        def __getattr__(self, name):
            def fail(*_args, **_kwargs):
                raise AssertionError(f"downgrade must not call op.{name}")

            return fail

    monkeypatch.setattr(migration, "op", FailOnOperation())

    assert migration.downgrade() is None


def test_phase_one_incremental_migration_renders_executable_offline_sql():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "20260805_01:20260806_00",
            "--sql",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE boss_stu_url_position" in result.stdout
    assert "CONSTRAINT uq_boss_stu_crawl_urls_url_hash UNIQUE (url_hash)" in result.stdout
    assert "CREATE INDEX ix_boss_crawl_task_url" in result.stdout
    assert "UPDATE boss_stu_crawl_urls" in result.stdout
