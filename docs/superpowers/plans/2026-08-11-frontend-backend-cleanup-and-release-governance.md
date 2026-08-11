# Frontend and Backend Cleanup and Release Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire unreachable frontend and Web API code, verify the retained product surface, and make Docker image releases reproducible.

**Architecture:** The supported product is the Vue frontend plus the FastAPI Web API and their shared data infrastructure. Retired routes are removed at their entrypoints rather than restored with compatibility shims. Production runs versioned backend and frontend images through one Compose topology; migrations complete before application services start.

**Tech Stack:** Vue 3, Vite, Vitest, FastAPI, Pytest, Alembic, Docker Compose, Nginx.

---

### Task 1: Retire unreachable frontend features

**Files:**
- Modify: `frontend/src/router/index.js`
- Modify: `frontend/src/layout/BasicLayout.vue`
- Delete: `frontend/src/views/InsightsHub.vue`
- Delete: `frontend/src/views/CitySalaryCompareView.vue`
- Delete: `frontend/src/views/IndustrySalaryCompareView.vue`
- Delete: `frontend/src/stores/favorite.js`
- Delete: `frontend/src/api/application.js`
- Test: `frontend/src/router/index.test.js`

- [ ] **Step 1: Add a route regression test**

```js
expect(router.getRoutes().map((route) => route.name)).not.toContain("career-data");
expect(router.getRoutes().map((route) => route.name)).not.toContain("compare-industries");
```

- [ ] **Step 2: Run the test and confirm the old routes fail it**

Run: `npm test -- src/router/index.test.js`
Expected: FAIL because legacy routes are still registered.

- [ ] **Step 3: Remove only unreferenced route entrypoints and their orphan modules**

```js
// Keep only routes whose Vue modules and API clients are part of the current product.
```

- [ ] **Step 4: Verify the frontend**

Run: `npm test && npm run build`
Expected: PASS and a successful Vite production bundle.

### Task 2: Keep tests and API contracts aligned with the retained surface

**Files:**
- Delete: `pytest/conftest.py`
- Delete: `pytest/test_analysis.py`
- Delete: `pytest/test_auth.py`
- Delete: `pytest/test_crud.py`
- Delete: `pytest/test_job.py`
- Modify: `tests/test_api_contracts.py`
- Create: `pyproject.toml`
- Test: `tests/test_test_layout.py`
- Test: `tests/test_pytest_configuration.py`

- [ ] **Step 1: Add a failing test that rejects the obsolete `pytest/` suite**

```python
assert not (project_root / "pytest").exists()
```

- [ ] **Step 2: Delete the stale suite and configure canonical test discovery**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = [".", "jobCollectionWebApi", "jobCollection"]
```

- [ ] **Step 3: Remove assertions for retired application and job-detail APIs**

```python
# Contract tests assert only routes consumed by the retained frontend.
```

- [ ] **Step 4: Run Web API contract and safety tests**

Run: `pytest -q tests/test_api_contracts.py tests/test_v2_api_contracts.py tests/test_agent_api_contract.py tests/test_production_safety.py`
Expected: PASS.

### Task 3: Standardize releases on immutable Docker images

**Files:**
- Modify: `docker-compose.yml`
- Modify: `deploy/nginx/container.conf`
- Create: `.env.production.example`
- Create: `deploy/release.sh`
- Modify: `docs/deploy/deploy_commands.md`
- Test: `tests/test_admin_deployment_config.py`
- Test: `tests/test_release_architecture.py`

- [ ] **Step 1: Add failing tests for versioned images and one release path**

```python
assert "image: ${BACKEND_IMAGE:?set BACKEND_IMAGE to an immutable release tag}" in config
assert "supervisorctl" not in release_guide
```

- [ ] **Step 2: Replace source mounts with tagged backend and frontend images**

```yaml
image: ${BACKEND_IMAGE:?set BACKEND_IMAGE to an immutable release tag}
```

- [ ] **Step 3: Add migration-first release and health verification**

```bash
docker compose run --rm --no-deps migration
curl --fail --retry 12 --retry-delay 5 http://127.0.0.1:8080/health
```

- [ ] **Step 4: Validate Compose interpolation**

Run: `BACKEND_IMAGE=registry.example/job-api:v1.2.3 FRONTEND_IMAGE=registry.example/job-frontend:v1.2.3 docker compose config --quiet`
Expected: PASS.

### Task 4: Enforce the boundary in CI

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Run frontend tests and production build on every pull request**

```yaml
- run: npm test
- run: npm run build
```

- [ ] **Step 2: Run Web API contract, safety, deployment, and configuration tests**

```yaml
- run: pytest -q tests/test_api_contracts.py tests/test_production_safety.py
- run: docker compose config --quiet
```

- [ ] **Step 3: Require the CI workflow before merging a release branch**

Expected: tags are created only from a reviewed, green `main` commit.

## Scope Boundary

This plan intentionally excludes crawler implementation and crawler test behavior. Crawler changes require a separate specification and verification plan.
