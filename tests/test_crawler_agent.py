import sys
from pathlib import Path

import pytest
import httpx


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))


class FakeControlClient:
    def __init__(self, assignments=None, desired_states=None):
        self.assignments = list(assignments or [])
        self.desired_states = list(desired_states or [])
        self.worker_heartbeats = []
        self.run_heartbeats = []
        self.events = []
        self.finished = []

    def heartbeat_worker(self, payload):
        self.worker_heartbeats.append(payload)
        return payload

    def claim_run(self, payload):
        return self.assignments.pop(0) if self.assignments else None

    def desired_state(self, run_id, execution_token):
        if self.desired_states:
            return self.desired_states.pop(0)
        return {"runId": str(run_id), "desiredStatus": "running", "status": "running"}

    def heartbeat_run(self, run_id, payload):
        self.run_heartbeats.append((str(run_id), payload))
        return payload

    def append_events(self, run_id, execution_token, events):
        self.events.extend(events)
        return len(events)

    def finish_run(self, run_id, payload):
        self.finished.append((str(run_id), payload))
        return payload


def assignment(token="run-token-1"):
    return {
        "runId": "101",
        "taskId": "201",
        "spiderName": "boss_list_drission",
        "spiderArgs": {"taskUrl": "https://example.invalid/jobs"},
        "executionToken": token,
        "desiredStatus": "running",
        "checkpoint": {},
    }


def test_scrapy_command_is_allowlisted_and_never_requires_a_shell():
    from jobCollection.crawler_agent import build_scrapy_command

    command = build_scrapy_command(
        python_executable="python",
        spider_name="boss_list_drission",
        allowed_spiders=["boss_list_drission"],
        task_id="201",
        spider_args={"taskUrl": "https://example.invalid/jobs", "unknown": "ignored"},
    )

    assert command == [
        "python",
        "-m",
        "scrapy",
        "crawl",
        "boss_list_drission",
        "-a",
        "task_id=201",
        "-a",
        "task_url=https://example.invalid/jobs",
    ]

    with pytest.raises(ValueError):
        build_scrapy_command(
            python_executable="python",
            spider_name="arbitrary-shell-command",
            allowed_spiders=["boss_list_drission"],
            task_id="201",
            spider_args={},
        )


def test_dry_run_agent_claims_work_and_reports_reserved_progress_metrics():
    from jobCollection.crawler_agent import AgentConfig, CrawlerAgent, DryRunRunner

    client = FakeControlClient(assignments=[assignment()])
    config = AgentConfig(
        worker_id="worker-1",
        worker_name="Test Worker",
        api_url="https://api.invalid/api/v2",
        token="secret",
        allowed_spiders=("boss_list_drission",),
        dry_run=True,
    )
    agent = CrawlerAgent(config, client=client, runner=DryRunRunner())

    agent.tick()
    agent.tick()

    assert agent.active_execution is not None
    assert client.worker_heartbeats[-1]["activeRuns"] == 1
    run_id, heartbeat = client.run_heartbeats[-1]
    assert run_id == "101"
    assert heartbeat["status"] == "running"
    assert heartbeat["metrics"]["itemsScraped"] > 0
    assert heartbeat["metrics"]["pagesProcessed"] > 0
    assert heartbeat["metrics"]["errors"] == 0
    assert client.events[0]["eventType"] == "run_started"


def test_dry_run_agent_acknowledges_pause_without_losing_checkpoint():
    from jobCollection.crawler_agent import AgentConfig, CrawlerAgent, DryRunRunner

    client = FakeControlClient(
        assignments=[assignment()],
        desired_states=[
            {"runId": "101", "desiredStatus": "paused", "status": "pausing"}
        ],
    )
    agent = CrawlerAgent(
        AgentConfig(worker_id="worker-1", token="secret", allowed_spiders=("boss_list_drission",)),
        client=client,
        runner=DryRunRunner(),
    )

    agent.tick()
    agent.tick()

    assert agent.active_execution is None
    assert client.run_heartbeats[-1][1]["status"] == "paused"
    assert client.run_heartbeats[-1][1]["checkpoint"]["dryRunTick"] >= 0
    assert not client.finished


def test_dry_run_agent_can_reclaim_a_resumed_run_and_stop_it():
    from jobCollection.crawler_agent import AgentConfig, CrawlerAgent, DryRunRunner

    client = FakeControlClient(
        assignments=[assignment("token-1"), assignment("token-2")],
        desired_states=[
            {"runId": "101", "desiredStatus": "paused", "status": "pausing"},
            {"runId": "101", "desiredStatus": "stopped", "status": "stopping"},
        ],
    )
    agent = CrawlerAgent(
        AgentConfig(worker_id="worker-1", token="secret", allowed_spiders=("boss_list_drission",)),
        client=client,
        runner=DryRunRunner(),
    )

    agent.tick()  # claim token-1
    agent.tick()  # pause token-1
    agent.tick()  # claim resumed run with token-2
    agent.tick()  # stop token-2

    assert agent.active_execution is None
    assert client.finished[-1][1]["status"] == "stopped"
    assert client.finished[-1][1]["executionToken"] == "token-2"


def test_agent_shutdown_stops_and_finalizes_an_active_execution():
    from jobCollection.crawler_agent import AgentConfig, CrawlerAgent, DryRunRunner

    client = FakeControlClient(assignments=[assignment()])
    agent = CrawlerAgent(
        AgentConfig(worker_id="worker-1", token="secret", allowed_spiders=("boss_list_drission",)),
        client=client,
        runner=DryRunRunner(),
    )
    agent.tick()

    agent.shutdown()

    assert agent.active_execution is None
    assert client.finished[-1][1]["status"] == "stopped"
    assert client.finished[-1][1]["errorMsg"] == "Crawler Agent shutting down"


def test_runner_start_failure_is_reported_immediately():
    from jobCollection.crawler_agent import AgentConfig, CrawlerAgent

    class FailingRunner:
        def start(self, assignment, config):
            raise RuntimeError("browser unavailable")

    client = FakeControlClient(assignments=[assignment()])
    agent = CrawlerAgent(
        AgentConfig(worker_id="worker-1", token="secret", allowed_spiders=("boss_list_drission",)),
        client=client,
        runner=FailingRunner(),
    )

    agent.tick()

    assert agent.active_execution is None
    assert client.finished[-1][1]["status"] == "failed"
    assert client.finished[-1][1]["errorMsg"] == "Crawler runner failed to start: RuntimeError"


def test_agent_backoff_is_bounded_and_does_not_require_stopping_execution():
    from jobCollection.crawler_agent import bounded_backoff

    assert [bounded_backoff(attempt) for attempt in range(6)] == [1, 2, 4, 8, 16, 30]
    assert bounded_backoff(20) == 30


def test_control_client_sends_execution_token_in_header_not_url():
    from jobCollection.crawler_agent import AgentConfig, CrawlerControlClient

    observed = {}

    def handler(request):
        observed["url"] = str(request.url)
        observed["token"] = request.headers.get("X-Crawler-Execution-Token")
        return httpx.Response(
            200,
            json={"runId": "101", "desiredStatus": "running", "status": "running"},
        )

    client = CrawlerControlClient(
        AgentConfig(api_url="https://api.invalid/api/v2", token="agent-secret")
    )
    client.client.close()
    client.client = httpx.Client(transport=httpx.MockTransport(handler))

    client.desired_state("101", "execution-secret")

    assert observed["token"] == "execution-secret"
    assert "execution-secret" not in observed["url"]
    assert "executionToken" not in observed["url"]


def test_process_log_redaction_removes_credentials_before_event_upload():
    from jobCollection.crawler_agent import redact_log_line

    sanitized = redact_log_line(
        "Authorization: Bearer secret-token Cookie: session=secret-cookie password=my-pass"
    )

    assert "secret-token" not in sanitized
    assert "secret-cookie" not in sanitized
    assert "my-pass" not in sanitized
    assert "[REDACTED]" in sanitized


def test_scrapy_telemetry_serialization_is_bounded_and_excludes_sensitive_fields():
    from jobCollection.jobCollection.extensions.crawler_telemetry import (
        serialize_telemetry,
    )
    from jobCollection.crawler_agent import parse_telemetry_line

    line = serialize_telemetry(
        "progress",
        metrics={
            "itemsScraped": 12,
            "pagesProcessed": 2,
            "customCounter": 7,
            "unsafeObject": object(),
        },
        checkpoint={"page": 2, "cursor": "abc"},
        payload={
            "reason": "periodic",
            "statusCode": 200,
            "cookies": "secret-cookie",
            "headers": {"Authorization": "secret"},
            "body": "private response body",
        },
        message="x" * 5000,
    )

    assert line.startswith("CRAWLER_EVENT ")
    assert len(line.encode("utf-8")) <= 32768
    assert "secret-cookie" not in line
    assert "Authorization" not in line
    assert "private response body" not in line
    payload = parse_telemetry_line(line)
    assert payload["metrics"] == {
        "itemsScraped": 12,
        "pagesProcessed": 2,
        "customCounter": 7,
    }
    assert payload["checkpoint"] == {"page": 2, "cursor": "abc"}
    assert len(payload["message"]) == 4000


def test_scrapy_settings_register_crawler_telemetry_extension():
    from jobCollection.jobCollection import settings

    assert (
        settings.EXTENSIONS[
            "jobCollection.extensions.crawler_telemetry.CrawlerTelemetryExtension"
        ]
        == 50
    )


def test_oversized_telemetry_remains_valid_json_after_truncation():
    from jobCollection.jobCollection.extensions.crawler_telemetry import serialize_telemetry
    from jobCollection.crawler_agent import parse_telemetry_line

    line = serialize_telemetry(
        "progress",
        metrics={f"dimension_{index}": "x" * 1000 for index in range(500)},
        payload={"reason": "oversized"},
    )

    assert len(line.encode("utf-8")) <= 32768
    parsed = parse_telemetry_line(line)
    assert parsed is not None
    assert parsed["payload"] == {"truncated": True}
