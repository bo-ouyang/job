# Complete CI/CD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver every reviewed semantic release through GitHub Actions as immutable GHCR images and deploy those exact images to production with backup, migration, health-check, and rollback guards.

**Architecture:** Pull requests run deterministic frontend, Web API, Compose, and Docker-image checks on GitHub-hosted runners. Release Please turns conventional commits on `main` into version PRs and Git tags; a created release builds backend/frontend images once, publishes them to GHCR with commit labels and attestations, then deploys those images through a protected `production` environment. The current Git-and-build-on-server command remains an emergency fallback, while the normal production path pulls CI-built images and verifies their revision labels before any database or service mutation.

**Tech Stack:** GitHub Actions, Release Please, GHCR, Docker Buildx, Docker Compose, OpenSSH, Bash, Pytest, Vitest, Alembic, Nginx, Prometheus.

---

### Task 1: Lock the CI/CD architecture with executable contracts

**Files:**
- Create: `tests/test_cicd_architecture.py`
- Modify: `deploy/deploy.py`

- [ ] **Step 1: Write failing contracts for CI, releases, immutable artifacts, SSH deployment, and production rollback**

```python
def test_pull_requests_run_all_required_ci_gates():
    assert "pull_request:" in ci
    assert "npm run lint:dead-code" in ci
    assert "pytest -q" in ci
    assert "docker build" in ci


def test_release_builds_ghcr_images_once_then_deploys_them():
    assert "release-please-action" in release
    assert "ghcr.io" in release
    assert "push: true" in release
    assert "environment: production" in release
    assert "remote_image_release.sh" in release


def test_remote_image_release_verifies_revision_before_database_changes():
    assert "org.opencontainers.image.revision" in remote
    assert remote.index("org.opencontainers.image.revision") < remote.index("pg_dump")
```

- [ ] **Step 2: Run the new contracts and verify RED**

Run: `conda run -n job python -m pytest -q tests/test_cicd_architecture.py`

Expected: FAIL because the release workflow and image deployment script do not exist.

- [ ] **Step 3: Add the contract suite to the local emergency release checks**

Add `tests/test_cicd_architecture.py` to `local_checks()` in `deploy/deploy.py`, ensuring local and hosted release paths enforce the same architecture.

- [ ] **Step 4: Commit the contracts**

```powershell
git add tests/test_cicd_architecture.py deploy/deploy.py
git commit -m "test: define complete CI/CD contracts"
```

### Task 2: Strengthen pull-request CI

**Files:**
- Modify: `.github/workflows/ci.yml`
- Test: `tests/test_cicd_architecture.py`

- [ ] **Step 1: Define read-only permissions and cancellation for stale commits**

```yaml
permissions:
  contents: read

concurrency:
  group: verify-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

- [ ] **Step 2: Keep frontend and Web API gates on Ubuntu with Node 20 and Python 3.11**

The frontend job runs `npm ci`, Vitest, Knip, and Vite build. The Web API job installs `jobCollectionWebApi/requirements.txt`, runs the supported non-crawler suite including `test_cicd_architecture.py`, and validates Compose with `.env.production.example`.

- [ ] **Step 3: Add a Docker image contract job**

```yaml
- run: docker build -t job-backend:ci -f jobCollectionWebApi/backend.Dockerfile .
- run: docker run --rm --env-file .env.production.example job-backend:ci python -c "import jobCollectionWebApi.main; import jobCollectionWebApi.main_admin; import jobCollectionWebApi.worker"
- run: docker build -t job-frontend:ci -f frontend/Dockerfile .
```

- [ ] **Step 4: Run contracts and verify GREEN**

Run: `conda run -n job python -m pytest -q tests/test_cicd_architecture.py`

Expected: PASS for CI workflow assertions; release assertions remain failing until Task 3.

- [ ] **Step 5: Commit CI gates**

```powershell
git add .github/workflows/ci.yml tests/test_cicd_architecture.py
git commit -m "ci: enforce pull request quality gates"
```

### Task 3: Add semantic release and immutable GHCR publication

**Files:**
- Create: `.github/workflows/release.yml`
- Create: `release-please-config.json`
- Create: `.release-please-manifest.json`
- Create: `CHANGELOG.md`
- Test: `tests/test_cicd_architecture.py`

- [ ] **Step 1: Configure Release Please from the deployed `v1.0.0` baseline**

```json
{
  "packages": {
    ".": {
      "release-type": "simple",
      "package-name": "job",
      "changelog-path": "CHANGELOG.md"
    }
  }
}
```

The manifest starts at `{ ".": "1.0.0" }`. The bootstrap GitHub release will point to production commit `8e4816d0a37fcbb47e8fed1dbb3be3d2a437a77d` before the new workflow is merged.

- [ ] **Step 2: Add a release workflow triggered by pushes to `main` and manual dispatch**

Use `googleapis/release-please-action@v4`. Expose `release_created`, `tag_name`, and `sha` as job outputs so image and deployment jobs execute only when a release is created.

- [ ] **Step 3: Build and push backend/frontend images once**

Use a matrix with `docker/setup-buildx-action`, `docker/login-action`, and `docker/build-push-action`. Publish:

```text
ghcr.io/bo-ouyang/job-backend:vX.Y.Z
ghcr.io/bo-ouyang/job-backend:sha-<commit>
ghcr.io/bo-ouyang/job-frontend:vX.Y.Z
ghcr.io/bo-ouyang/job-frontend:sha-<commit>
```

Set OCI source, version, and revision labels; enable BuildKit provenance and SBOM attestations.

- [ ] **Step 4: Add image vulnerability reports**

Run Trivy for each published image and upload SARIF to GitHub Security. The initial rollout records findings without blocking deployment; severity policy can be tightened once the baseline backlog is classified.

- [ ] **Step 5: Commit release automation**

```powershell
git add .github/workflows/release.yml release-please-config.json .release-please-manifest.json CHANGELOG.md tests/test_cicd_architecture.py
git commit -m "feat: publish semantic GHCR releases"
```

### Task 4: Deploy CI-built images without rebuilding production

**Files:**
- Create: `deploy/remote_image_release.sh`
- Modify: `.github/workflows/release.yml`
- Test: `tests/test_cicd_architecture.py`

- [ ] **Step 1: Create an image-based remote release script**

Arguments are repository URL, commit SHA, release ID, server name, backend image, frontend image, and Git proxy. The script keeps the existing release lock, Git worktree, `.env.production`, database backup, migration, Nginx/Prometheus switch, current symlink, and rollback behavior.

- [ ] **Step 2: Pull and verify artifacts before production mutation**

```bash
docker pull "$backend_image"
docker pull "$frontend_image"
[[ $(docker image inspect -f '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$backend_image") == "$commit" ]]
[[ $(docker image inspect -f '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$frontend_image") == "$commit" ]]
compose_new run --rm --no-deps api python -c "import jobCollectionWebApi.main; import jobCollectionWebApi.main_admin; import jobCollectionWebApi.worker"
```

All pulls, revision checks, Compose validation, and imports precede `pg_dump`, migrations, and application replacement.

- [ ] **Step 3: Add protected production deployment over OpenSSH**

The release job uses repository variables `PRODUCTION_HOST`, `PRODUCTION_USER`, `PRODUCTION_PORT`, `PRODUCTION_SERVER_NAME`, and `PRODUCTION_KNOWN_HOSTS`, plus the `PRODUCTION_SSH_KEY` secret. It copies only the committed remote script, performs an ephemeral GHCR login using `github.token`, invokes the release by exact tag and commit, logs out in an `always()` step, then probes public `/health`.

- [ ] **Step 4: Verify Bash, Compose, and contracts**

Run:

```powershell
conda run -n job python -m pytest -q tests/test_cicd_architecture.py tests/test_release_architecture.py
docker build --check -f jobCollectionWebApi/backend.Dockerfile .
```

Expected: PASS.

- [ ] **Step 5: Commit image deployment**

```powershell
git add deploy/remote_image_release.sh .github/workflows/release.yml tests/test_cicd_architecture.py
git commit -m "feat: deploy verified release images"
```

### Task 5: Document operating and recovery procedures

**Files:**
- Modify: `docs/deploy/deploy_commands.md`
- Create: `docs/deploy/cicd.md`
- Modify: `README.md`
- Test: `tests/test_cicd_architecture.py`

- [ ] **Step 1: Document the normal release lifecycle**

Document conventional commits, PR checks, Release Please PRs, semantic tags, GHCR artifacts, production environment deployment, exact release directories, and status locations.

- [ ] **Step 2: Document emergency and rollback paths**

Keep `./deploy/deploy.ps1` as an explicitly labeled emergency build-on-server command. Document application rollback, database backup paths, the fact that schema downgrade is not automatic, and commands that verify `/opt/job/current`, containers, Supervisor disablement, Prometheus, and public health.

- [ ] **Step 3: Document local Conda prerequisites**

State that local Python commands use `conda run -n job` and that hosted CI is authoritative on Python 3.11.

- [ ] **Step 4: Commit documentation**

```powershell
git add README.md docs/deploy/deploy_commands.md docs/deploy/cicd.md tests/test_cicd_architecture.py
git commit -m "docs: define CI/CD release operations"
```

### Task 6: Verify the complete change

**Files:**
- No production code changes

- [ ] **Step 1: Run the supported Web API and release suites with Conda `job`**

Run the same explicit Pytest list used by `.github/workflows/ci.yml`.

Expected: all tests pass; crawler implementation tests remain outside this change.

- [ ] **Step 2: Run all frontend gates**

Run: `npm test && npm run lint:dead-code && npm run build`

Expected: 25 test files pass, Knip reports no findings, Vite build succeeds.

- [ ] **Step 3: Validate workflows and scripts**

Run `actionlint`, `bash -n deploy/remote_image_release.sh` in a Linux container, `docker compose config --quiet`, Dockerfile `--check`, and `git diff --check`.

- [ ] **Step 4: Request code review and fix all Critical/Important findings**

Review the branch against its base commit, focusing on secret exposure, GitHub token scope, image provenance, release conditionals, SSH quoting, pre-mutation ordering, rollback, and database safety.

### Task 7: Provision GitHub and production integration

**Files:**
- GitHub repository settings
- Server: `/root/.ssh/authorized_keys`

- [ ] **Step 1: Install and authenticate GitHub CLI**

Install `gh`, authenticate as repository owner `bo-ouyang`, and verify `repo`, `workflow`, and package administration access without printing tokens.

- [ ] **Step 2: Create a dedicated Actions SSH key**

Generate an Ed25519 key dedicated to `bo-ouyang/job`, install the public key on `root@193.112.94.8`, preserve existing authorized keys, and verify non-interactive SSH using the pinned host key.

- [ ] **Step 3: Configure the production environment**

Create GitHub Environment `production`, set environment variables for host/user/port/server name/known hosts, and set `PRODUCTION_SSH_KEY` as an environment secret. No password is stored in GitHub.

- [ ] **Step 4: Establish the semantic baseline**

Create annotated tag and GitHub Release `v1.0.0` at deployed commit `8e4816d0a37fcbb47e8fed1dbb3be3d2a437a77d` before merging the release workflow, so it does not trigger a deployment.

- [ ] **Step 5: Push the feature branch and create a pull request**

Push `codex/complete-cicd`, open a PR to `main`, and wait for all required CI checks.

- [ ] **Step 6: Configure main branch protection**

Require the frontend, Web API, and Docker image contract checks; reject force pushes and deletion; require changes through pull requests. Keep the repository owner as the emergency bypass actor.

- [ ] **Step 7: Merge and observe the first release cycle**

Merge only after CI is green. Confirm Release Please creates the release PR. Merge that PR, then observe GHCR build, attestations, production deployment, health verification, and GitHub deployment status through completion.

## Scope Boundary

This plan changes frontend/Web API delivery infrastructure only. It does not read, modify, test, or deploy crawler process behavior beyond packaging the already-required opaque `jobCollection` runtime dependency in the backend image.
