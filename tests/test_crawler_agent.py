import sys
import json
from types import SimpleNamespace
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
    assert heartbeat["metrics"]["pagesProcessed"] > 0
    assert "itemsScraped" not in heartbeat["metrics"]
    assert "errors" not in heartbeat["metrics"]
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


def test_runner_start_failure_finish_retries_without_reclaiming_assignment():
    from jobCollection.crawler_agent import AgentConfig, CrawlerAgent

    class FailingRunner:
        calls = 0
        def start(self, assignment, config):
            self.calls += 1
            raise RuntimeError("browser unavailable")

    class FlakyFinishClient(FakeControlClient):
        def __init__(self):
            super().__init__(assignments=[assignment()])
            self.claim_calls = 0
            self.finish_calls = 0
        def claim_run(self, payload):
            self.claim_calls += 1
            return super().claim_run(payload)
        def finish_run(self, run_id, payload):
            self.finish_calls += 1
            if self.finish_calls < 3:
                request = httpx.Request("POST", "https://api.invalid/runs/101/finish")
                response = httpx.Response(503, request=request)
                raise httpx.HTTPStatusError("temporary", request=request, response=response)
            return super().finish_run(run_id, payload)

    runner = FailingRunner()
    client = FlakyFinishClient()
    agent = CrawlerAgent(
        AgentConfig(worker_id="worker-1", token="secret", allowed_spiders=("boss_list_drission",)),
        client=client,
        runner=runner,
    )

    agent.tick()
    assert agent.active_assignment is not None
    agent.tick()
    assert agent.active_assignment is not None
    agent.tick()

    assert runner.calls == 1
    assert client.claim_calls == 1
    assert client.finish_calls == 3
    assert agent.active_assignment is None


def test_runner_start_failure_finish_gives_up_locally_after_bounded_network_retries():
    from jobCollection.crawler_agent import AgentConfig, CrawlerAgent

    class FailingRunner:
        def start(self, assignment, config):
            raise RuntimeError("browser unavailable")

    class OfflineFinishClient(FakeControlClient):
        def __init__(self):
            super().__init__(assignments=[assignment()])
            self.claim_calls = 0
            self.finish_calls = 0
        def claim_run(self, payload):
            self.claim_calls += 1
            return super().claim_run(payload)
        def finish_run(self, run_id, payload):
            self.finish_calls += 1
            raise httpx.ConnectError(
                "offline", request=httpx.Request("POST", "https://api.invalid/finish")
            )

    client = OfflineFinishClient()
    agent = CrawlerAgent(
        AgentConfig(worker_id="worker-1", token="secret", allowed_spiders=("boss_list_drission",)),
        client=client,
        runner=FailingRunner(),
    )

    agent.tick()
    agent.tick()
    agent.tick()

    assert client.finish_calls == 3
    assert client.claim_calls == 1
    assert agent.active_assignment is None
    assert agent.active_execution is None


def test_agent_heartbeat_omits_progress_authoritative_fact_metrics():
    from jobCollection.crawler_agent import AgentConfig, CrawlerAgent, DryRunRunner

    client = FakeControlClient(assignments=[assignment()])
    agent = CrawlerAgent(
        AgentConfig(worker_id="worker-1", token="secret", allowed_spiders=("boss_list_drission",)),
        client=client,
        runner=DryRunRunner(),
    )
    agent.tick()
    agent.tick()

    metrics = client.run_heartbeats[-1][1]["metrics"]
    assert "itemsScraped" not in metrics
    assert "errors" not in metrics
    assert metrics["responsesReceived"] > 0
    assert metrics["pagesProcessed"] > 0


def test_agent_terminates_process_and_clears_assignment_when_lease_is_lost():
    from jobCollection.crawler_agent import AgentConfig, CrawlerAgent

    class Execution:
        pid = 321
        terminated = False
        def terminate(self): self.terminated = True
        def metrics(self): return {}
        def checkpoint(self): return {"page": 2}
        def drain_events(self): return []
        def advance(self): return None
        def poll(self): return None

    execution = Execution()

    class Runner:
        def start(self, assignment, config): return execution

    client = FakeControlClient(assignments=[assignment()])
    request = httpx.Request("GET", "https://api.invalid/runs/101/desired-state")
    response = httpx.Response(403, request=request)

    def lost_lease(run_id, execution_token):
        raise httpx.HTTPStatusError("forbidden", request=request, response=response)

    client.desired_state = lost_lease
    agent = CrawlerAgent(
        AgentConfig(worker_id="worker-1", token="secret", allowed_spiders=("boss_list_drission",)),
        client=client,
        runner=Runner(),
    )

    agent.tick()
    agent.active_assignment["proxyLease"] = "proxy-secret"
    agent.tick()

    assert execution.terminated is True
    assert agent.active_execution is None
    assert agent.active_assignment is None


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


def test_subprocess_runner_injects_execution_token_into_spider_environment(monkeypatch):
    from jobCollection.crawler_agent import AgentConfig, SubprocessRunner

    observed = {}

    def fake_popen(command, **kwargs):
        observed["command"] = command
        observed["env"] = kwargs["env"]
        return SimpleNamespace(pid=123, stdout=[], poll=lambda: 0)

    monkeypatch.setattr("jobCollection.crawler_agent.subprocess.Popen", fake_popen)
    runner = SubprocessRunner()

    runner.start(
        assignment("fenced-token"),
        AgentConfig(
            worker_id="worker-1",
            token="agent-secret",
            allowed_spiders=("boss_list_drission",),
            dry_run=False,
        ),
    )

    assert observed["env"]["CRAWLER_RUN_ID"] == "101"
    assert observed["env"]["CRAWLER_EXECUTION_TOKEN"] == "fenced-token"


def test_process_log_redaction_removes_credentials_before_event_upload():
    from jobCollection.crawler_agent import redact_log_line

    sanitized = redact_log_line(
        "Authorization: Bearer secret-token Cookie: session=secret-cookie password=my-pass"
    )

    assert "secret-token" not in sanitized
    assert "secret-cookie" not in sanitized
    assert "my-pass" not in sanitized
    assert "[REDACTED]" in sanitized


def test_process_log_redaction_removes_complete_multi_value_cookie_header():
    from jobCollection.crawler_agent import redact_log_line

    sanitized = redact_log_line(
        "Cookie: a=1; b=secret-value; session=private Authorization: Bearer auth-secret"
    )

    assert "a=1" not in sanitized
    assert "secret-value" not in sanitized
    assert "private" not in sanitized
    assert "auth-secret" not in sanitized


def test_agent_text_redaction_covers_naked_bearer_and_request_or_generic_body():
    from jobCollection.crawler_agent import redact_log_line

    sanitized = redact_log_line(
        "Bearer naked-secret request body: private-request"
    )
    generic = redact_log_line("body: private-generic")
    ordinary = redact_log_line("The body is healthy and bearer plants grow here")

    assert "naked-secret" not in sanitized
    assert "private-request" not in sanitized
    assert "private-generic" not in generic
    assert ordinary == "The body is healthy and bearer plants grow here"


def test_raw_crawler_telemetry_is_sanitized_at_the_agent_boundary():
    from jobCollection.crawler_agent import parse_telemetry_line

    line = "CRAWLER_EVENT " + json.dumps(
        {
            "eventType": "progress",
            "level": "info",
            "message": (
                "Authorization: Bearer message-secret "
                "response body: private-response"
            ),
            "metrics": {"itemsScraped": 2, "accessToken": "metric-secret"},
            "checkpoint": {"page": 3, "cookies": "checkpoint-secret"},
            "payload": {
                "reason": "periodic",
                "nested": {
                    "proxyPassword": "proxy-secret",
                    "response_body": "payload-secret",
                },
                "safe": [1, {"Authorization": "nested-secret"}],
            },
        }
    )

    parsed = parse_telemetry_line(line)
    serialized = json.dumps(parsed, ensure_ascii=False)

    for secret in (
        "message-secret",
        "private-response",
        "metric-secret",
        "checkpoint-secret",
        "proxy-secret",
        "payload-secret",
        "nested-secret",
    ):
        assert secret not in serialized
    assert parsed["metrics"] == {"itemsScraped": 2}
    assert parsed["checkpoint"] == {"page": 3}
    assert parsed["payload"]["reason"] == "periodic"


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


def test_scrapy_telemetry_key_filter_is_precise_for_response_metrics():
    from jobCollection.jobCollection.extensions.crawler_telemetry import serialize_telemetry
    from jobCollection.crawler_agent import parse_telemetry_line

    parsed = parse_telemetry_line(
        serialize_telemetry(
            "progress",
            metrics={
                "responsesReceived": 12,
                "requestCount": 7,
                "responseTime": 1.5,
                "responseBody": "private-response",
                "requestHeaders": "private-request",
                "accessToken": "private-token",
            },
        )
    )

    assert parsed["metrics"] == {
        "responsesReceived": 12,
        "requestCount": 7,
        "responseTime": 1.5,
    }


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
