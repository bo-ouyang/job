# Crawler Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不依赖有效 Boss Cookie 的前提下，实现可跨机器启动、暂停、恢复、停止和监控爬虫的后端控制面与独立 Crawler Agent，并为后续真实抓取量、页面数、错误数和日志监控预留稳定接口。

**Architecture:** PostgreSQL 是任务、运行、Worker 与事件的持久化事实源；FastAPI 提供管理员控制接口和 Agent 专用接口。Crawler Agent 运行在实际爬虫机器，通过 HTTPS 出站轮询领取运行、读取期望状态并上报心跳/指标/事件；默认 dry-run 模式模拟执行，因此没有 Cookie 也能验收完整控制链路。真实 Scrapy 进程只允许从白名单构造命令，并通过结构化遥测行把抓取统计交给 Agent。

**Tech Stack:** Python 3.10、FastAPI、Pydantic v2、SQLAlchemy 2 async、PostgreSQL、Alembic、Scrapy、httpx、Supervisor、pytest。

---

## File map

- Create `common/databases/models/crawler_control.py`: Worker、Run、Event 三个持久化模型。
- Modify `common/databases/models/boss_crawl_task.py`: 增加任务级爬虫名称、参数、期望状态和最近运行关联字段。
- Create `alembic/versions/20260805_00_add_crawler_control_plane.py`: 表、字段、索引和约束迁移。
- Create `jobCollectionWebApi/schemas/v2/crawler.py`: 管理端和 Agent 端的请求/响应契约。
- Create `jobCollectionWebApi/services/v2/crawler_control_service.py`: 状态机、原子领取、命令、心跳、指标和查询逻辑。
- Create `jobCollectionWebApi/api/v2/endpoints/crawler_controller.py`: 管理员控制接口。
- Create `jobCollectionWebApi/api/v2/endpoints/crawler_agent_controller.py`: 共享密钥保护的 Agent 接口。
- Modify `jobCollectionWebApi/api/v2/api.py`: 注册两组路由。
- Modify `jobCollectionWebApi/config.py` and `.env.example`: Agent 地址、Token、心跳、过期时间、轮询、dry-run 和爬虫白名单配置。
- Create `jobCollection/crawler_agent.py`: 可注入客户端和运行器的 Agent 主循环。
- Create `jobCollection/jobCollection/extensions/crawler_telemetry.py`: Scrapy 结构化指标输出。
- Modify `jobCollection/jobCollection/settings.py`: 注册遥测扩展。
- Modify `jobCollectionWebApi/admin/views/crawler.py` and `jobCollectionWebApi/admin/setup.py`: 后台展示 Worker、Run、Event。
- Create `tests/test_crawler_control_plane.py`: 后端模型、状态机、鉴权和路由测试。
- Create `tests/test_crawler_agent.py`: dry-run、命令处理、进度与进程命令白名单测试。
- Create `docs/爬虫控制与监控架构.md`: 配置、启动、接口、状态机与上线说明。

### Task 1: Persistent control-plane contract

**Files:**
- Create: `tests/test_crawler_control_plane.py`
- Create: `common/databases/models/crawler_control.py`
- Modify: `common/databases/models/boss_crawl_task.py`
- Modify: `common/databases/models/__init__.py`
- Create: `alembic/versions/20260805_00_add_crawler_control_plane.py`

- [ ] **Step 1: Write failing model contract tests**

Add tests asserting `CrawlerWorker`, `CrawlerRun`, and `CrawlerEvent` table names and required columns. Assert `BossCrawlTask` exposes `spider_name`, `spider_args`, `desired_status`, and `latest_run_id`.

- [ ] **Step 2: Run the model tests and verify RED**

Run: `pytest tests/test_crawler_control_plane.py -q`

Expected: import or assertion failures because the models do not exist.

- [ ] **Step 3: Implement the minimal models**

Use string statuses with database check constraints, JSONB for capabilities/metrics/checkpoints/payload, timezone-aware heartbeat timestamps, Snowflake IDs for runs/events, and a stable string ID for a configured Worker.

- [ ] **Step 4: Add the Alembic migration**

Set `revision = "20260805_00"` and `down_revision = "20260728_02"`. Add all tables, foreign keys, indexes, check constraints, and the four new `boss_crawl_task` columns. The downgrade must remove them in reverse dependency order.

- [ ] **Step 5: Run tests and migration checks**

Run: `pytest tests/test_crawler_control_plane.py -q && alembic heads`

Expected: model tests pass and the only head is `20260805_00`.

### Task 2: State machine and service boundary

**Files:**
- Modify: `tests/test_crawler_control_plane.py`
- Create: `jobCollectionWebApi/schemas/v2/crawler.py`
- Create: `jobCollectionWebApi/services/v2/crawler_control_service.py`

- [ ] **Step 1: Write failing pure state-machine tests**

Cover `start`, `pause`, `resume`, `stop`, and `retry`. Invalid transitions such as starting an already active task must raise `CrawlerTransitionError`. Test that progress counters are monotonic and arbitrary metric keys are retained under `metrics` for future extensions.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_crawler_control_plane.py -q`

Expected: missing service symbols.

- [ ] **Step 3: Implement schemas and pure transition helpers**

Define explicit `Literal` command/status types and camelCase V2 contracts. Implement `transition_for_command`, `merge_run_metrics`, and `worker_is_online` without database dependencies.

- [ ] **Step 4: Implement async service operations**

Implement administrator overview/list/detail, idempotent start, desired-state updates, Worker upsert, atomic `FOR UPDATE SKIP LOCKED` claim, run heartbeat, event append, finish, and stale Worker/run reconciliation. Every Agent mutation must require both `run_id` and `execution_token`.

- [ ] **Step 5: Verify GREEN**

Run: `pytest tests/test_crawler_control_plane.py -q`

Expected: all state and service-contract tests pass.

### Task 3: FastAPI administrator and Agent APIs

**Files:**
- Modify: `tests/test_crawler_control_plane.py`
- Create: `jobCollectionWebApi/api/v2/endpoints/crawler_controller.py`
- Create: `jobCollectionWebApi/api/v2/endpoints/crawler_agent_controller.py`
- Modify: `jobCollectionWebApi/api/v2/api.py`
- Modify: `jobCollectionWebApi/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Write failing route and authentication tests**

Assert all administrator and Agent route paths are registered. Assert non-admin users receive 403, a missing/incorrect `X-Crawler-Agent-Token` receives 401, and an empty server token disables Agent endpoints with 503.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_crawler_control_plane.py -q`

Expected: routes and dependencies are missing.

- [ ] **Step 3: Implement administrator routes**

Add overview, workers, tasks, task command, run detail, and cursor-based event list endpoints under `/api/v2/admin/crawlers`. Only `admin` and `super_admin` roles may access them, and commands must write `AdminLog` through the service.

- [ ] **Step 4: Implement Agent routes**

Add Worker heartbeat, run claim, desired-state query, run heartbeat, event batch, and finish endpoints under `/api/v2/crawler-agent`. Compare the shared token with `secrets.compare_digest`; never accept raw shell commands from Agent or administrator payloads.

- [ ] **Step 5: Add safe configuration defaults**

Add `CRAWLER_AGENT_TOKEN`, heartbeat/stale/poll values, API URL, Worker identity, maximum concurrency, `CRAWLER_AGENT_DRY_RUN=true`, and an explicit allowed-spider list to settings and `.env.example`.

- [ ] **Step 6: Verify GREEN**

Run: `pytest tests/test_crawler_control_plane.py -q`

Expected: route and authentication tests pass.

### Task 4: Cross-machine Crawler Agent

**Files:**
- Create: `tests/test_crawler_agent.py`
- Create: `jobCollection/crawler_agent.py`

- [ ] **Step 1: Write failing Agent tests**

Use injected fake control clients. Verify Worker registration, one-run-at-a-time claiming, dry-run progress heartbeat, pause acknowledgement, resume re-claim, stop completion, and backoff after API errors. Verify command construction rejects spiders outside the allowlist and never uses `shell=True`.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_crawler_agent.py -q`

Expected: Agent module is missing.

- [ ] **Step 3: Implement HTTP control client**

Use `httpx.Client` with bounded connect/read timeouts, `X-Crawler-Agent-Token`, JSON-only payloads, and no logging of Token/Cookie values.

- [ ] **Step 4: Implement dry-run execution**

Default dry-run must emit deterministic `itemsScraped`, `pagesProcessed`, `responsesReceived`, and elapsed-time metrics while remaining fully pause/resume/stop controllable. It must never open Chrome or contact Boss.

- [ ] **Step 5: Implement real subprocess execution boundary**

Build only `python -m scrapy crawl <allowlisted-spider> -a task_id=... -a task_url=...`. Start a new process group, capture stdout/stderr, parse only prefixed telemetry JSON, and implement graceful terminate followed by bounded forced kill.

- [ ] **Step 6: Implement the Agent loop and CLI entry point**

Send Worker heartbeat, claim when capacity is available, poll desired state, send progress/events, finalize exit status, and exponentially back off on control-plane outages without terminating a running local process.

- [ ] **Step 7: Verify GREEN**

Run: `pytest tests/test_crawler_agent.py -q`

Expected: all Agent lifecycle tests pass without network, Chrome, Cookie, or Scrapy execution.

### Task 5: Scrapy telemetry reservation

**Files:**
- Modify: `tests/test_crawler_agent.py`
- Create: `jobCollection/jobCollection/extensions/__init__.py`
- Create: `jobCollection/jobCollection/extensions/crawler_telemetry.py`
- Modify: `jobCollection/jobCollection/settings.py`

- [ ] **Step 1: Write failing telemetry serialization tests**

Verify item/page/response/error counters serialize as one bounded JSON line prefixed with `CRAWLER_EVENT ` and exclude request headers, cookies, response bodies, and arbitrary objects.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_crawler_agent.py -q`

Expected: telemetry extension is missing.

- [ ] **Step 3: Implement Scrapy signal extension**

Subscribe to `spider_opened`, `item_scraped`, `response_received`, `spider_error`, and `spider_closed`. Emit periodic progress and terminal events to stdout so the Agent can forward them without coupling spiders to backend credentials.

- [ ] **Step 4: Register the extension**

Add it to Scrapy `EXTENSIONS` with a low-priority numeric value. If `CRAWLER_RUN_ID` is absent, remain enabled for local metrics but use no sensitive run metadata.

- [ ] **Step 5: Verify GREEN**

Run: `pytest tests/test_crawler_agent.py -q`

Expected: serialization and Agent parsing tests pass.

### Task 6: Admin visibility and operational documentation

**Files:**
- Modify: `jobCollectionWebApi/admin/views/crawler.py`
- Modify: `jobCollectionWebApi/admin/setup.py`
- Create: `docs/爬虫控制与监控架构.md`

- [ ] **Step 1: Add read-only admin views**

Register Worker, Run, and Event views. Hide tokens and checkpoint payloads, prohibit create/edit/delete, and expose status, desired status, heartbeat, counters, exit code, and timestamps.

- [ ] **Step 2: Write the operator documentation**

Document dry-run setup, Agent startup command, Supervisor example, control API examples, state transition table, stale recovery, real Cookie activation boundary, metric names, and security rules.

- [ ] **Step 3: Verify documentation and imports**

Run: `python -m compileall -q common jobCollectionWebApi jobCollection && git diff --check`

Expected: no syntax or whitespace errors.

### Task 7: Full verification

**Files:**
- Test: `tests/test_crawler_control_plane.py`
- Test: `tests/test_crawler_agent.py`

- [ ] **Step 1: Run crawler-focused tests**

Run: `pytest tests/test_crawler_control_plane.py tests/test_crawler_agent.py -q`

Expected: all crawler tests pass.

- [ ] **Step 2: Run the full backend suite**

Run: `pytest tests -q`

Expected: existing API, Agent, billing, profile, market, and crawler tests all pass.

- [ ] **Step 3: Validate migration and route contract**

Run: `alembic heads && python -m compileall -q common jobCollectionWebApi jobCollection`

Expected: only `20260805_00` is the Alembic head and all modules compile.

- [ ] **Step 4: Run a local dry-run lifecycle smoke test**

Start the API against a migrated test database, run one Agent in dry-run mode, issue start → pause → resume → stop, and confirm Worker heartbeat, monotonic metrics, events, and final state. Do not start a real spider or access Boss.

## Self-review

- Spec coverage: cross-machine control, monitoring, future per-spider counts, Cookie-independent verification, security, recovery and deployment configuration are covered.
- Placeholder scan: no unspecified implementation steps or future TODO markers remain; real Cookie use is explicitly outside this scope and guarded by dry-run.
- Type consistency: administrator commands use `start/pause/resume/stop/retry`; run states and camelCase metric names are consistent across schemas, service, Agent and tests.
