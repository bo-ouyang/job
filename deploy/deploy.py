#!/usr/bin/env python3
"""Validate, push, and release an exact Git commit over SSH."""

from __future__ import annotations

import argparse
from io import BytesIO
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

import paramiko


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_DIR = PROJECT_ROOT / ".deploy"
REMOTE_BASE = PurePosixPath("/opt/job/.deploy")


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def run(command: list[str], *, cwd: Path = PROJECT_ROOT) -> None:
    print(f"\n> {shlex.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def validate_environment(production_env: Path) -> None:
    values = read_dotenv(production_env)
    required = (
        "SECRET_KEY",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "REDIS_PASSWORD",
    )
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError(
            f"{production_env.name} is missing required values: {', '.join(missing)}"
        )
    if values.get("ENVIRONMENT", "").lower() != "production":
        raise ValueError(".env.production must set ENVIRONMENT=production")


def local_checks(production_env: Path) -> None:
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    docker = shutil.which("docker")
    if not npm:
        raise RuntimeError("npm was not found in PATH")
    if not docker:
        raise RuntimeError("docker was not found in PATH")

    test_files = [
        "tests/test_api_contracts.py",
        "tests/test_v2_api_contracts.py",
        "tests/test_agent_api_contract.py",
        "tests/test_production_safety.py",
        "tests/test_admin_deployment_config.py",
        "tests/test_release_architecture.py",
        "tests/test_webapi_source_hygiene.py",
        "tests/test_pytest_configuration.py",
        "tests/test_test_layout.py",
        "tests/test_v2_message_api.py",
        "tests/test_llm_client.py",
        "tests/test_message_notification_migration.py",
        "tests/test_notification_service.py",
        "tests/test_notification_tasks.py",
        "tests/test_agent_markdown_stream.py",
        "tests/test_agent_events.py",
        "tests/test_agent_runtime.py",
        "tests/test_ai_task_billing.py",
        "tests/test_celery_notification_routing.py",
        "tests/test_resume_parser.py",
        "tests/test_v2_career_profile.py",
    ]
    run([sys.executable, "-m", "pytest", "-q", *test_files])
    run([npm, "test"], cwd=PROJECT_ROOT / "frontend")
    run([npm, "run", "lint:dead-code"], cwd=PROJECT_ROOT / "frontend")
    run([npm, "run", "build"], cwd=PROJECT_ROOT / "frontend")

    compose_env = os.environ.copy()
    compose_env.update(
        {
            "BACKEND_IMAGE": "job-backend:validation",
            "FRONTEND_IMAGE": "job-frontend:validation",
        }
    )
    print("\n> docker compose config --quiet", flush=True)
    subprocess.run(
        [docker, "compose", "--env-file", str(production_env), "config", "--quiet"],
        cwd=PROJECT_ROOT,
        env=compose_env,
        check=True,
    )


def git_output(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def prepare_git_release(*, skip_push: bool = False) -> tuple[str, str]:
    # Keep these command names visible because they are part of the release contract:
    # git status --porcelain, followed by git push of the exact commit.
    if git_output("status", "--porcelain"):
        raise RuntimeError(
            "The working tree is not clean. Commit the release changes before deploying."
        )

    branch = git_output("branch", "--show-current")
    if not branch:
        raise RuntimeError("Deployments must run from a named Git branch")
    commit = git_output("rev-parse", "HEAD")
    repository_url = git_output("remote", "get-url", "origin")
    if "@" in repository_url.partition("//")[2].partition("/")[0]:
        raise RuntimeError("The origin URL must not contain embedded credentials")

    if skip_push:
        print("Skipping the local Git push; the server will verify the exact commit before build.")
    else:
        run(["git", "push", "origin", f"HEAD:{branch}"])
        remote_commit = git_output("ls-remote", "origin", f"refs/heads/{branch}").split()
        if not remote_commit or remote_commit[0] != commit:
            raise RuntimeError("The pushed branch does not resolve to the local commit")
    return commit, repository_url


def connect(host: str, password: str) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        hostname=host,
        username="root",
        password=password,
        timeout=20,
        auth_timeout=20,
        banner_timeout=20,
    )
    return client


def create_repository_bundle(commit: str) -> Path:
    if git_output("rev-parse", "HEAD") != commit:
        raise RuntimeError("The bundle commit must match the current Git HEAD")
    DEPLOY_DIR.mkdir(parents=True, exist_ok=True)
    bundle = DEPLOY_DIR / f"repository-{commit[:12]}.bundle"
    # git bundle create preserves the exact commit and complete Git history.
    run(["git", "bundle", "create", str(bundle), "HEAD"])
    return bundle


def ensure_remote_directory(sftp: paramiko.SFTPClient, path: PurePosixPath) -> None:
    current = PurePosixPath("/")
    for part in path.parts[1:]:
        current /= part
        try:
            sftp.stat(str(current))
        except FileNotFoundError:
            sftp.mkdir(str(current), mode=0o700)


def upload_release(
    client: paramiko.SSHClient,
    repository_bundle: Path | None = None,
) -> tuple[PurePosixPath, PurePosixPath | None]:
    remote_script = REMOTE_BASE / "remote_release.sh"
    remote_bundle = (
        REMOTE_BASE / repository_bundle.name if repository_bundle is not None else None
    )

    with client.open_sftp() as sftp:
        ensure_remote_directory(sftp, REMOTE_BASE)
        script_source = (PROJECT_ROOT / "deploy" / "remote_release.sh").read_bytes()
        script_source = script_source.replace(b"\r\n", b"\n")
        sftp.putfo(BytesIO(script_source), str(remote_script), file_size=len(script_source))
        sftp.chmod(str(remote_script), 0o700)
        if repository_bundle is not None and remote_bundle is not None:
            size_mib = repository_bundle.stat().st_size / 1024 / 1024
            print(f"Uploading Git bootstrap bundle ({size_mib:.1f} MiB)...", flush=True)
            sftp.put(str(repository_bundle), str(remote_bundle))
    return remote_script, remote_bundle


def stream_remote_command(client: paramiko.SSHClient, command: str) -> int:
    channel = client.get_transport().open_session()
    channel.exec_command(command)
    stdout_decoder = "utf-8"
    while True:
        made_progress = False
        if channel.recv_ready():
            sys.stdout.write(channel.recv(65536).decode(stdout_decoder, "replace"))
            sys.stdout.flush()
            made_progress = True
        if channel.recv_stderr_ready():
            sys.stderr.write(channel.recv_stderr(65536).decode(stdout_decoder, "replace"))
            sys.stderr.flush()
            made_progress = True
        if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
            break
        if not made_progress:
            time.sleep(0.1)
    return channel.recv_exit_status()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-checks",
        action="store_true",
        help="Skip local tests/build checks (emergency use only)",
    )
    parser.add_argument(
        "--skip-push",
        action="store_true",
        help="Skip a redundant push when the exact commit is already on origin",
    )
    parser.add_argument(
        "--bootstrap-bundle",
        action="store_true",
        help="Upload a Git bundle when the server cannot clone from GitHub",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    credentials_path = PROJECT_ROOT / ".env"
    production_env = PROJECT_ROOT / ".env.production"
    if not credentials_path.exists():
        raise FileNotFoundError("Root .env with remote_ip and remote_pd is required")
    if not production_env.exists():
        raise FileNotFoundError("Root .env.production is required")

    credentials = read_dotenv(credentials_path)
    host = credentials.get("remote_ip", "")
    password = credentials.get("remote_pd", "")
    if not host or not password:
        raise ValueError("Root .env must define remote_ip and remote_pd")
    validate_environment(production_env)

    if not args.skip_checks:
        local_checks(production_env)

    commit, repository_url = prepare_git_release(skip_push=args.skip_push)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    release_id = f"{timestamp}-{commit[:12]}"
    print(f"\nRelease: {release_id}")
    repository_bundle = create_repository_bundle(commit) if args.bootstrap_bundle else None

    client = connect(host, password)
    try:
        remote_script, remote_bundle = upload_release(client, repository_bundle)
        command = " ".join(
            shlex.quote(value)
            for value in (
                "bash",
                str(remote_script),
                repository_url,
                commit,
                release_id,
                host,
                str(remote_bundle) if remote_bundle is not None else "",
            )
        )
        status = stream_remote_command(client, command)
        if status != 0:
            raise RuntimeError(f"Remote release failed with exit status {status}")
    finally:
        client.close()
        if repository_bundle is not None:
            repository_bundle.unlink(missing_ok=True)

    print(f"\nRelease {release_id} is live: https://{host}/health")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"\nDeployment failed: {error}", file=sys.stderr)
        raise SystemExit(1)
