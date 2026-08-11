# Job Platform

[![Verify](https://github.com/bo-ouyang/job/actions/workflows/ci.yml/badge.svg)](https://github.com/bo-ouyang/job/actions/workflows/ci.yml)
[![Release](https://github.com/bo-ouyang/job/actions/workflows/release.yml/badge.svg)](https://github.com/bo-ouyang/job/actions/workflows/release.yml)

The supported product surface is the Vue frontend and FastAPI Web API. Production
runs immutable Docker images through Docker Compose, backed by project-specific
PostgreSQL and Redis services; Elasticsearch is disabled.

- CI/CD and production operations: [docs/deploy/cicd.md](docs/deploy/cicd.md)
- Emergency release command: [docs/deploy/deploy_commands.md](docs/deploy/deploy_commands.md)
- Frontend documentation: [docs/frontend/README.md](docs/frontend/README.md)
