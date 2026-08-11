#!/usr/bin/env python3
"""Validate, push, and release an exact Git commit over SSH."""

from __future__ import annotations

import argparse
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
    ]
    run([sys.executable, "-m", "pytest", "-q", *test_files])
    run([npm, "test"], cwd=PROJECT_ROOT / "frontend")
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


def prepare_git_release() -> tuple[str, str]:
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
) -> PurePosixPath:
    remote_script = REMOTE_BASE / "remote_release.sh"

    with client.open_sftp() as sftp:
        ensure_remote_directory(sftp, REMOTE_BASE)
        sftp.put(str(PROJECT_ROOT / "deploy" / "remote_release.sh"), str(remote_script))
        sftp.chmod(str(remote_script), 0o700)
    return remote_script


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

    commit, repository_url = prepare_git_release()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    release_id = f"{timestamp}-{commit[:12]}"
    print(f"\nRelease: {release_id}")

    client = connect(host, password)
    try:
        remote_script = upload_release(client)
        command = " ".join(
            shlex.quote(value)
            for value in (
                "bash",
                str(remote_script),
                repository_url,
                commit,
                release_id,
                host,
            )
        )
        status = stream_remote_command(client, command)
        if status != 0:
            raise RuntimeError(f"Remote release failed with exit status {status}")
    finally:
        client.close()

    print(f"\nRelease {release_id} is live: https://{host}/health")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"\nDeployment failed: {error}", file=sys.stderr)
        raise SystemExit(1)
