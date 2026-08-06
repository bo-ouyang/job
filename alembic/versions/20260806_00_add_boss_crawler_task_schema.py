"""add task-oriented BOSS crawler schema

Revision ID: 20260806_00
Revises: 20260805_01
Create Date: 2026-08-06 10:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_00"
down_revision: Union[str, Sequence[str], None] = "20260805_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ACTIVE_RUN_STATES = "('queued', 'starting', 'running', 'pausing', 'paused', 'stopping')"


def _backfill_major_urls() -> None:
    """Use exactly the same deterministic legacy identity in every mode."""

    op.execute(_legacy_major_url_backfill_statement())


def _legacy_major_url_backfill_statement() -> sa.TextClause:
    """Backfill legacy rows without pretending they were newly canonicalized.

    Legacy identity is deliberately versioned as ``canonical_url = raw_url``.
    Phase 2 discovery uses the application canonicalizer and can reconcile
    these explicitly marked rows. Keeping this as one SQL statement makes
    online upgrades and rendered offline upgrades byte-for-byte reproducible.
    """

    return sa.text(
        r"""
        WITH legacy_row AS (
            SELECT source_row.*,
                   row_number() OVER (
                       PARTITION BY source_row.url ORDER BY source_row.id
                   ) AS identity_ordinal,
                   regexp_match(
                       source_row.url,
                       '(?:[?&])position=([^&#]*)'
                   ) AS position_match,
                   regexp_match(
                       source_row.url,
                       '(?:[?&])experience=([^&#]*)'
                   ) AS experience_match
              FROM boss_stu_crawl_urls AS source_row
        ),
        parsed_row AS (
            SELECT legacy_row.*,
                   coalesce(position_data.codes, '[]'::jsonb) AS parsed_codes,
                   coalesce(position_data.has_invalid_code, false) AS has_invalid_code,
                   major_data.match_count AS major_match_count,
                   major_data.matched_id AS matched_major_id,
                   major_data.matched_code AS matched_major_code
              FROM legacy_row
              LEFT JOIN LATERAL (
                  WITH distinct_position_code AS (
                        SELECT DISTINCT btrim(position_token) AS code
                          FROM regexp_split_to_table(
                              replace(
                                  replace(
                                      coalesce(legacy_row.position_match[1], ''),
                                      '%2C',
                                      ','
                                  ),
                                  '%2c',
                                  ','
                              ),
                              ','
                          ) AS position_token
                  )
                  SELECT (
                             SELECT jsonb_agg(code ORDER BY code::numeric)
                               FROM distinct_position_code
                              WHERE code ~ '^[0-9]+$'
                         ) AS codes,
                         EXISTS (
                             SELECT 1
                               FROM distinct_position_code
                              WHERE code <> '' AND code !~ '^[0-9]+$'
                         ) AS has_invalid_code
              ) AS position_data ON true
              LEFT JOIN LATERAL (
                  SELECT count(*) AS match_count,
                         min(major_match.id) AS matched_id,
                         min(major_match.code) AS matched_code
                    FROM majors AS major_match
                   WHERE nullif(btrim(legacy_row.major_name), '') IS NOT NULL
                     AND major_match.name = legacy_row.major_name
              ) AS major_data ON true
        )
        UPDATE boss_stu_crawl_urls AS target_row
           SET raw_url = parsed_row.url,
               canonical_url = parsed_row.url,
               url_hash = encode(
                   sha256(convert_to(
                       CASE
                           WHEN parsed_row.identity_ordinal = 1 THEN parsed_row.url
                           ELSE 'legacy-duplicate:' || parsed_row.id::text || ':' || parsed_row.url
                       END,
                       'UTF8'
                   )),
                   'hex'
               ),
               position_codes = (
                   SELECT coalesce(jsonb_agg(code ORDER BY code::numeric), '[]'::jsonb)
                     FROM jsonb_array_elements_text(parsed_row.parsed_codes) AS item(code)
                    WHERE code ~ '^[0-9]+$'
               ),
               experience_code = parsed_row.experience_match[1],
               major_id = CASE
                   WHEN parsed_row.major_match_count = 1 THEN parsed_row.matched_major_id
                   ELSE NULL
               END,
               major_code = CASE
                   WHEN parsed_row.major_match_count = 1 THEN parsed_row.matched_major_code
                   ELSE NULL
               END,
               first_seen_at = coalesce(parsed_row.created_at, now()),
               last_seen_at = coalesce(parsed_row.created_at, now()),
               parse_error = concat_ws(
                   '; ',
                   'legacy identity pending Phase2 canonicalization',
                   CASE WHEN parsed_row.identity_ordinal > 1
                        THEN 'duplicate legacy URL retained with deterministic identity'
                   END,
                   CASE WHEN parsed_row.has_invalid_code
                        THEN 'invalid non-numeric position code in legacy URL'
                   END,
                   CASE
                       WHEN nullif(btrim(parsed_row.major_name), '') IS NULL THEN NULL
                       WHEN parsed_row.major_match_count = 0
                           THEN 'major_name not found: ' || parsed_row.major_name
                       WHEN parsed_row.major_match_count > 1
                           THEN 'ambiguous major_name: ' || parsed_row.major_name
                   END
               )
          FROM parsed_row
         WHERE target_row.id = parsed_row.id
        """
    )


def _legacy_major_url_relation_backfill_statements() -> tuple[sa.TextClause, sa.TextClause]:
    """Populate normalized position relations and retain unmatched diagnostics."""

    return (
        sa.text(
            """
            INSERT INTO boss_stu_url_position (major_url_id, position_type_id)
            SELECT major_url.id, matched_position.id
              FROM boss_stu_crawl_urls AS major_url
              CROSS JOIN LATERAL jsonb_array_elements_text(
                  major_url.position_codes
              ) AS position_code(code)
              JOIN position_type AS matched_position
                ON matched_position.code::text = position_code.code
            ON CONFLICT DO NOTHING
            """
        ),
        sa.text(
        """
        UPDATE boss_stu_crawl_urls AS major_url
           SET parse_error = concat_ws(
               '; ',
               nullif(major_url.parse_error, ''),
               'position code not found: ' || missing_position.codes
           )
          FROM (
              SELECT source_url.id,
                     string_agg(
                         position_code.code,
                         ',' ORDER BY position_code.code::numeric
                     ) AS codes
                FROM boss_stu_crawl_urls AS source_url
                CROSS JOIN LATERAL jsonb_array_elements_text(
                    source_url.position_codes
                ) AS position_code(code)
               WHERE NOT EXISTS (
                   SELECT 1
                     FROM position_type AS known_position
                    WHERE known_position.code::text = position_code.code
               )
               GROUP BY source_url.id
          ) AS missing_position
         WHERE major_url.id = missing_position.id
        """
        ),
    )


def _drop_legacy_task_url_uniqueness_statement() -> sa.TextClause:
    """Find and drop any single-column URL unique constraint/index by shape."""

    return sa.text(
        """
        DO $$
        DECLARE
            target_table regclass := to_regclass('boss_crawl_task');
            item record;
        BEGIN
            FOR item IN
                SELECT constraint_row.conname
                  FROM pg_constraint AS constraint_row
                 WHERE constraint_row.conrelid = target_table
                   AND constraint_row.contype = 'u'
                   AND cardinality(constraint_row.conkey) = 1
                   AND EXISTS (
                       SELECT 1
                         FROM pg_attribute AS attribute_row
                        WHERE attribute_row.attrelid = target_table
                          AND attribute_row.attnum = constraint_row.conkey[1]
                          AND attribute_row.attname = 'url'
                   )
            LOOP
                EXECUTE format(
                    'ALTER TABLE %s DROP CONSTRAINT %I',
                    target_table,
                    item.conname
                );
            END LOOP;

            FOR item IN
                SELECT index_class.relname, namespace_row.nspname
                  FROM pg_index AS index_row
                  JOIN pg_class AS index_class
                    ON index_class.oid = index_row.indexrelid
                  JOIN pg_namespace AS namespace_row
                    ON namespace_row.oid = index_class.relnamespace
                 WHERE index_row.indrelid = target_table
                   AND index_row.indisunique
                   AND index_row.indnkeyatts = 1
                   AND NOT EXISTS (
                       SELECT 1
                         FROM pg_constraint AS owning_constraint
                        WHERE owning_constraint.conindid = index_row.indexrelid
                   )
                   AND EXISTS (
                       SELECT 1
                         FROM unnest(index_row.indkey) AS key_column(attnum)
                         JOIN pg_attribute AS attribute_row
                           ON attribute_row.attrelid = target_table
                          AND attribute_row.attnum = key_column.attnum
                        WHERE attribute_row.attname = 'url'
                   )
            LOOP
                EXECUTE format(
                    'DROP INDEX %I.%I',
                    item.nspname,
                    item.relname
                );
            END LOOP;
        END
        $$;
        """
    )


def _legacy_task_url_downgrade_guard_statement() -> sa.TextClause:
    """Abort before a legacy downgrade could truncate or collide URLs."""

    return sa.text(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM boss_crawl_task WHERE length(url) > 250) THEN
                RAISE EXCEPTION
                    'cannot downgrade: boss_crawl_task contains URL longer than 250 characters';
            END IF;
            IF EXISTS (
                SELECT 1
                  FROM boss_crawl_task
                 GROUP BY url HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade: boss_crawl_task contains duplicate URLs';
            END IF;
            IF EXISTS (
                SELECT 1 FROM boss_stu_crawl_urls WHERE length(url) > 255
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade: boss_stu_crawl_urls contains URL longer than 255 characters';
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    op.alter_column(
        "boss_stu_crawl_urls",
        "url",
        existing_type=sa.String(length=255),
        type_=sa.String(length=2048),
        existing_nullable=False,
    )
    for column in (
        sa.Column("major_id", sa.BigInteger(), nullable=True),
        sa.Column("major_code", sa.String(length=50), nullable=True),
        sa.Column("raw_url", sa.String(length=2048), nullable=True),
        sa.Column("canonical_url", sa.String(length=2048), nullable=True),
        sa.Column("url_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "position_codes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("experience_code", sa.String(length=30), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.Column("source_version", sa.String(length=64), nullable=True),
        sa.Column("parse_error", sa.Text(), nullable=True),
    ):
        op.add_column("boss_stu_crawl_urls", column)
    _backfill_major_urls()
    for column_name, column_type in (
        ("raw_url", sa.String(length=2048)),
        ("canonical_url", sa.String(length=2048)),
        ("url_hash", sa.String(length=64)),
        ("first_seen_at", sa.DateTime(timezone=True)),
        ("last_seen_at", sa.DateTime(timezone=True)),
    ):
        op.alter_column(
            "boss_stu_crawl_urls",
            column_name,
            existing_type=column_type,
            nullable=False,
        )
    op.create_foreign_key(
        "fk_boss_stu_crawl_urls_major",
        "boss_stu_crawl_urls",
        "majors",
        ["major_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_boss_stu_crawl_urls_url_hash",
        "boss_stu_crawl_urls",
        ["url_hash"],
    )
    op.create_index(
        "idx_boss_stu_major_active",
        "boss_stu_crawl_urls",
        ["major_id", "is_active"],
    )
    op.create_table(
        "boss_stu_url_position",
        sa.Column("major_url_id", sa.BigInteger(), nullable=False),
        sa.Column("position_type_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["major_url_id"],
            ["boss_stu_crawl_urls.id"],
            name="fk_boss_stu_url_position_major_url",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["position_type_id"],
            ["position_type.id"],
            name="fk_boss_stu_url_position_position_type",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "major_url_id",
            "position_type_id",
            name="pk_boss_stu_url_position",
        ),
    )
    for statement in _legacy_major_url_relation_backfill_statements():
        op.execute(statement)

    op.alter_column(
        "boss_crawl_task",
        "url",
        existing_type=sa.String(length=250),
        type_=sa.String(length=2048),
        existing_nullable=False,
    )
    op.add_column("boss_crawl_task", sa.Column("task_type", sa.String(30), nullable=True))
    op.add_column("boss_crawl_task", sa.Column("source_key", sa.String(255), nullable=True))
    op.add_column("boss_crawl_task", sa.Column("url_hash", sa.String(64), nullable=True))
    op.add_column("boss_crawl_task", sa.Column("major_url_id", sa.BigInteger(), nullable=True))
    op.add_column("boss_crawl_task", sa.Column("major_id", sa.BigInteger(), nullable=True))
    op.add_column("boss_crawl_task", sa.Column("city_code", sa.String(30), nullable=True))
    op.add_column("boss_crawl_task", sa.Column("industry_code", sa.String(30), nullable=True))
    op.add_column(
        "boss_crawl_task",
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "boss_crawl_task", sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("boss_crawl_task", sa.Column("error_code", sa.String(50), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE boss_crawl_task
               SET task_type = CASE
                     WHEN url LIKE '%position=%' AND url NOT LIKE '%industry=%'
                     THEN 'major'
                     ELSE 'city_industry'
                   END,
                   source_key = 'legacy:' || id::text,
                   url_hash = md5(url)
             WHERE task_type IS NULL OR source_key IS NULL OR url_hash IS NULL
            """
        )
    )
    op.alter_column("boss_crawl_task", "task_type", existing_type=sa.String(30), nullable=False)
    op.alter_column("boss_crawl_task", "source_key", existing_type=sa.String(255), nullable=False)
    op.alter_column("boss_crawl_task", "url_hash", existing_type=sa.String(64), nullable=False)
    op.execute(_drop_legacy_task_url_uniqueness_statement())
    op.create_check_constraint(
        "ck_boss_crawl_task_type",
        "boss_crawl_task",
        "task_type IN ('major', 'city_industry')",
    )
    op.create_check_constraint(
        "ck_boss_crawl_task_max_retries", "boss_crawl_task", "max_retries >= 0"
    )
    op.create_unique_constraint(
        "uq_boss_crawl_task_source_key", "boss_crawl_task", ["source_key"]
    )
    op.create_foreign_key(
        "fk_boss_crawl_task_major_url",
        "boss_crawl_task",
        "boss_stu_crawl_urls",
        ["major_url_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_boss_crawl_task_major",
        "boss_crawl_task",
        "majors",
        ["major_id"],
        ["id"],
        ondelete="SET NULL",
    )
    for name, columns in (
        ("ix_boss_crawl_task_url", ["url"]),
        ("idx_boss_crawl_url_hash", ["url_hash"]),
        ("ix_boss_crawl_task_major_url_id", ["major_url_id"]),
        ("ix_boss_crawl_task_major_id", ["major_id"]),
        ("ix_boss_crawl_task_city_code", ["city_code"]),
        ("ix_boss_crawl_task_industry_code", ["industry_code"]),
        ("ix_boss_crawl_task_next_retry_at", ["next_retry_at"]),
        ("ix_boss_crawl_task_error_code", ["error_code"]),
    ):
        op.create_index(name, "boss_crawl_task", columns, unique=False)

    op.create_table(
        "boss_crawler_account",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("profile_ref", sa.String(255), nullable=False),
        sa.Column("secret_ref", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="available"),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('available', 'in_use', 'cooldown', 'disabled')",
            name="ck_boss_crawler_account_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_boss_crawler_account_name"),
        sa.UniqueConstraint("profile_ref", name="uq_boss_crawler_account_profile_ref"),
        sa.UniqueConstraint("secret_ref", name="uq_boss_crawler_account_secret_ref"),
    )
    op.create_index(
        "idx_boss_crawler_account_status_cooldown",
        "boss_crawler_account",
        ["status", "cooldown_until"],
    )
    op.create_index("ix_boss_crawler_account_status", "boss_crawler_account", ["status"])

    op.add_column("crawler_runs", sa.Column("account_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "crawler_runs", sa.Column("proxy_identity_hash", sa.String(64), nullable=True)
    )
    op.create_foreign_key(
        "fk_crawler_run_account",
        "crawler_runs",
        "boss_crawler_account",
        ["account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_crawler_runs_account_id", "crawler_runs", ["account_id"])
    op.create_index(
        "ix_crawler_runs_proxy_identity_hash", "crawler_runs", ["proxy_identity_hash"]
    )
    op.create_index(
        "uq_crawler_run_active_account",
        "crawler_runs",
        ["account_id"],
        unique=True,
        postgresql_where=sa.text(
            f"account_id IS NOT NULL AND status IN {ACTIVE_RUN_STATES}"
        ),
    )
    op.create_index(
        "uq_crawler_run_active_proxy",
        "crawler_runs",
        ["proxy_identity_hash"],
        unique=True,
        postgresql_where=sa.text(
            f"proxy_identity_hash IS NOT NULL AND status IN {ACTIVE_RUN_STATES}"
        ),
    )

    op.create_table(
        "boss_crawl_run_job",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("encrypt_job_id", sa.String(100), nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=True),
        sa.Column("list_page", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("scroll_round", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("card_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detail_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("detail_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("detail_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "detail_status IN ('pending', 'processing', 'done', 'error')",
            name="ck_boss_crawl_run_job_detail_status",
        ),
        sa.CheckConstraint(
            "detail_attempts >= 0", name="ck_boss_crawl_run_job_detail_attempts"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["crawler_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["boss_crawl_task.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "encrypt_job_id",
            name="uq_boss_crawl_run_job_run_encrypt_job",
        ),
    )
    for name, columns in (
        ("idx_boss_crawl_run_job_run_status", ["run_id", "detail_status"]),
        ("idx_boss_crawl_run_job_task_status", ["task_id", "detail_status"]),
        ("ix_boss_crawl_run_job_run_id", ["run_id"]),
        ("ix_boss_crawl_run_job_task_id", ["task_id"]),
        ("ix_boss_crawl_run_job_encrypt_job_id", ["encrypt_job_id"]),
        ("ix_boss_crawl_run_job_job_id", ["job_id"]),
        ("ix_boss_crawl_run_job_detail_status", ["detail_status"]),
    ):
        op.create_index(name, "boss_crawl_run_job", columns)


def downgrade() -> None:
    op.execute(_legacy_task_url_downgrade_guard_statement())

    for name in (
        "ix_boss_crawl_run_job_detail_status",
        "ix_boss_crawl_run_job_job_id",
        "ix_boss_crawl_run_job_encrypt_job_id",
        "ix_boss_crawl_run_job_task_id",
        "ix_boss_crawl_run_job_run_id",
        "idx_boss_crawl_run_job_task_status",
        "idx_boss_crawl_run_job_run_status",
    ):
        op.drop_index(name, table_name="boss_crawl_run_job")
    op.drop_table("boss_crawl_run_job")

    op.drop_index("uq_crawler_run_active_proxy", table_name="crawler_runs")
    op.drop_index("uq_crawler_run_active_account", table_name="crawler_runs")
    op.drop_index("ix_crawler_runs_proxy_identity_hash", table_name="crawler_runs")
    op.drop_index("ix_crawler_runs_account_id", table_name="crawler_runs")
    op.drop_constraint("fk_crawler_run_account", "crawler_runs", type_="foreignkey")
    op.drop_column("crawler_runs", "proxy_identity_hash")
    op.drop_column("crawler_runs", "account_id")

    op.drop_index("ix_boss_crawler_account_status", table_name="boss_crawler_account")
    op.drop_index(
        "idx_boss_crawler_account_status_cooldown", table_name="boss_crawler_account"
    )
    op.drop_table("boss_crawler_account")

    for name in (
        "ix_boss_crawl_task_error_code",
        "ix_boss_crawl_task_next_retry_at",
        "ix_boss_crawl_task_industry_code",
        "ix_boss_crawl_task_city_code",
        "ix_boss_crawl_task_major_id",
        "ix_boss_crawl_task_major_url_id",
        "idx_boss_crawl_url_hash",
        "ix_boss_crawl_task_url",
    ):
        op.drop_index(name, table_name="boss_crawl_task")
    op.drop_constraint("fk_boss_crawl_task_major", "boss_crawl_task", type_="foreignkey")
    op.drop_constraint("fk_boss_crawl_task_major_url", "boss_crawl_task", type_="foreignkey")
    op.drop_constraint("uq_boss_crawl_task_source_key", "boss_crawl_task", type_="unique")
    op.drop_constraint("ck_boss_crawl_task_max_retries", "boss_crawl_task", type_="check")
    op.drop_constraint("ck_boss_crawl_task_type", "boss_crawl_task", type_="check")
    for column in (
        "error_code",
        "next_retry_at",
        "max_retries",
        "industry_code",
        "city_code",
        "major_id",
        "major_url_id",
        "url_hash",
        "source_key",
        "task_type",
    ):
        op.drop_column("boss_crawl_task", column)
    op.alter_column(
        "boss_crawl_task",
        "url",
        existing_type=sa.String(length=2048),
        type_=sa.String(length=250),
        existing_nullable=False,
        postgresql_using="url::varchar(250)",
    )
    op.create_unique_constraint(
        "boss_crawl_task_url_key", "boss_crawl_task", ["url"]
    )

    op.drop_table("boss_stu_url_position")
    op.drop_index("idx_boss_stu_major_active", table_name="boss_stu_crawl_urls")
    op.drop_constraint(
        "uq_boss_stu_crawl_urls_url_hash",
        "boss_stu_crawl_urls",
        type_="unique",
    )
    op.drop_constraint(
        "fk_boss_stu_crawl_urls_major",
        "boss_stu_crawl_urls",
        type_="foreignkey",
    )
    for column in (
        "parse_error",
        "source_version",
        "last_seen_at",
        "first_seen_at",
        "is_active",
        "experience_code",
        "position_codes",
        "url_hash",
        "canonical_url",
        "raw_url",
        "major_code",
        "major_id",
    ):
        op.drop_column("boss_stu_crawl_urls", column)
    op.alter_column(
        "boss_stu_crawl_urls",
        "url",
        existing_type=sa.String(length=2048),
        type_=sa.String(length=255),
        existing_nullable=False,
        postgresql_using="url::varchar(255)",
    )
