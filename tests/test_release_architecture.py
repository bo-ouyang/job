from pathlib import Path


def test_release_process_has_one_docker_compose_entrypoint():
    project_root = Path(__file__).resolve().parents[1]
    release_guide = (project_root / "docs" / "deploy" / "deploy_commands.md").read_text(
        encoding="utf-8"
    )

    assert "docker compose" in release_guide
    assert "supervisorctl" not in release_guide
    assert "scp " not in release_guide


def test_compose_project_name_keeps_runtime_volumes_stable_across_releases():
    project_root = Path(__file__).resolve().parents[1]
    compose = (project_root / "docker-compose.yml").read_text(encoding="utf-8")

    assert compose.startswith("name: job\n")


def test_compose_runs_job_services_without_elasticsearch_or_duplicate_monitoring():
    project_root = Path(__file__).resolve().parents[1]
    compose = (project_root / "docker-compose.yml").read_text(encoding="utf-8")

    assert "  elasticsearch:" not in compose
    assert "  prometheus:" not in compose
    assert "  grafana:" not in compose
    assert '"127.0.0.1:18000:8000"' in compose
    assert '"127.0.0.1:18080:80"' in compose
    assert "ES_ENABLED: \"false\"" in compose
    assert "${JOB_CERTS_DIR:-/opt/job/certs}:/opt/job/certs:ro" in compose


def test_backend_image_excludes_the_crawler_project():
    project_root = Path(__file__).resolve().parents[1]
    dockerfile = (
        project_root / "jobCollectionWebApi" / "backend.Dockerfile"
    ).read_text(encoding="utf-8")

    assert "COPY . /app" not in dockerfile
    assert "COPY jobCollectionWebApi/ /app/jobCollectionWebApi/" in dockerfile
    assert "COPY common/ /app/common/" in dockerfile
    assert "COPY jobCollection/" not in dockerfile
    assert "mirrors.cloud.tencent.com/debian" in dockerfile
    assert "pypi.tuna.tsinghua.edu.cn" in dockerfile


def test_frontend_image_uses_a_configurable_npm_registry():
    project_root = Path(__file__).resolve().parents[1]
    dockerfile = (project_root / "frontend" / "Dockerfile").read_text(
        encoding="utf-8"
    )

    assert "ARG NPM_REGISTRY=" in dockerfile
    assert "registry.npmmirror.com" in dockerfile


def test_local_migration_chain_includes_the_production_database_head():
    project_root = Path(__file__).resolve().parents[1]
    migration = (
        project_root
        / "alembic"
        / "versions"
        / "20260807_00_add_structured_message_notifications.py"
    )

    assert migration.exists()
    assert 'revision: str = "20260807_00"' in migration.read_text(encoding="utf-8")


def test_one_command_release_has_remote_backup_cutover_and_rollback_guards():
    project_root = Path(__file__).resolve().parents[1]
    launcher = project_root / "deploy" / "deploy.ps1"
    client = project_root / "deploy" / "deploy.py"
    remote = project_root / "deploy" / "remote_release.sh"

    assert launcher.exists()
    assert client.exists()
    assert remote.exists()
    assert not (project_root / "deploy" / "release.sh").exists()

    launcher_source = launcher.read_text(encoding="utf-8")
    client_source = client.read_text(encoding="utf-8")
    remote_source = remote.read_text(encoding="utf-8")

    assert "deploy.py" in launcher_source
    assert "remote_ip" in client_source
    assert "remote_pd" in client_source
    assert '"--skip-push"' in client_source
    assert '"--bootstrap-bundle"' in client_source
    assert "git bundle create" in client_source
    assert '["git", "bundle", "create", str(bundle), "HEAD"]' in client_source
    assert 'replace(b"\\r\\n", b"\\n")' in client_source
    assert "git status --porcelain" in client_source
    assert "git push" in client_source
    assert "git fetch" in remote_source
    assert "git worktree add" in remote_source
    assert "http.version=HTTP/1.1" in remote_source
    assert "git_with_retry" in remote_source
    assert "timeout --signal=TERM 120" in remote_source
    assert "clone --depth=1 --no-checkout" in remote_source
    assert "--filter=blob:none" not in remote_source
    assert "repository_bundle" in remote_source
    assert "/opt/job/.env.production" in remote_source
    assert "pg_dump" in remote_source
    assert "pg_restore" in remote_source
    assert "supervisorctl stop" in remote_source
    assert "rollback" in remote_source
    assert "curl --fail" in remote_source
