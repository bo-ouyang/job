# Complete CI/CD Operations

This repository uses GitHub Actions as the authoritative CI/CD system. Local
commands are useful for development, but a production release is valid only when
GitHub has built, attested, and deployed the exact release images.

## Normal release path

1. Create a branch and use conventional commits such as `feat:`, `fix:`,
   `docs:`, `refactor:`, `test:`, `build:`, or `ci:`.
2. Open a pull request to `main`.
3. GitHub runs the required `frontend`, `web-api`, and `docker-images` checks.
4. Merge only after all required checks pass.
5. Release Please creates or updates a release pull request containing the next
   semantic version and `CHANGELOG.md` changes.
6. The release workflow explicitly dispatches `ci.yml` for that bot-created
   branch, so the same required checks run without a long-lived user PAT.
7. Merge the Release Please pull request to create `vMAJOR.MINOR.PATCH` and a
   GitHub Release.
8. The release workflow builds the backend and frontend once, publishes them to
   GHCR with OCI source/version/revision labels, generates provenance and SBOM
   attestations, and records Trivy results.
9. The protected `production` job authenticates with a dedicated SSH key,
   temporarily authenticates the server to GHCR, and invokes
   `deploy/remote_image_release.sh` with the exact release tag and commit.
10. Production pulls both images, verifies their
   `org.opencontainers.image.revision` labels, imports all application entry
   points in an isolated container, backs up the database, runs Alembic, starts
   the new services, verifies health, and switches Nginx and Prometheus.

Published image names are:

```text
ghcr.io/bo-ouyang/job-backend:vMAJOR.MINOR.PATCH
ghcr.io/bo-ouyang/job-backend:sha-COMMIT
ghcr.io/bo-ouyang/job-frontend:vMAJOR.MINOR.PATCH
ghcr.io/bo-ouyang/job-frontend:sha-COMMIT
```

The production server never builds images in the normal path.

## Required GitHub configuration

Environment `production` contains one secret:

```text
PRODUCTION_SSH_KEY
```

It contains these variables:

```text
PRODUCTION_HOST=193.112.94.8
PRODUCTION_USER=root
PRODUCTION_PORT=22
PRODUCTION_SERVER_NAME=193.112.94.8
PRODUCTION_KNOWN_HOSTS=<pinned OpenSSH host-key line>
SERVER_GIT_PROXY=http://127.0.0.1:10809
```

The key is dedicated to GitHub Actions. The root password is never stored in
GitHub. GHCR authentication uses the short-lived workflow token and is removed
from the server after every deployment.

The `production` Environment deployment branch policy must allow only `main`.
This setting is a security boundary: it prevents a workflow modified on another
branch from receiving the production SSH key. The deploy job also checks
`github.ref == 'refs/heads/main'` as defense in depth.

## Local verification

Use the Conda `job` environment, which provides Python 3.11:

```powershell
conda run -n job python -m pytest -q tests/test_cicd_architecture.py tests/test_release_architecture.py
cd frontend
npm test
npm run lint:dead-code
npm run build
```

Hosted CI remains authoritative because it runs in a clean Ubuntu environment.

## Release and runtime state

- Release worktrees: `/opt/job/releases`
- Current release link: `/opt/job/current`
- Database backups: `/opt/job/backups`
- Production environment: `/opt/job/.env.production`
- Payment certificates: `/opt/job/certs`
- Deployment state and lock: `/opt/job/.deploy`

Every application image and release directory is traceable to a Git tag and full
commit SHA. The Compose project name remains `job`, so PostgreSQL and Redis
volumes remain stable across releases.

## Automatic rollback

Before Nginx is switched, failures leave the current public release serving.
After a partial switch, the remote trap restores the previous Nginx and
Prometheus files and starts the previous release images. On the legacy first
cutover path it can restore the old Supervisor services.

Alembic schema downgrade and database restore are deliberately not automatic.
Every release creates a PostgreSQL dump in `/opt/job/backups`; a destructive or
backward-incompatible migration requires a reviewed restore procedure before
the release pull request is merged.

## Emergency fallback

The local command remains available only when GitHub Actions or GHCR is
unavailable and production must be repaired:

```powershell
.\deploy\deploy.ps1
```

This emergency path runs local gates, pushes the exact Git commit, builds images
on the production server, and uses the same backup, migration, health, switch,
and rollback guards. Record why it was used and reconcile the deployed commit
with a semantic GitHub Release afterward.

## Verification commands

```bash
readlink -f /opt/job/current
docker ps --format '{{.Names}} {{.Image}} {{.Status}}'
curl --fail http://127.0.0.1:18000/health
curl --fail http://127.0.0.1:18080/health
curl --fail http://127.0.0.1:18002/admin/
```

The current IP certificate is self-signed. Public probes therefore use
`--insecure` until a trusted domain certificate is installed.
