import json
from pathlib import Path
import re

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def read_workflow(path: str) -> dict:
    return yaml.load(read_text(path), Loader=yaml.BaseLoader)


def test_pull_requests_run_frontend_web_api_and_docker_gates():
    workflow = read_workflow(".github/workflows/ci.yml")
    source = read_text(".github/workflows/ci.yml")

    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["on"]["pull_request"]["branches"] == ["main"]
    assert "workflow_dispatch" in workflow["on"]
    assert workflow["concurrency"]["cancel-in-progress"] == "true"
    assert {"frontend", "web-api", "docker-images"} <= set(workflow["jobs"])
    assert "npm test" in source
    assert "npm run lint:dead-code" in source
    assert "python-version: \"3.11\"" in source
    assert "tests/test_cicd_architecture.py" in source
    assert "docker build" in source
    assert "import jobCollectionWebApi.main_admin" in source


def test_web_api_ci_installs_emergency_release_dependencies():
    source = read_text(".github/workflows/ci.yml")
    requirements = read_text("deploy/requirements.txt")

    assert requirements.strip() == "paramiko==5.0.0"
    assert (
        "pip install -r jobCollectionWebApi/requirements.txt "
        "-r deploy/requirements.txt"
    ) in source


def test_emergency_release_runs_the_cicd_contracts_locally():
    client = read_text("deploy/deploy.py")

    assert '"tests/test_cicd_architecture.py"' in client


def test_release_please_owns_semantic_version_creation():
    workflow = read_workflow(".github/workflows/release.yml")
    config = read_text("release-please-config.json")
    manifest = json.loads(read_text(".release-please-manifest.json"))
    source = read_text(".github/workflows/release.yml")

    assert workflow["on"]["push"]["branches"] == ["main"]
    assert set(workflow["on"]["workflow_dispatch"]["inputs"]) == {"tag", "sha"}
    assert "googleapis/release-please-action" in source
    assert "RELEASE_PLEASE_TOKEN" not in source
    assert workflow["jobs"]["release"]["permissions"]["actions"] == "write"
    assert "steps.release.outputs.prs_created == 'true'" in source
    assert '"action_required"' in source
    assert '"github-actions[bot]"' in source
    assert ".head.repo.full_name" in source
    assert '"queued", "in_progress"' in source
    assert "for _ in {1..24}" in source
    assert "/approve" in source
    assert "gh workflow run" not in source
    assert "release_created" in source
    assert '"release-type": "simple"' in config
    version = manifest.get(".")
    assert isinstance(version, str)
    assert re.fullmatch(
        r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version
    )
    assert tuple(map(int, version.split("."))) >= (1, 0, 0)


def test_release_builds_traceable_ghcr_images_once():
    workflow = read_workflow(".github/workflows/release.yml")
    source = read_text(".github/workflows/release.yml")
    build = workflow["jobs"]["build-images"]

    assert workflow["permissions"] == {}
    assert workflow["jobs"]["release"]["permissions"] == {
        "actions": "write",
        "contents": "write",
        "pull-requests": "write",
    }
    assert build["permissions"]["packages"] == "write"
    assert build["permissions"]["id-token"] == "write"
    assert "github.event_name != 'workflow_dispatch'" in build["if"]
    assert build["strategy"]["matrix"]["image"] == ["backend", "frontend"]
    assert "ghcr.io/${{ github.repository_owner }}/job-" in source
    assert "push: true" in source
    assert "org.opencontainers.image.revision=${{ needs.release.outputs.sha }}" in source
    assert "provenance: mode=max" in source
    assert "sbom: true" in source
    assert "actions/attest-build-provenance" in source


def test_production_deployment_uses_keys_and_protected_environment():
    workflow = read_workflow(".github/workflows/release.yml")
    source = read_text(".github/workflows/release.yml")
    deploy = workflow["jobs"]["deploy-production"]

    assert deploy["environment"]["name"] == "production"
    assert "build-images" in deploy["needs"]
    assert "needs.build-images.result == 'skipped'" in deploy["if"]
    assert "github.ref == 'refs/heads/main'" in deploy["if"]
    assert deploy["permissions"] == {"contents": "read", "packages": "read"}
    assert "PRODUCTION_SSH_KEY" in source
    assert "PRODUCTION_KNOWN_HOSTS" in source
    assert "PRODUCTION_PASSWORD" not in source
    assert "remote_image_release.sh" in source
    assert "docker login ghcr.io" in source
    assert "--password-stdin" in source
    assert "docker logout ghcr.io" in source

    checkout = next(
        step
        for step in deploy["steps"]
        if step.get("name") == "Check out trusted deployment runner"
    )
    assert "with" not in checkout


def test_remote_release_verifies_images_before_database_changes():
    source = read_text("deploy/remote_image_release.sh")

    assert "flock -n" in source
    assert 'docker_pull_with_retry "$backend_image"' in source
    assert 'docker_pull_with_retry "$frontend_image"' in source
    assert "timeout --signal=TERM 300 docker pull" in source
    assert "org.opencontainers.image.revision" in source
    assert "docker build" not in source
    assert "start_previous_release" in source
    assert "rollback" in source
    assert "pg_dump" in source
    assert "compose_new run --rm migration" in source
    assert "curl --fail" in source

    revision_check = source.index("org.opencontainers.image.revision")
    backup_call = source.index("backup_running_database \"$database_backup\"")
    assert revision_check < backup_call
    assert revision_check < source.index("runuser -u postgres -- pg_dump")
    assert revision_check < source.index("compose_new run --rm migration")
    assert backup_call < source.index("compose_new up -d db redis")


def test_operations_guide_defines_normal_and_emergency_release_paths():
    guide = read_text("docs/deploy/cicd.md")

    assert "Release Please" in guide
    assert "GHCR" in guide
    assert "production" in guide
    assert "conda run -n job" in guide
    assert ".\\deploy\\deploy.ps1" in guide
    assert "emergency" in guide.lower()
    assert "/opt/job/backups" in guide
    assert "database" in guide.lower()
    assert "deployment branch policy" in guide.lower()
    assert "main" in guide
