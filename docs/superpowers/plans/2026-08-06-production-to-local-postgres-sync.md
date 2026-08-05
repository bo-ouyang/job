# Production-to-Local PostgreSQL Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Boss industry and position taxonomy tables/data to production, then replace the local PostgreSQL schema and data with a verified production dump.

**Architecture:** Production PostgreSQL is the authoritative source. Both databases are backed up before mutation; the taxonomy migration and importer run on production first, then a fresh production custom-format dump is downloaded and restored into a newly recreated local `job` database. Verification compares Alembic head, table inventory, taxonomy counts, representative business-table counts, and taxonomy hierarchy integrity.

**Tech Stack:** PostgreSQL 15/18, `pg_dump`, `pg_restore`, Alembic, SQLAlchemy async, Paramiko/SFTP, PowerShell, Supervisor-managed FastAPI deployment.

---

### Task 1: Inventory and recoverable backups

**Files:**
- Read: `D:/Code/job/.env`
- Create: `D:/Code/job/.backups/db-sync-<timestamp>/local-before-sync.dump`
- Create remote: `/opt/job/backups/db-sync-<timestamp>/production-before-taxonomy.dump`

- [ ] **Step 1: Record local and production database versions**

Run read-only SQL for `version()`, current database, Alembic version, table count, and taxonomy table presence on both databases.

- [ ] **Step 2: Back up the local database**

Run `pg_dump -Fc` with the local values from `D:/Code/job/.env`, then run `pg_restore --list` and require a non-empty archive.

- [ ] **Step 3: Back up production before taxonomy changes**

Over SSH, load `/opt/job/.env.production`, run `pg_dump -Fc`, and validate it with `pg_restore --list` before continuing.

### Task 2: Install the production taxonomy schema and importer

**Files:**
- Upload: `alembic/versions/20260805_01_add_position_type.py`
- Upload: `common/databases/models/position_type.py`
- Upload: `common/databases/models/__init__.py`
- Upload: `common/databases/PostgresManager.py`
- Upload: `jobCollectionWebApi/scripts/__init__.py`
- Upload: `jobCollectionWebApi/scripts/import_boss_taxonomies.py`

- [ ] **Step 1: Upload only the taxonomy release files**

Preserve `/opt/job/.env*`, the virtual environment, uploads, frontend assets, and unrelated crawler files.

- [ ] **Step 2: Compile and migrate production**

Run `compileall`, validate the offline migration interval `20260805_00:20260805_01`, then run `alembic upgrade head`. Require the only head/current revision to be `20260805_01`.

- [ ] **Step 3: Execute the production importer**

Run `python -m jobCollectionWebApi.scripts.import_boss_taxonomies` with `ENVIRONMENT=production` and `PYTHONPATH=/opt/job`.

- [ ] **Step 4: Verify production taxonomy data**

Require 1292 `position_type` rows, levels `28/161/1103`, 1292 unique paths, 227 duplicate-code groups, zero orphan parents, and all 160 live industry source codes present.

### Task 3: Create and download the authoritative production dump

**Files:**
- Create remote: `/opt/job/backups/db-sync-<timestamp>/production-authoritative.dump`
- Create local: `D:/Code/job/.backups/db-sync-<timestamp>/production-authoritative.dump`

- [ ] **Step 1: Dump production after taxonomy import**

Run `pg_dump -Fc`, then validate the dump with `pg_restore --list` and record its byte size and SHA-256 hash.

- [ ] **Step 2: Download and verify the archive locally**

Download by SFTP and require the local SHA-256 to equal the remote hash before any local database deletion.

### Task 4: Replace local PostgreSQL from production

**Files:**
- Read: `D:/Code/job/.backups/db-sync-<timestamp>/production-authoritative.dump`

- [ ] **Step 1: Validate the destructive target**

Require local host `localhost` or `127.0.0.1`, database `job`, and a verified local backup before continuing. Refuse to drop `postgres`, `template0`, or `template1`.

- [ ] **Step 2: Terminate local connections and recreate `job`**

Connect to the local `postgres` maintenance database, terminate sessions for `job`, drop `job`, and recreate it with the configured local owner.

- [ ] **Step 3: Restore the production archive**

Run `pg_restore --exit-on-error --no-owner --no-privileges` into the newly created local database.

### Task 5: Cross-database verification

**Files:**
- Read: local and remote PostgreSQL catalogs

- [ ] **Step 1: Compare schema and representative row counts**

Compare Alembic revision, public table names, and counts for `jobs`, `users`, `companies`, `industries`, `position_type`, `agent_runs`, and crawler control tables.

- [ ] **Step 2: Verify taxonomy hierarchy locally**

Require the same `position_type` counts and zero orphan parents as production.

- [ ] **Step 3: Run application checks**

Run `pytest tests/test_boss_taxonomy_import.py -q`, compile the backend, and execute API/database health checks without starting a real crawler.

## Self-review

- Spec coverage: production taxonomy creation/import and authoritative production-to-local schema/data replacement are covered.
- Safety: both pre-change databases are backed up and validated; local deletion is gated by host/database checks and dump checksum equality.
- Scope: cluster roles and server-level PostgreSQL configuration are intentionally excluded; schema and data inside the `job` database are synchronized.
