import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from agent.event_store import AgentEventStore
from agent.events import AgentEvent, AgentEventType, sanitize_event_data
from agent.locks import AgentRunLock
from agent.sse import format_sse_event, normalize_last_event_id, stream_agent_events


class FakeManager:
    def __init__(self, prefix="job"):
        self.prefix = prefix

    def make_key(self, key):
        return f"{self.prefix}:{key}" if self.prefix else key


class FakeRedis:
    def __init__(self):
        self.eval_calls = []
        self.set_calls = []
        self.range_rows = []
        self.read_rows = []
        self.eval_result = ["1710000000-1", 1]
        self.set_result = True

    async def eval(self, *args):
        self.eval_calls.append(args)
        return self.eval_result

    async def set(self, *args, **kwargs):
        self.set_calls.append((args, kwargs))
        return self.set_result

    async def xrange(self, *args, **kwargs):
        return self.range_rows

    async def xread(self, *args, **kwargs):
        return self.read_rows


def make_event(event_type=AgentEventType.RUN_STARTED, event_id="1710000000-1", sequence=1):
    return AgentEvent(
        event_id=event_id,
        sequence=sequence,
        event=event_type,
        run_id="100",
        conversation_id="200",
        data={"status": "running"},
        created_at=datetime(2026, 7, 27, 16, 0, 0),
    )


def test_event_store_applies_prefix_once_and_appends_atomically(monkeypatch):
    redis = FakeRedis()
    store = AgentEventStore(client=redis, manager=FakeManager())
    monkeypatch.setattr("agent.event_store.settings.AGENT_EVENT_MAXLEN", 500)
    monkeypatch.setattr("agent.event_store.settings.AGENT_EVENT_TTL_SECONDS", 86400)

    event = asyncio.run(
        store.append(
            run_id=100,
            conversation_id=200,
            event=AgentEventType.RUN_STARTED,
            data={"token": "secret", "status": "running"},
        )
    )

    call = redis.eval_calls[0]
    assert call[2] == "job:agent:run:100:events"
    assert call[3] == "job:agent:run:100:event_sequence"
    assert "job:job:" not in " ".join(str(item) for item in call)
    assert event.sequence == 1
    assert event.data == {"status": "running"}


def test_event_store_replays_strictly_after_event_id():
    redis = FakeRedis()
    redis.range_rows = [
        (
            "1710000000-2",
            {
                "sequence": "2",
                "event": "run_completed",
                "run_id": "100",
                "conversation_id": "200",
                "data": "{\"status\":\"completed\"}",
                "created_at": "2026-07-27T16:00:00",
            },
        )
    ]
    store = AgentEventStore(client=redis, manager=FakeManager())
    events = asyncio.run(store.replay(100, after_id="1710000000-1"))
    assert events[0].event == AgentEventType.RUN_COMPLETED
    assert events[0].sequence == 2


def test_run_lock_uses_tokenized_acquire_and_compare_delete(monkeypatch):
    redis = FakeRedis()
    lock = AgentRunLock(client=redis, manager=FakeManager())
    monkeypatch.setattr("agent.locks.settings.AGENT_LOCK_TTL_SECONDS", 90)
    token = asyncio.run(lock.acquire(100))
    redis.eval_result = 1
    released = asyncio.run(lock.release(100, token))

    assert token
    assert redis.set_calls[0][0][0] == "job:agent:run:100:lock"
    assert redis.set_calls[0][1] == {"nx": True, "ex": 90}
    assert released
    assert redis.eval_calls[-1][-1] == token


def test_sse_format_and_last_event_validation():
    frame = format_sse_event(make_event())
    assert frame.startswith("id: 1710000000-1\nevent: run_started\n")
    assert json.loads(frame.split("data: ", 1)[1].strip())["run_id"] == "100"
    assert normalize_last_event_id("1710000000-1") == "1710000000-1"
    assert normalize_last_event_id("bad-id") is None


def test_sse_replay_closes_after_terminal_event():
    class FakeStore:
        async def replay(self, run_id, after_id=None):
            return [make_event(AgentEventType.RUN_COMPLETED)]

        async def read_new(self, *args, **kwargs):
            raise AssertionError("terminal replay must close before blocking read")

    request = SimpleNamespace(is_disconnected=lambda: None)

    async def collect():
        return [
            frame
            async for frame in stream_agent_events(
                request,
                run_id=100,
                user_id=300,
                initial_status="completed",
                conversation_id=200,
                store=FakeStore(),
            )
        ]

    frames = asyncio.run(collect())
    assert len(frames) == 1
    assert "event: run_completed" in frames[0]


def test_event_sanitizer_removes_sensitive_fields():
    sanitized = sanitize_event_data(
        {"prompt": "hidden", "sql": "select 1", "api_key": "secret", "safe": "visible"}
    )
    assert sanitized == {"safe": "visible"}
