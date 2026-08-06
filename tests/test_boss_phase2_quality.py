import asyncio
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql


ROOT = Path(__file__).resolve().parents[1]


class _ScalarRows:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class _ExecuteResult:
    def __init__(self, values=()):
        self._values = values

    def scalars(self):
        return _ScalarRows(self._values)

    def all(self):
        return list(self._values)


class RecordingSession:
    def __init__(self):
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        compiled = statement.compile(dialect=postgresql.dialect())
        batch_size = sum(
            1 for key in compiled.params if key.startswith("source_key_m")
        )
        return _ExecuteResult([True] * batch_size)


def test_city_industry_generation_streams_373_by_145_in_fixed_batches():
    from jobCollection.jobCollection.boss.tasks import (
        SqlAlchemyTaskRepository,
        generate_city_industry_tasks,
    )

    class Repository(SqlAlchemyTaskRepository):
        async def list_city_level_codes(self):
            return [str(101000000 + index) for index in range(373)]

        async def list_boss_industry_leaf_codes(self):
            return [str(100000 + index) for index in range(145)]

    session = RecordingSession()
    stats = asyncio.run(generate_city_industry_tasks(Repository(session)))

    assert stats.expected == 54_085
    assert stats.created == 54_085
    assert len(session.statements) == 109
    batch_sizes = []
    for statement in session.statements:
        compiled = statement.compile(dialect=postgresql.dialect())
        batch_size = sum(
            1 for key in compiled.params if key.startswith("source_key_m")
        )
        batch_sizes.append(batch_size)
        assert batch_size <= 500
        # asyncpg limits one prepared statement to 32,767 bind parameters.
        assert len(compiled.params) < 32_767
    assert sum(batch_sizes) == 54_085


def test_task_upsert_refreshes_metadata_without_overwriting_runtime_status():
    from jobCollection.jobCollection.boss.tasks import (
        SqlAlchemyTaskRepository,
        build_city_industry_task_draft,
    )

    session = RecordingSession()
    repository = SqlAlchemyTaskRepository(session)
    asyncio.run(
        repository.upsert_task_drafts(
            iter([build_city_industry_task_draft("101010100", "100020")])
        )
    )

    sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    update_sql = sql.split("DO UPDATE SET", 1)[1]
    for column in (
        "url",
        "url_hash",
        "spider_args",
        "city_code",
        "industry_code",
        "priority",
    ):
        assert f"{column} = excluded.{column}" in update_sql
    assert "status =" not in update_sql
    assert "desired_status =" not in update_sql


def test_taxonomy_resolution_rejects_ambiguous_major_name_and_keeps_duplicate_leaf_paths():
    from jobCollection.jobCollection.boss.tasks import (
        parse_major_candidate,
        resolve_major_catalog_candidate,
    )

    candidate = parse_major_candidate("/web/geek/jobs?position=210108", "软件工程")
    draft = resolve_major_catalog_candidate(
        candidate,
        majors=[
            SimpleNamespace(id=1, code="080902", name="软件工程"),
            SimpleNamespace(id=2, code="080902T", name="软件工程"),
        ],
        position_types=[
            SimpleNamespace(id=11, code=210108, is_leaf=True, path="/1/210108"),
            SimpleNamespace(id=12, code=210108, is_leaf=True, path="/2/210108"),
        ],
    )

    assert draft.major_id is None
    assert draft.position_type_ids == (11, 12)
    assert "ambiguous major name: 软件工程" in draft.parse_error
    assert "unmatched position_type" not in draft.parse_error


def test_taxonomy_resolution_prefers_exact_major_code_over_ambiguous_name():
    from jobCollection.jobCollection.boss.tasks import (
        parse_major_candidate,
        resolve_major_catalog_candidate,
    )

    candidate = parse_major_candidate(
        "/web/geek/jobs?position=210108", "软件工程", "080902T"
    )
    draft = resolve_major_catalog_candidate(
        candidate,
        majors=[
            SimpleNamespace(id=1, code="080902", name="软件工程"),
            SimpleNamespace(id=2, code="080902T", name="软件工程"),
        ],
        position_types=[SimpleNamespace(id=11, code=210108, is_leaf=True)],
    )

    assert draft.major_id == 2
    assert draft.parse_error is None


def test_major_generation_never_schedules_unreconciled_legacy_identity():
    from jobCollection.jobCollection.boss.tasks import generate_major_tasks

    class Repository:
        def __init__(self):
            self.received = []

        async def list_major_urls(self):
            return [
                SimpleNamespace(
                    id=1,
                    major_id=10,
                    canonical_url="https://www.zhipin.com/web/geek/jobs?position=1",
                    is_active=True,
                    parse_error="legacy identity pending Phase2 canonicalization",
                ),
                SimpleNamespace(
                    id=2,
                    major_id=11,
                    canonical_url="https://www.zhipin.com/web/geek/jobs?position=2",
                    is_active=True,
                    parse_error=None,
                ),
            ]

        async def upsert_task_drafts(self, drafts):
            self.received = list(drafts)
            return len(self.received)

    repository = Repository()
    stats = asyncio.run(generate_major_tasks(repository))

    assert [draft.major_url_id for draft in repository.received] == [2]
    assert (stats.expected, stats.created, stats.existing, stats.disabled) == (1, 1, 0, 1)


def test_legacy_reconciliation_uses_application_canonicalizer_and_stable_survivor():
    from jobCollection.jobCollection.boss.tasks import (
        LEGACY_IDENTITY_PENDING,
        parse_major_candidate,
        plan_legacy_reconciliation,
    )

    candidate = parse_major_candidate(
        "/web/geek/jobs?position=2,1&experience=102", "软件工程"
    )
    rows = [
        SimpleNamespace(
            id=20,
            raw_url=(
                "https://www.zhipin.com/web/geek/jobs?"
                "ka=old&position=1,2&experience=102"
            ),
            url_hash="legacy-20",
            parse_error=LEGACY_IDENTITY_PENDING,
        ),
        SimpleNamespace(
            id=10,
            raw_url=(
                "https://www.zhipin.com/web/geek/jobs?"
                "experience=102&position=2,1&ka=older"
            ),
            url_hash="legacy-10",
            parse_error=LEGACY_IDENTITY_PENDING,
        ),
    ]

    plan = plan_legacy_reconciliation(rows, [candidate])

    assert plan.survivor_updates == {
        10: (candidate.canonical_url, candidate.url_hash)
    }
    assert plan.duplicate_to_survivor == {20: 10}
    assert plan.duplicate_hashes[20] != candidate.url_hash


def test_catalog_upsert_reports_created_from_returning_and_bulk_writes_relations():
    from jobCollection.jobCollection.boss.tasks import (
        MajorCatalogDraft,
        SqlAlchemyTaskRepository,
        parse_major_candidate,
    )

    class Session:
        def __init__(self):
            self.statements = []

        async def execute(self, statement):
            self.statements.append(statement)
            table = getattr(statement, "table", None)
            if table is not None and table.name == "boss_stu_crawl_urls":
                return _ExecuteResult(
                    [
                        (101, drafts[0].candidate.url_hash, True),
                        (102, drafts[1].candidate.url_hash, False),
                    ]
                )
            return _ExecuteResult()

    drafts = [
        MajorCatalogDraft(
            parse_major_candidate(f"/web/geek/jobs?position={code}", f"专业{code}"),
            major_id=None,
            position_type_ids=(position_id,),
            parse_error=None,
        )
        for code, position_id in (("1", 11), ("2", 12))
    ]
    session = Session()
    created = asyncio.run(
        SqlAlchemyTaskRepository(session).upsert_major_catalog(drafts, "fixture")
    )

    relation_inserts = [
        statement
        for statement in session.statements
        if getattr(getattr(statement, "table", None), "name", None)
        == "boss_stu_url_position"
        and getattr(statement, "is_insert", False)
    ]
    assert created == 1
    assert len(relation_inserts) == 1
    assert len(session.statements) <= 6


def test_redis_manager_import_is_safe_after_asyncio_run_clears_default_loop():
    """A prior synchronous async bridge must not make service imports fail."""

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import asyncio, sys; "
                f"sys.path.insert(0, {str(ROOT / 'jobCollectionWebApi')!r}); "
                "from common.databases.PostgresManager import db_manager; "
                "asyncio.run(asyncio.sleep(0)); "
                "from services.v2.crawler_control_service import "
                "crawler_control_service; "
                "assert crawler_control_service is not None"
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
