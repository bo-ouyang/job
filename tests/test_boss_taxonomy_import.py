import sys
import importlib.util
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects import postgresql


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))


def _node(code, name, children=None, **overrides):
    data = {
        "code": code,
        "name": name,
        "tip": None,
        "subLevelModelList": children,
        "firstChar": None,
        "pinyin": None,
        "rank": 0,
        "mark": 11,
        "positionType": 3,
        "cityType": 0,
        "capital": 0,
        "color": None,
        "recruitmentType": "1,2,3",
        "cityCode": None,
        "regionCode": 0,
        "centerGeo": None,
        "value": None,
    }
    data.update(overrides)
    return data


def _industry_payload():
    return {
        "code": 0,
        "message": "Success",
        "zpData": [
            _node(
                100000,
                "互联网/AI",
                [
                    _node(100020, "互联网", None, positionType=0),
                    _node(100021, "计算机软件", None, positionType=0),
                ],
                positionType=0,
            )
        ],
    }


def _position_payload():
    repeated = _node(101313, "高性能计算工程师", None)
    return {
        "code": 0,
        "message": "Success",
        "zpData": {
            "position": [
                _node(
                    1010000,
                    "互联网/AI",
                    [
                        _node(1000020, "后端开发", [repeated]),
                        _node(1000130, "人工智能", [dict(repeated)]),
                    ],
                    positionType=0,
                )
            ]
        },
    }


def test_position_type_model_preserves_tree_paths_for_repeated_codes():
    from common.databases.models.position_type import PositionType

    assert PositionType.__tablename__ == "position_type"
    assert {
        "id",
        "code",
        "name",
        "parent_id",
        "parent_code",
        "level",
        "path",
        "sort_order",
        "source_payload",
    } <= set(PositionType.__table__.columns.keys())

    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in PositionType.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("path",) in unique_columns
    assert ("code",) not in unique_columns


def test_industry_payload_is_flattened_using_existing_zero_based_tree_contract():
    from jobCollectionWebApi.scripts.import_boss_taxonomies import parse_industries

    rows = parse_industries(_industry_payload())

    assert [(row["code"], row["level"], row["parent_id"], row["path"]) for row in rows] == [
        (100000, 0, None, "/100000/"),
        (100020, 1, 100000, "/100000/100020/"),
        (100021, 1, 100000, "/100000/100021/"),
    ]
    assert [row["rank"] for row in rows] == [0, 0, 1]


def test_position_payload_keeps_same_code_under_different_parent_paths():
    from jobCollectionWebApi.scripts.import_boss_taxonomies import parse_position_types

    rows = parse_position_types(_position_payload())
    repeated = [row for row in rows if row["code"] == 101313]

    assert len(rows) == 5
    assert len(repeated) == 2
    assert {row["parent_code"] for row in repeated} == {1000020, 1000130}
    assert {row["path"] for row in repeated} == {
        "/1010000/1000020/101313/",
        "/1010000/1000130/101313/",
    }
    assert {row["parent_path"] for row in repeated} == {
        "/1010000/1000020/",
        "/1010000/1000130/",
    }


@pytest.mark.parametrize(
    "payload, parser",
    [
        ({"code": 1, "message": "denied", "zpData": []}, "parse_industries"),
        ({"code": 0, "message": "Success", "zpData": {}}, "parse_industries"),
        ({"code": 0, "message": "Success", "zpData": []}, "parse_position_types"),
    ],
)
def test_invalid_boss_responses_fail_without_touching_the_database(payload, parser):
    from jobCollectionWebApi.scripts import import_boss_taxonomies as importer

    with pytest.raises(importer.TaxonomyImportError):
        getattr(importer, parser)(payload)


def test_source_url_uses_a_fresh_cache_buster():
    from jobCollectionWebApi.scripts.import_boss_taxonomies import (
        INDUSTRY_SOURCE_URL,
        POSITION_SOURCE_URL,
        build_source_url,
    )

    assert build_source_url(POSITION_SOURCE_URL, now_ms=1785933793811).endswith(
        "getCityShowPosition?_=1785933793811"
    )
    assert build_source_url(INDUSTRY_SOURCE_URL, now_ms=1785933793812).endswith(
        "industryFilterExemption?_=1785933793812"
    )


def test_position_records_resolve_parent_ids_without_merging_duplicate_codes():
    from jobCollectionWebApi.scripts.import_boss_taxonomies import (
        parse_position_types,
        prepare_position_records,
    )

    rows = parse_position_types(_position_payload())
    ids = iter(range(9001, 9100))
    records = prepare_position_records(rows, existing_ids={}, id_factory=lambda: next(ids))
    by_path = {record["path"]: record for record in records}

    assert by_path["/1010000/"]["parent_id"] is None
    assert by_path["/1010000/1000020/"]["parent_id"] == by_path["/1010000/"]["id"]
    assert (
        by_path["/1010000/1000020/101313/"]["parent_id"]
        == by_path["/1010000/1000020/"]["id"]
    )
    assert (
        by_path["/1010000/1000130/101313/"]["parent_id"]
        == by_path["/1010000/1000130/"]["id"]
    )
    assert "parent_path" not in by_path["/1010000/1000020/101313/"]


def test_import_statements_are_idempotent_on_source_keys():
    from jobCollectionWebApi.scripts.import_boss_taxonomies import (
        build_industry_upsert,
        build_position_upsert,
        parse_industries,
        parse_position_types,
        prepare_position_records,
    )

    industry_sql = str(
        build_industry_upsert(parse_industries(_industry_payload())).compile(
            dialect=postgresql.dialect()
        )
    )
    position_rows = prepare_position_records(
        parse_position_types(_position_payload()),
        existing_ids={},
        id_factory=iter(range(8001, 9000)).__next__,
    )
    position_sql = str(
        build_position_upsert(position_rows).compile(dialect=postgresql.dialect())
    )

    assert "ON CONFLICT (code) DO UPDATE" in industry_sql
    assert "ON CONFLICT (path) DO UPDATE" in position_sql


def test_position_type_migration_accepts_a_table_created_by_the_script(monkeypatch):
    migration_path = ROOT / "alembic" / "versions" / "20260805_01_add_position_type.py"
    spec = importlib.util.spec_from_file_location("position_type_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)

    create_table_calls = []
    create_index_calls = []
    monkeypatch.setattr(
        migration.op,
        "create_table",
        lambda *args, **kwargs: create_table_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        migration.op,
        "create_index",
        lambda *args, **kwargs: create_index_calls.append((args, kwargs)),
    )

    migration.upgrade()

    assert create_table_calls[0][1]["if_not_exists"] is True
    assert all(kwargs["if_not_exists"] is True for _args, kwargs in create_index_calls)


def test_position_type_migration_can_render_offline_sql():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "20260805_00:20260805_01",
            "--sql",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE IF NOT EXISTS position_type" in result.stdout


@pytest.mark.asyncio
async def test_database_write_serializes_concurrent_taxonomy_imports():
    from jobCollectionWebApi.scripts.import_boss_taxonomies import (
        parse_industries,
        parse_position_types,
        write_taxonomies,
    )

    class Result:
        def all(self):
            return []

    class Session:
        def __init__(self):
            self.statements = []

        async def execute(self, statement):
            self.statements.append(statement)
            return Result()

    session = Session()
    await write_taxonomies(
        session,
        industry_rows=parse_industries(_industry_payload()),
        position_rows=parse_position_types(_position_payload()),
        id_factory=iter(range(7001, 8000)).__next__,
    )

    assert "pg_advisory_xact_lock" in str(session.statements[0])
    assert "INSERT INTO industries" in str(session.statements[1])
    assert "SELECT position_type.path" in str(session.statements[2])
    assert "INSERT INTO position_type" in str(session.statements[3])
