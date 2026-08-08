from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260807_00_add_structured_message_notifications.py"
)

def test_message_notification_migration_uses_postgres_idempotent_ddl():
    """Baseline schemas may already contain these fields before Alembic reaches this revision."""
    rendered = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "information_schema.columns" in rendered
    assert "category" in rendered and "dedupe_key" in rendered
    assert "indnkeyatts = 1" in rendered
    assert "attname = 'dedupe_key'" in rendered
    assert "uq_messages_dedupe_key" in rendered
    assert "managed_by_alembic:20260807_00" in rendered
    assert "obj_description" in rendered
    assert "col_description" in rendered
    assert "DROP CONSTRAINT uq_messages_dedupe_key" in rendered
    assert "to_regclass" in rendered


def test_message_notification_model_leaves_dedupe_constraint_ownership_to_migration():
    model_source = (
        Path(__file__).parents[1]
        / "common"
        / "databases"
        / "models"
        / "message.py"
    ).read_text(encoding="utf-8")

    assert 'dedupe_key = Column(String(180), nullable=True)' in model_source
    assert 'dedupe_key = Column(String(180), nullable=True, unique=True)' not in model_source
    assert 'idx_messages_receiver_category_created' not in model_source
