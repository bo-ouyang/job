import importlib.util
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260721_01_add_agent_core_tables.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("agent_core_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _LegacyUsersInspector:
    def get_pk_constraint(self, table_name):
        assert table_name == "users"
        return {"name": None, "constrained_columns": []}


class _UsersIdStatsResult:
    def one(self):
        return (9, 9, 9)


class _LegacyUsersConnection:
    def execute(self, statement):
        assert "COUNT(DISTINCT id)" in str(statement)
        return _UsersIdStatsResult()


def test_upgrade_adds_users_primary_key_for_valid_legacy_table(monkeypatch):
    migration = _load_migration()
    primary_keys = []

    monkeypatch.setattr(migration.sa, "inspect", lambda bind: _LegacyUsersInspector())
    monkeypatch.setattr(migration.op, "get_bind", lambda: _LegacyUsersConnection())
    monkeypatch.setattr(
        migration.op,
        "create_primary_key",
        lambda name, table, columns: primary_keys.append((name, table, columns)),
    )
    monkeypatch.setattr(migration.op, "create_table", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "create_index", lambda *args, **kwargs: None)

    migration.upgrade()

    assert primary_keys == [("pk_users", "users", ["id"])]
