# Frontend, Backend, and Career Agent Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the non-crawler frontend and backend contracts consistent, harden the Career Agent request/SSE/recovery path, and document the resulting platform and Agent architecture.

**Architecture:** Treat FastAPI route schemas as the source of truth and cover them with route-contract and controller tests. Keep the Agent's existing PostgreSQL + Celery + Redis Streams design, add regression coverage at its API and browser-client boundaries, and make only minimal production changes required by failing tests.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x async, Celery, Redis Streams, Pydantic 2, Vue 3, Pinia, Axios, Vitest, Vite, Pytest.

---

### Task 1: Freeze the API contract baseline

**Files:**
- Create: `tests/test_api_contracts.py`
- Create: `frontend/src/api/apiContracts.test.js`
- Modify: `frontend/src/api/application.js`
- Modify: `frontend/src/api/common.js`

- [ ] **Step 1: Write the failing backend route-contract test**

```python
from api.v1.api import api_router


def route_pairs():
    return {
        (method, f"/api/v1{route.path}")
        for route in api_router.routes
        for method in (route.methods or set())
    }


def test_public_frontend_routes_are_canonical():
    routes = route_pairs()
    assert ("GET", "/api/v1/applications/") in routes
    assert ("GET", "/api/v1/jobs/{job_id}") in routes
    assert ("GET", "/api/v1/industries/level/{level}") in routes
    assert not any("/industries/industries/" in path for _, path in routes)
```

- [ ] **Step 2: Run the backend test and verify it fails on missing job detail and duplicate industry prefix**

Run: `python -m pytest tests/test_api_contracts.py -q -p no:cacheprovider`

Expected: FAIL for `/jobs/{job_id}` and canonical `/industries/...` routes.

- [ ] **Step 3: Write the failing frontend API wrapper test**

```javascript
import { describe, expect, it, vi } from "vitest";

const request = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));
vi.mock("@/utils/request", () => ({ default: request }));

import { applicationAPI } from "./application";
import { commonAPI } from "./common";

describe("frontend API contracts", () => {
  it("uses the backend applications collection for the current user", () => {
    applicationAPI.getMyApplications({ page: 1 });
    expect(request.get).toHaveBeenCalledWith("/applications/", { params: { page: 1 } });
  });

  it("uses canonical industry routes", () => {
    commonAPI.getIndustries(1);
    expect(request.get).toHaveBeenCalledWith("/industries/level/1");
  });
});
```

- [ ] **Step 4: Run the frontend test and verify it fails on current URLs**

Run: `npm run test -- --run src/api/apiContracts.test.js`

Expected: FAIL showing `/applications/me` and `/industries/industries/...`.

- [ ] **Step 5: Implement only the URL corrections and canonical backend industry prefix**

```javascript
getMyApplications(params) {
  return request.get("/applications/", { params });
}
```

```python
router = APIRouter(tags=["industries"])
```

- [ ] **Step 6: Run both contract test files**

Run: `python -m pytest tests/test_api_contracts.py -q -p no:cacheprovider`

Run: `npm run test -- --run src/api/apiContracts.test.js`

Expected: application and industry assertions PASS; job detail remains RED until Task 2.

### Task 2: Restore missing job-facing backend behavior

**Files:**
- Modify: `jobCollectionWebApi/api/v1/endpoints/job_controller.py`
- Modify: `jobCollectionWebApi/crud/job.py`
- Modify: `tests/test_api_contracts.py`
- Create: `tests/test_job_controller_contract.py`

- [ ] **Step 1: Write the failing job-detail controller test**

```python
import asyncio
from types import SimpleNamespace
from api.v1.endpoints import job_controller


def test_job_detail_returns_owned_schema_data(monkeypatch):
    expected = SimpleNamespace(id=10, title="Python Engineer")

    async def fake_get_detail(db, job_id):
        assert job_id == 10
        return expected

    monkeypatch.setattr(job_controller.crud_job, "get_detail", fake_get_detail)
    result = asyncio.run(job_controller.get_job_detail(10, db=object()))
    assert result is expected
```

- [ ] **Step 2: Run the test and verify the endpoint/function is missing**

Run: `python -m pytest tests/test_job_controller_contract.py -q -p no:cacheprovider`

Expected: FAIL because `get_job_detail` is not exposed.

- [ ] **Step 3: Implement the minimal detail endpoint using the existing eager-loading CRUD pattern**

```python
@router.get("/{job_id}", response_model=JobWithRelations)
async def get_job_detail(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await crud_job.get_detail(db, job_id)
    if job is None:
        raise AppException(status_code=404, code=StatusCode.BUSINESS_ERROR, message="职位不存在")
    return job
```

- [ ] **Step 4: Run the job and route-contract tests**

Run: `python -m pytest tests/test_job_controller_contract.py tests/test_api_contracts.py -q -p no:cacheprovider`

Expected: PASS.

### Task 3: Harden the Agent API and browser event path

**Files:**
- Create: `tests/test_agent_api_contract.py`
- Modify: `tests/test_agent_events.py`
- Modify: `frontend/src/stores/agent.test.js`
- Modify: `frontend/src/utils/sseClient.test.js`
- Modify only if tests demonstrate a defect: `jobCollectionWebApi/api/v1/endpoints/agent_controller.py`
- Modify only if tests demonstrate a defect: `jobCollectionWebApi/agent/sse.py`
- Modify only if tests demonstrate a defect: `frontend/src/stores/agent.js`
- Modify only if tests demonstrate a defect: `frontend/src/utils/sseClient.js`

- [ ] **Step 1: Add API contract tests for every Agent route, idempotency header, Snowflake string IDs, ownership dependencies, and SSE response headers**

```python
def test_agent_route_surface_is_complete():
    expected = {
        ("GET", "/api/v1/agent/capabilities"),
        ("POST", "/api/v1/agent/conversations"),
        ("POST", "/api/v1/agent/conversations/{conversation_id}/messages"),
        ("GET", "/api/v1/agent/runs/{run_id}"),
        ("GET", "/api/v1/agent/runs/{run_id}/events"),
        ("POST", "/api/v1/agent/runs/{run_id}/cancel"),
        ("GET", "/api/v1/agent/profile"),
        ("PATCH", "/api/v1/agent/profile"),
    }
    assert expected <= route_pairs()
```

- [ ] **Step 2: Add RED tests for any observed Agent integration defect**

```javascript
it("does not reconnect after a terminal run event", async () => {
  // Feed run_completed through the real store event callback and assert
  // connection state becomes closed without scheduling another stream.
});
```

- [ ] **Step 3: Run focused Agent tests and confirm each new regression test fails for the expected reason**

Run: `python -m pytest tests/test_agent_api_contract.py tests/test_agent_events.py tests/test_agent_runtime.py tests/test_agent_tools.py -q -p no:cacheprovider`

Run: `npm run test -- --run src/stores/agent.test.js src/utils/sseClient.test.js`

Expected: Existing tests stay green; each newly discovered defect has one RED test.

- [ ] **Step 4: Apply minimal Agent fixes one at a time**

```text
For each RED test: change only the failing ownership, idempotency, event replay,
terminal reconciliation, token refresh, or reconnect branch; rerun that single test
before moving to the next defect.
```

- [ ] **Step 5: Run all Agent tests**

Run: `python -m pytest tests/test_agent_batch1.py tests/test_agent_batch2.py tests/test_agent_api_contract.py tests/test_agent_events.py tests/test_agent_runtime.py tests/test_agent_tools.py -q -p no:cacheprovider`

Run: `npm run test -- --run`

Expected: PASS with no Agent regressions.

### Task 4: Full non-crawler verification

**Files:**
- Modify as required by isolated failures in `jobCollectionWebApi/`, `frontend/src/`, or `tests/`
- Do not modify: `jobCollection/`

- [ ] **Step 1: Parse all Python and Vue source without writing build artifacts into the repository**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -c "import ast,pathlib; [ast.parse(p.read_text(encoding='utf-8-sig')) for p in pathlib.Path('jobCollectionWebApi').rglob('*.py')]"
```

```powershell
npm run build -- --outDir "$env:TEMP/job-frontend-build"
```

- [ ] **Step 2: Run the complete maintained test suites**

Run: `python -m pytest tests -q -p no:cacheprovider`

Run: `npm run test -- --run`

Expected: PASS.

- [ ] **Step 3: Inspect `git diff --check` and the final working-tree delta**

Run: `git diff --check`

Run: `git status --short`

Expected: no whitespace errors and no crawler changes introduced by this plan.

### Task 5: Write the architecture handoff documents

**Files:**
- Create: `docs/PROJECT_ARCHITECTURE.md`
- Create: `docs/AGENT_ARCHITECTURE.md`

- [ ] **Step 1: Write the platform architecture document**

```markdown
# 项目总体架构

Include: product scope, repository map, runtime topology, API layering,
data ownership, PostgreSQL/Redis/Elasticsearch responsibilities, Celery queues,
frontend state flow, authentication, payments, deployment, observability,
local startup order, testing strategy, and known boundaries. Mark crawler as
out of scope for this integration pass while still showing its architectural position.
```

- [ ] **Step 2: Write the Career Agent architecture and runtime document**

```markdown
# 职业规划 Agent 架构与运行逻辑

Include: API contracts, four persistence tables, admission/idempotency flow,
Celery dispatch, Redis/DB locks, runtime state machine, six approved tools,
evidence policy, checkpoint transitions, Redis Streams event schema, SSE replay,
frontend recovery, cancellation/failure handling, limits, rollout, metrics,
and troubleshooting runbooks.
```

- [ ] **Step 3: Validate links, route names, event names, table names, and configuration keys against source**

Run: `rg -n "agent_|AgentEventType|AGENT_|/agent/" common jobCollectionWebApi frontend/src docs/PROJECT_ARCHITECTURE.md docs/AGENT_ARCHITECTURE.md`

Expected: document identifiers match the implemented code.

- [ ] **Step 4: Perform the plan self-review**

```text
Check requirements coverage, scan for placeholders, verify type and route-name
consistency, and confirm no crawler source was changed.
```
