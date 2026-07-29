# API V2 Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在完整保留 `/api/v1` 的前提下，为前端 V2 建立独立、可演进、可报告数据缺口的 `/api/v2` 接口。

**Architecture:** `/api/v2` 使用独立 Router、Pydantic 响应契约和页面聚合 Service，底层复用现有 CRUD、AnalysisService、CareerProfile、钱包及 Agent 运行时。所有聚合响应携带 `dataStatus`，已有数据库字段返回真实统计，缺失指标返回空值并登记到统一数据缺口注册表，供后续爬虫和数据任务消费。

**Tech Stack:** FastAPI、Pydantic v2、SQLAlchemy Async、PostgreSQL、可选 Elasticsearch、Pytest、Vue/Axios

---

### Task 1: V2 Router 与公共响应契约

**Files:**
- Create: `jobCollectionWebApi/api/v2/__init__.py`
- Create: `jobCollectionWebApi/api/v2/api.py`
- Create: `jobCollectionWebApi/api/v2/endpoints/meta_controller.py`
- Create: `jobCollectionWebApi/schemas/v2/common.py`
- Modify: `jobCollectionWebApi/config.py`
- Modify: `jobCollectionWebApi/main.py`
- Test: `tests/test_v2_api_contracts.py`

- [ ] **Step 1: Write failing route contract tests**

```python
def test_v2_router_exposes_meta_and_market_routes():
    paths = {route.path for route in api_router.routes}
    assert "/meta/data-gaps" in paths
    assert "/market/dashboard" in paths
```

- [ ] **Step 2: Run the test and verify RED**

Run: `pytest tests/test_v2_api_contracts.py -q`

Expected: FAIL because `api.v2` does not exist.

- [ ] **Step 3: Implement V2 router and configuration**

```python
class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    API_V2_STR: str = "/api/v2"
```

`main.py` includes both routers. V1 imports and prefixes remain unchanged.

- [ ] **Step 4: Verify route tests pass**

Run: `pytest tests/test_v2_api_contracts.py -q`

Expected: PASS with both V1 and V2 route trees present.

### Task 2: Data-gap registry

**Files:**
- Create: `jobCollectionWebApi/services/data_gap_registry.py`
- Create: `docs/DATA_GAPS_FOR_CRAWLER.md`
- Test: `tests/test_v2_data_gaps.py`

- [ ] **Step 1: Write a failing registry test**

```python
def test_registry_contains_crawler_actionable_fields():
    gap = get_gap("market.monthly_job_trend")
    assert gap.owner == "crawler"
    assert gap.source_fields
    assert gap.refresh_frequency == "daily"
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_v2_data_gaps.py -q`

Expected: FAIL because the registry does not exist.

- [ ] **Step 3: Implement typed registry and public metadata**

Each gap includes `key`, `module`, `description`, `required_fields`, `source_fields`, `refresh_frequency`, `priority`, `owner`, and `status`. The initial registry covers monthly trends, normalized skill frequencies, city competition, talent shortage, salary percentiles/history, and source coverage.

- [ ] **Step 4: Verify registry tests pass**

Run: `pytest tests/test_v2_data_gaps.py -q`

Expected: PASS and `/api/v2/meta/data-gaps` returns only non-sensitive metadata.

### Task 3: Market dashboard V2

**Files:**
- Create: `jobCollectionWebApi/schemas/v2/market.py`
- Create: `jobCollectionWebApi/services/v2/market_dashboard_service.py`
- Create: `jobCollectionWebApi/api/v2/endpoints/market_controller.py`
- Test: `tests/test_v2_market_dashboard.py`

- [ ] **Step 1: Write failing transformation and source tests**

```python
async def test_dashboard_uses_real_stats_and_reports_missing_dimensions():
    service = MarketDashboardService(stats_loader=fake_postgres_stats)
    result = await service.get_dashboard(MarketDashboardQuery())
    assert result.kpis[0].value == 120
    assert result.data_status.source == "postgresql"
    assert "market.monthly_job_trend" in result.data_status.missing_dimensions
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_v2_market_dashboard.py -q`

Expected: FAIL because the service and schemas do not exist.

- [ ] **Step 3: Implement ES/PG loader and stable view model**

When ES is enabled, use faceted aggregations; on failure or when disabled, call `crud_job.get_statistics_from_db`. The response always contains filters, KPI, salary distribution, skills, talent structure, ranking/trend/matrix arrays, and `dataStatus`; unsupported arrays are empty and registered as missing.

- [ ] **Step 4: Verify service and endpoint**

Run: `pytest tests/test_v2_market_dashboard.py tests/test_v2_api_contracts.py -q`

Expected: PASS without requiring a live Elasticsearch instance.

### Task 4: Career analysis, profile and pricing V2

**Files:**
- Create: `jobCollectionWebApi/schemas/v2/career.py`
- Create: `jobCollectionWebApi/schemas/v2/profile.py`
- Create: `jobCollectionWebApi/api/v2/endpoints/career_controller.py`
- Create: `jobCollectionWebApi/api/v2/endpoints/profile_controller.py`
- Create: `jobCollectionWebApi/api/v2/endpoints/pricing_controller.py`
- Reuse: `jobCollectionWebApi/crud/agent.py`
- Reuse: `common/databases/models/career_profile.py`
- Test: `tests/test_v2_career_profile.py`

- [ ] **Step 1: Write failing auth and pricing tests**

Test guest visibility, authenticated personalized overview, profile course/skill collections, and backend-managed prices.

- [ ] **Step 2: Implement adapters over existing profile, product, wallet and Agent services**

Do not duplicate billing or Agent runtime logic. Report/profile generation accepts `Idempotency-Key`; insufficient balance preserves the existing HTTP 402 contract.

- [ ] **Step 3: Verify tests**

Run: `pytest tests/test_v2_career_profile.py -q`

Expected: PASS for auth, idempotency, pricing and profile collection contracts.

### Task 5: Frontend V2 client cutover

**Files:**
- Create: `frontend/src/utils/v2Request.js`
- Modify: `frontend/src/api/market.js`
- Modify: `frontend/src/api/career.js`
- Modify: `frontend/src/api/profile.js`
- Modify: `frontend/src/api/apiContracts.test.js`

- [ ] **Step 1: Write failing base-path tests**

```js
it("uses the V2 API client for the market dashboard", () => {
  marketAPI.getDashboard({});
  expect(v2Request.get).toHaveBeenCalledWith("/market/dashboard", { params: {} });
});
```

- [ ] **Step 2: Implement isolated V2 Axios client**

The client uses `VITE_API_V2_BASE_URL || /api/v2`, reuses V1 access tokens, unified-response unwrapping and HTTP 402 events. Existing auth, wallet, resume and legacy routes continue using `request.js` and `/api/v1`.

- [ ] **Step 3: Verify front and back suites**

Run: `npm test` in `frontend`, then `pytest tests -q` in the repository root.

Expected: all current tests plus V2 contract tests pass.

### Task 6: Migration inventory and deprecation policy

**Files:**
- Create: `docs/API_V2_MIGRATION.md`

- [ ] **Step 1: Document endpoint mapping**

List V2 page needs, reused V1 implementation, new V2 route, data owner, authentication, cache TTL and deprecation status.

- [ ] **Step 2: Record V1 policy**

V1 remains available with no breaking changes. Add deprecation headers only after all production clients have migrated and a removal date is approved.

- [ ] **Step 3: Run final checks**

Run: `pytest tests -q`, `npm test`, `npm run build`, and `git diff --check`.

Expected: all checks pass; no crawler code is modified in this phase.
