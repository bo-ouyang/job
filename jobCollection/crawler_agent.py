"""Cross-machine crawler execution Agent.

The Agent makes outbound HTTPS requests to the API control plane. By default it
runs deterministic dry-run executions, so lifecycle control can be verified
without cookies, Chrome, Scrapy, or target-site traffic.
"""

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import platform as platform_module
import queue
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Dict, Optional, Sequence, Tuple

import httpx

from common.crawler_metrics import PROGRESS_FACT_METRICS
from common.crawler_sanitization import redact_crawler_text


logger = logging.getLogger("crawler-agent")
TELEMETRY_PREFIX = "CRAWLER_EVENT "
MAX_FINALIZE_ATTEMPTS = 3
SENSITIVE_FIELD_NAMES = {
    "authorization",
    "body",
    "content",
    "cookie",
    "credential",
    "credentials",
    "header",
    "headers",
    "password",
    "proxy",
    "requestbody",
    "requestcontent",
    "requestheaders",
    "responsebody",
    "responsecontent",
    "responseheaders",
    "responsetext",
    "secret",
    "token",
}
SENSITIVE_FIELD_SUFFIXES = (
    "authorization", "body", "cookie", "cookies", "credential",
    "credentials", "header", "headers", "password", "proxy", "secret",
    "token",
)


def _is_sensitive_field(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
    return normalized in SENSITIVE_FIELD_NAMES or normalized.endswith(
        SENSITIVE_FIELD_SUFFIXES
    )


def bounded_backoff(attempt: int) -> int:
    return min(30, 2 ** max(0, int(attempt)))


def build_scrapy_command(
    *,
    python_executable: str,
    spider_name: str,
    allowed_spiders: Sequence[str],
    task_id: str,
    spider_args: Dict[str, Any],
) -> list[str]:
    """Construct an argument list from an allowlist; never accept raw shell text."""

    if spider_name not in set(allowed_spiders):
        raise ValueError(f"spider {spider_name!r} is not allowlisted")
    command = [
        python_executable,
        "-m",
        "scrapy",
        "crawl",
        spider_name,
        "-a",
        f"task_id={task_id}",
    ]
    allowed_arguments = {
        "taskUrl": "task_url",
        "task_url": "task_url",
        "accountIndex": "account_index",
        "account_index": "account_index",
        "accountsFile": "accounts_file",
        "accounts_file": "accounts_file",
    }
    emitted = set()
    for source_name, target_name in allowed_arguments.items():
        if target_name in emitted or source_name not in spider_args:
            continue
        value = spider_args.get(source_name)
        if value is None or value == "":
            continue
        command.extend(["-a", f"{target_name}={value}"])
        emitted.add(target_name)
    return command


def parse_telemetry_line(line: str) -> Optional[Dict[str, Any]]:
    if not line.startswith(TELEMETRY_PREFIX):
        return None
    try:
        payload = json.loads(line[len(TELEMETRY_PREFIX) :])
    except (TypeError, ValueError):
        return None
    return sanitize_telemetry_event(payload) if isinstance(payload, dict) else None


def redact_log_line(line: str) -> str:
    return redact_crawler_text(line, max_length=4000)


def _sanitize_telemetry_value(value: Any, depth: int = 0) -> Any:
    if depth >= 4:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        result = {}
        for raw_key, child in list(value.items())[:50]:
            key = str(raw_key)[:80]
            if _is_sensitive_field(key):
                continue
            result[key] = _sanitize_telemetry_value(child, depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [
            _sanitize_telemetry_value(child, depth + 1)
            for child in value[:50]
        ]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_log_line(str(value)[:2000])


def sanitize_telemetry_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Treat spider stdout as untrusted before it reaches control storage."""

    level = str(payload.get("level") or "info").casefold()
    if level not in {"debug", "info", "warning", "error"}:
        level = "info"
    message = payload.get("message")
    return {
        "eventType": str(payload.get("eventType") or "telemetry")[:50],
        "level": level,
        "message": (
            redact_log_line(str(message)) if message is not None else None
        ),
        "metrics": _sanitize_telemetry_value(payload.get("metrics") or {}),
        "checkpoint": _sanitize_telemetry_value(
            payload.get("checkpoint") or {}
        ),
        "payload": _sanitize_telemetry_value(payload.get("payload") or {}),
    }


@dataclass(frozen=True)
class AgentConfig:
    worker_id: str = "crawler-worker-local"
    worker_name: str = "Local Crawler Worker"
    api_url: str = "http://127.0.0.1:8000/api/v2"
    token: str = ""
    allowed_spiders: Tuple[str, ...] = (
        "boss_list_drission",
        "boss_detail_drission",
    )
    dry_run: bool = True
    max_concurrency: int = 1
    poll_seconds: float = 2.0
    heartbeat_seconds: int = 10
    request_timeout: float = 15.0
    python_executable: str = sys.executable
    project_dir: str = str(Path(__file__).resolve().parent)

    @classmethod
    def from_env(cls) -> "AgentConfig":
        allowed = tuple(
            name.strip()
            for name in os.getenv(
                "CRAWLER_AGENT_ALLOWED_SPIDERS",
                "boss_list_drission,boss_detail_drission",
            ).split(",")
            if name.strip()
        )
        return cls(
            worker_id=os.getenv("CRAWLER_AGENT_ID", "crawler-worker-local"),
            worker_name=os.getenv("CRAWLER_AGENT_NAME", "Local Crawler Worker"),
            api_url=os.getenv("CRAWLER_AGENT_API_URL", "http://127.0.0.1:8000/api/v2"),
            token=os.getenv("CRAWLER_AGENT_TOKEN", ""),
            allowed_spiders=allowed,
            dry_run=os.getenv("CRAWLER_AGENT_DRY_RUN", "true").lower() == "true",
            max_concurrency=max(1, int(os.getenv("CRAWLER_AGENT_MAX_CONCURRENCY", "1"))),
            poll_seconds=max(0.5, float(os.getenv("CRAWLER_AGENT_POLL_SECONDS", "2"))),
            heartbeat_seconds=max(3, int(os.getenv("CRAWLER_AGENT_HEARTBEAT_SECONDS", "10"))),
            request_timeout=max(2.0, float(os.getenv("CRAWLER_AGENT_REQUEST_TIMEOUT", "15"))),
            python_executable=os.getenv("CRAWLER_PYTHON_EXECUTABLE", sys.executable),
            project_dir=os.getenv("CRAWLER_PROJECT_DIR", str(Path(__file__).resolve().parent)),
        )


class CrawlerControlClient:
    def __init__(self, config: AgentConfig):
        self.base_url = config.api_url.rstrip("/") + "/crawler-agent"
        self.client = httpx.Client(
            timeout=httpx.Timeout(config.request_timeout, connect=min(5.0, config.request_timeout)),
            headers={"X-Crawler-Agent-Token": config.token},
        )

    @staticmethod
    def _unwrap(payload):
        if isinstance(payload, dict) and payload.get("code") == 200 and "data" in payload:
            return payload["data"]
        return payload

    def _request(self, method: str, path: str, **kwargs):
        response = self.client.request(method, self.base_url + path, **kwargs)
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return None
        return self._unwrap(response.json())

    def heartbeat_worker(self, payload):
        return self._request("POST", "/workers/heartbeat", json=payload)

    def claim_run(self, payload):
        return self._request("POST", "/runs/claim", json=payload)

    def desired_state(self, run_id, execution_token):
        return self._request(
            "GET",
            f"/runs/{run_id}/desired-state",
            headers={"X-Crawler-Execution-Token": execution_token},
        )

    def heartbeat_run(self, run_id, payload):
        return self._request("POST", f"/runs/{run_id}/heartbeat", json=payload)

    def append_events(self, run_id, execution_token, events):
        return self._request(
            "POST",
            f"/runs/{run_id}/events",
            json={"executionToken": execution_token, "events": events},
        )

    def finish_run(self, run_id, payload):
        return self._request("POST", f"/runs/{run_id}/finish", json=payload)

    def close(self):
        self.client.close()


class DryRunExecution:
    pid = None

    def __init__(self, checkpoint: Optional[Dict[str, Any]] = None):
        checkpoint = checkpoint or {}
        self.tick_count = max(0, int(checkpoint.get("dryRunTick") or 0))
        self._stopped = False

    def advance(self):
        if not self._stopped:
            self.tick_count += 1

    def poll(self):
        return 0 if self._stopped else None

    def terminate(self):
        self._stopped = True

    def metrics(self) -> Dict[str, Any]:
        return {
            "itemsScraped": self.tick_count * 5,
            "pagesProcessed": self.tick_count,
            "responsesReceived": self.tick_count,
            "errors": 0,
            "elapsedSeconds": self.tick_count,
            "dryRun": True,
        }

    def checkpoint(self) -> Dict[str, Any]:
        return {"dryRunTick": self.tick_count}

    def drain_events(self) -> list[Dict[str, Any]]:
        return []


class DryRunRunner:
    def start(self, assignment: Dict[str, Any], config: AgentConfig) -> DryRunExecution:
        return DryRunExecution(assignment.get("checkpoint"))


class SubprocessExecution:
    def __init__(self, process: subprocess.Popen):
        self.process = process
        self.pid = process.pid
        self._metrics: Dict[str, Any] = {}
        self._checkpoint: Dict[str, Any] = {}
        self._events: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=1000)
        self._reader = threading.Thread(target=self._read_output, daemon=True)
        self._reader.start()

    def _read_output(self):
        stream = self.process.stdout
        if stream is None:
            return
        for raw_line in stream:
            line = raw_line.rstrip("\r\n")
            telemetry = parse_telemetry_line(line)
            if telemetry is not None:
                metrics = telemetry.get("metrics")
                if isinstance(metrics, dict):
                    self._metrics.update(metrics)
                checkpoint = telemetry.get("checkpoint")
                if isinstance(checkpoint, dict):
                    self._checkpoint.update(checkpoint)
                event = {
                    "eventType": str(telemetry.get("eventType") or "telemetry"),
                    "level": str(telemetry.get("level") or "info"),
                    "message": telemetry.get("message"),
                    "payload": telemetry.get("payload") or {},
                }
            else:
                event = {
                    "eventType": "process_log",
                    "level": "info",
                    "message": redact_log_line(line),
                    "payload": {},
                }
            try:
                self._events.put_nowait(event)
            except queue.Full:
                pass

    def advance(self):
        return None

    def poll(self):
        return self.process.poll()

    def terminate(self, grace_seconds: float = 8.0):
        if self.process.poll() is not None:
            return
        try:
            if os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
                self.process.send_signal(signal.CTRL_BREAK_EVENT)
            elif os.name != "nt":
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            else:
                self.process.terminate()
            self.process.wait(timeout=grace_seconds)
        except Exception:
            if self.process.poll() is None:
                try:
                    if os.name != "nt":
                        os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                    else:
                        self.process.kill()
                except Exception:
                    pass

    def metrics(self) -> Dict[str, Any]:
        return dict(self._metrics)

    def checkpoint(self) -> Dict[str, Any]:
        return dict(self._checkpoint)

    def drain_events(self) -> list[Dict[str, Any]]:
        events = []
        while len(events) < 100:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        return events


class SubprocessRunner:
    def start(self, assignment: Dict[str, Any], config: AgentConfig) -> SubprocessExecution:
        command = build_scrapy_command(
            python_executable=config.python_executable,
            spider_name=assignment["spiderName"],
            allowed_spiders=config.allowed_spiders,
            task_id=str(assignment["taskId"]),
            spider_args=assignment.get("spiderArgs") or {},
        )
        env = os.environ.copy()
        env["CRAWLER_RUN_ID"] = str(assignment["runId"])
        env["CRAWLER_EXECUTION_TOKEN"] = str(assignment["executionToken"])
        env["CRAWLER_WORKER_ID"] = config.worker_id
        kwargs = {
            "cwd": config.project_dir,
            "env": env,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
            "shell": False,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True
        return SubprocessExecution(subprocess.Popen(command, **kwargs))


class CrawlerAgent:
    def __init__(self, config: AgentConfig, *, client=None, runner=None):
        self.config = config
        self.client = client or CrawlerControlClient(config)
        self.runner = runner or (DryRunRunner() if config.dry_run else SubprocessRunner())
        self.active_assignment: Optional[Dict[str, Any]] = None
        self.active_execution = None
        self._pending_finish_payload: Optional[Dict[str, Any]] = None
        self._pending_finish_attempts = 0

    def _worker_heartbeat(self):
        self.client.heartbeat_worker(
            {
                "workerId": self.config.worker_id,
                "name": self.config.worker_name,
                "hostname": socket.gethostname(),
                "platform": platform_module.platform(),
                "maxConcurrency": self.config.max_concurrency,
                "activeRuns": 1 if self.active_execution is not None else 0,
                "capabilities": {
                    "spiders": list(self.config.allowed_spiders),
                    "dryRun": self.config.dry_run,
                    "telemetryVersion": 1,
                },
            }
        )

    def _heartbeat_active(self, status: str):
        assignment = self.active_assignment
        execution = self.active_execution
        self.client.heartbeat_run(
            assignment["runId"],
            {
                "executionToken": assignment["executionToken"],
                "status": status,
                "pid": execution.pid,
                "metrics": {
                    key: value
                    for key, value in execution.metrics().items()
                    if key not in PROGRESS_FACT_METRICS
                },
                "checkpoint": execution.checkpoint(),
            },
        )

    def _append_event(self, event_type: str, message: str, level: str = "info", payload=None):
        assignment = self.active_assignment
        self.client.append_events(
            assignment["runId"],
            assignment["executionToken"],
            [
                {
                    "eventType": event_type,
                    "level": level,
                    "message": message,
                    "payload": payload or {},
                }
            ],
        )

    def _finish_active(self, status: str, *, exit_code: Optional[int] = None, error_msg=None):
        assignment = self.active_assignment
        execution = self.active_execution
        try:
            self.client.finish_run(
                assignment["runId"],
                {
                    "executionToken": assignment["executionToken"],
                    "status": status,
                    "exitCode": exit_code,
                    "errorMsg": error_msg,
                    "metrics": execution.metrics(),
                    "checkpoint": execution.checkpoint(),
                },
            )
        except Exception as exc:
            if not self._is_lease_loss(exc):
                raise
        self.active_assignment = None
        self.active_execution = None

    @staticmethod
    def _is_lease_loss(error: Exception) -> bool:
        return isinstance(error, httpx.HTTPStatusError) and (
            error.response.status_code in {403, 404, 409}
        )

    @staticmethod
    def _is_transient_control_error(error: Exception) -> bool:
        if isinstance(error, httpx.HTTPStatusError):
            return error.response.status_code >= 500
        return isinstance(error, (httpx.TimeoutException, httpx.TransportError))

    def _clear_local_assignment(self):
        self.active_assignment = None
        self.active_execution = None
        self._pending_finish_payload = None
        self._pending_finish_attempts = 0

    def _retry_pending_finish(self) -> None:
        assignment = self.active_assignment
        payload = self._pending_finish_payload
        if assignment is None or payload is None:
            return
        self._pending_finish_attempts += 1
        try:
            self.client.finish_run(assignment["runId"], payload)
        except Exception as exc:
            if self._is_lease_loss(exc):
                self._clear_local_assignment()
                return
            if self._is_transient_control_error(exc):
                if self._pending_finish_attempts >= MAX_FINALIZE_ATTEMPTS:
                    logger.warning(
                        "Giving up local finalize after %s attempts; server will reconcile run=%s",
                        self._pending_finish_attempts,
                        assignment["runId"],
                    )
                    self._clear_local_assignment()
                return
            self._clear_local_assignment()
            raise
        self._clear_local_assignment()

    def _abandon_active(self):
        execution = self.active_execution
        try:
            if execution is not None:
                execution.terminate()
        finally:
            self.active_assignment = None
            self.active_execution = None

    def tick(self):
        self._worker_heartbeat()
        if self._pending_finish_payload is not None:
            self._retry_pending_finish()
            return
        if self.active_execution is None:
            claimed = self.client.claim_run(
                {
                    "workerId": self.config.worker_id,
                    "allowedSpiders": list(self.config.allowed_spiders),
                }
            )
            if claimed is None:
                return
            self.active_assignment = claimed
            try:
                self.active_execution = self.runner.start(claimed, self.config)
            except Exception as exc:
                self._pending_finish_payload = {
                    "executionToken": claimed["executionToken"],
                    "status": "failed",
                    "exitCode": None,
                    "errorMsg": f"Crawler runner failed to start: {type(exc).__name__}",
                    "metrics": {},
                    "checkpoint": claimed.get("checkpoint") or {},
                }
                self._retry_pending_finish()
                return
            try:
                self._append_event(
                    "run_started",
                    "Dry-run crawler started" if self.config.dry_run else "Crawler process started",
                    payload={"dryRun": self.config.dry_run},
                )
                self._heartbeat_active("running")
            except Exception as exc:
                if not self._is_lease_loss(exc):
                    raise
                self._abandon_active()
            return

        assignment = self.active_assignment
        execution = self.active_execution
        try:
            desired = self.client.desired_state(
                assignment["runId"],
                assignment["executionToken"],
            )
        except Exception as exc:
            if not self._is_lease_loss(exc):
                raise
            self._abandon_active()
            return
        if desired.get("status") in {"stopped", "succeeded", "failed", "stale"}:
            self._abandon_active()
            return
        desired_status = desired["desiredStatus"]
        if desired_status == "paused":
            execution.terminate()
            try:
                self._append_event("run_paused", "Crawler run paused")
                self._heartbeat_active("paused")
            except Exception as exc:
                if not self._is_lease_loss(exc):
                    raise
            self.active_assignment = None
            self.active_execution = None
            return
        if desired_status == "stopped":
            execution.terminate()
            self._append_event("run_stopped", "Crawler run stopped")
            self._finish_active("stopped", exit_code=execution.poll())
            return

        execution.advance()
        events = execution.drain_events()
        if events:
            try:
                self.client.append_events(
                    assignment["runId"],
                    assignment["executionToken"],
                    events,
                )
            except Exception as exc:
                if not self._is_lease_loss(exc):
                    raise
                self._abandon_active()
                return
        exit_code = execution.poll()
        if exit_code is None:
            try:
                self._heartbeat_active("running")
            except Exception as exc:
                if not self._is_lease_loss(exc):
                    raise
                self._abandon_active()
            return
        status = "succeeded" if exit_code == 0 else "failed"
        self._finish_active(
            status,
            exit_code=exit_code,
            error_msg=None if exit_code == 0 else f"crawler exited with code {exit_code}",
        )

    def shutdown(self):
        if self.active_execution is None:
            return
        execution = self.active_execution
        try:
            execution.terminate()
            self._finish_active(
                "stopped",
                exit_code=execution.poll(),
                error_msg="Crawler Agent shutting down",
            )
        except Exception as exc:
            logger.warning("Failed to finalize crawler during Agent shutdown: %s", type(exc).__name__)
            self.active_assignment = None
            self.active_execution = None

    def run_forever(self):
        attempt = 0
        try:
            while True:
                try:
                    self.tick()
                    attempt = 0
                    time.sleep(self.config.poll_seconds)
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    logger.warning("Crawler control plane unavailable: %s", type(exc).__name__)
                    time.sleep(bounded_backoff(attempt))
                    attempt += 1
        finally:
            self.shutdown()
            close = getattr(self.client, "close", None)
            if callable(close):
                close()


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = AgentConfig.from_env()
    if not config.token:
        logger.error("CRAWLER_AGENT_TOKEN is required")
        return 2
    logger.info(
        "Starting crawler Agent worker=%s dry_run=%s spiders=%s",
        config.worker_id,
        config.dry_run,
        ",".join(config.allowed_spiders),
    )
    CrawlerAgent(config).run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
