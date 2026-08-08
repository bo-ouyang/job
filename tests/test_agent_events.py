import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from agent.event_store import AgentEventPublisher, AgentEventStore
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


class RoundTripRedis(FakeRedis):
    """Minimal Redis Stream double that round-trips the real store payload."""

    async def eval(self, *args):
        self.eval_calls.append(args)
        sequence = len(self.range_rows) + 1
        event_id = f"1710000000-{sequence}"
        self.range_rows.append(
            (
                event_id,
                {
                    "sequence": str(sequence),
                    "event": args[7],
                    "run_id": args[8],
                    "conversation_id": args[9],
                    "data": args[10],
                    "created_at": args[11],
                },
            )
        )
        return [event_id, sequence]


class GateAwareRedis(FakeRedis):
    """Emulate the atomic gate contract exposed by the append Lua script."""

    def __init__(self):
        super().__init__()
        self.sequence = 0
        self.terminal = None
        self.active_stream_id = None
        self.expirations = {}

    async def eval(self, *args):
        self.eval_calls.append(args)
        assert args[1] == 4
        stream_key, sequence_key, terminal_key, active_stream_key = args[2:6]
        event_name = args[7]
        run_id = args[8]
        conversation_id = args[9]
        data = args[10]
        created_at = args[11]
        ttl = int(args[12])
        stream_id = args[13]
        stream_events = {"message_started", "message_delta", "message_completed"}
        terminal_events = {"run_completed", "run_failed", "run_cancelled"}

        terminal_rejects_all = "== 1 and is_stream_event" not in args[0]
        if self.terminal and (terminal_rejects_all or event_name in stream_events):
            return ["rejected", self.sequence]
        if event_name == "message_started":
            self.active_stream_id = stream_id
            self.expirations[active_stream_key] = ttl
        elif event_name in {"message_delta", "message_completed"}:
            if not stream_id or stream_id != self.active_stream_id:
                return ["rejected", self.sequence]
        if event_name in terminal_events:
            self.terminal = event_name
            self.expirations[terminal_key] = ttl

        self.sequence += 1
        event_id = f"1710000000-{self.sequence}"
        self.range_rows.append(
            (
                event_id,
                {
                    "sequence": str(self.sequence),
                    "event": event_name,
                    "run_id": run_id,
                    "conversation_id": conversation_id,
                    "data": data,
                    "created_at": created_at,
                },
            )
        )
        self.expirations[stream_key] = ttl
        self.expirations[sequence_key] = ttl
        return [event_id, self.sequence]


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


def test_event_store_replays_message_deltas_in_sequence_order():
    redis = FakeRedis()
    redis.range_rows = [
        (
            "1710000000-2",
            {
                "sequence": "2",
                "event": "message_started",
                "run_id": "100",
                "conversation_id": "200",
                "data": '{"streamMode":"validated_markdown_chunks"}',
                "created_at": "2026-07-27T16:00:00",
            },
        ),
        (
            "1710000000-3",
            {
                "sequence": "3",
                "event": "message_delta",
                "run_id": "100",
                "conversation_id": "200",
                "data": '{"index":0,"delta":"第一段。"}',
                "created_at": "2026-07-27T16:00:01",
            },
        ),
        (
            "1710000000-4",
            {
                "sequence": "4",
                "event": "message_delta",
                "run_id": "100",
                "conversation_id": "200",
                "data": '{"index":1,"delta":"Second paragraph."}',
                "created_at": "2026-07-27T16:00:02",
            },
        ),
    ]
    store = AgentEventStore(client=redis, manager=FakeManager())

    events = asyncio.run(store.replay(100, after_id="1710000000-1"))

    assert [event.event for event in events] == [
        AgentEventType.MESSAGE_STARTED,
        AgentEventType.MESSAGE_DELTA,
        AgentEventType.MESSAGE_DELTA,
    ]
    assert [event.sequence for event in events] == [2, 3, 4]
    assert "".join(event.data["delta"] for event in events[1:]) == "第一段。Second paragraph."


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


def test_sse_formats_message_delta_without_losing_unicode():
    event = make_event(AgentEventType.MESSAGE_DELTA)
    event.data = {"index": 0, "delta": "岗位建议 🚀"}

    frame = format_sse_event(event)

    assert "event: message_delta\n" in frame
    assert json.loads(frame.split("data: ", 1)[1].strip())["data"] == {
        "index": 0,
        "delta": "岗位建议 🚀",
    }


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


def test_event_sanitizer_preserves_final_message_content_for_snapshot_fallback():
    content = "职业分析正文。" * 300

    sanitized = sanitize_event_data({"content": content, "status": "completed"})

    assert sanitized["content"] == content


def test_real_event_publisher_store_and_replay_preserve_large_completed_content():
    redis = RoundTripRedis()
    store = AgentEventStore(client=redis, manager=FakeManager())
    publisher = AgentEventPublisher(store)
    content = "职业分析正文与行动建议。🚀\n" * 1200

    async def publish_and_replay():
        published = await publisher.publish(
            run_id=100,
            conversation_id=200,
            event=AgentEventType.MESSAGE_COMPLETED,
            data={
                "streamId": "attempt-one",
                "content": content,
                "result": {"summary": "完成"},
                "deltaCount": 80,
            },
        )
        replayed = await store.replay(100)
        return published, replayed

    published, replayed = asyncio.run(publish_and_replay())

    assert len(content) > 12000
    assert published.data["content"] == content
    assert replayed[0].data["content"] == content


def test_atomic_event_gate_rejects_delta_after_cancel_without_advancing_sequence(monkeypatch):
    redis = GateAwareRedis()
    store = AgentEventStore(client=redis, manager=FakeManager())
    publisher = AgentEventPublisher(store)
    monkeypatch.setattr("agent.event_store.settings.AGENT_EVENT_TTL_SECONDS", 86400)

    async def publish_sequence():
        started = await publisher.publish(
            run_id=100,
            conversation_id=200,
            event=AgentEventType.MESSAGE_STARTED,
            data={"streamId": "attempt-one"},
        )
        cancelled = await publisher.publish(
            run_id=100,
            conversation_id=200,
            event=AgentEventType.RUN_CANCELLED,
            data={"status": "cancelled"},
        )
        rejected = await publisher.publish(
            run_id=100,
            conversation_id=200,
            event=AgentEventType.MESSAGE_DELTA,
            data={"streamId": "attempt-one", "index": 0, "delta": "late"},
        )
        return started, cancelled, rejected, await store.replay(100)

    started, cancelled, rejected, replayed = asyncio.run(publish_sequence())

    assert started.sequence == 1
    assert cancelled.sequence == 2
    assert rejected is None
    assert redis.sequence == 2
    assert [event.event for event in replayed] == [
        AgentEventType.MESSAGE_STARTED,
        AgentEventType.RUN_CANCELLED,
    ]
    assert redis.expirations[store.terminal_key(100)] == 86400


def test_atomic_event_gate_rejects_old_attempt_after_new_stream_started(monkeypatch):
    redis = GateAwareRedis()
    store = AgentEventStore(client=redis, manager=FakeManager())
    publisher = AgentEventPublisher(store)
    monkeypatch.setattr("agent.event_store.settings.AGENT_EVENT_TTL_SECONDS", 43200)

    async def publish_sequence():
        await publisher.publish(
            run_id=100,
            conversation_id=200,
            event=AgentEventType.MESSAGE_STARTED,
            data={"streamId": "attempt-one"},
        )
        await publisher.publish(
            run_id=100,
            conversation_id=200,
            event=AgentEventType.MESSAGE_STARTED,
            data={"streamId": "attempt-two"},
        )
        stale = await publisher.publish(
            run_id=100,
            conversation_id=200,
            event=AgentEventType.MESSAGE_DELTA,
            data={"streamId": "attempt-one", "index": 0, "delta": "stale"},
        )
        current = await publisher.publish(
            run_id=100,
            conversation_id=200,
            event=AgentEventType.MESSAGE_DELTA,
            data={"streamId": "attempt-two", "index": 0, "delta": "current"},
        )
        return stale, current

    stale, current = asyncio.run(publish_sequence())

    assert stale is None
    assert current.sequence == 3
    assert redis.sequence == 3
    assert redis.expirations[store.active_stream_key(100)] == 43200


def test_atomic_event_gate_keeps_the_first_terminal_event_without_duplicates():
    redis = GateAwareRedis()
    store = AgentEventStore(client=redis, manager=FakeManager())
    publisher = AgentEventPublisher(store)

    async def publish_sequence():
        started = await publisher.publish(
            run_id=100,
            conversation_id=200,
            event=AgentEventType.MESSAGE_STARTED,
            data={"streamId": "attempt-one"},
        )
        completed = await publisher.publish(
            run_id=100,
            conversation_id=200,
            event=AgentEventType.RUN_COMPLETED,
            data={"status": "completed"},
        )
        late_failed = await publisher.publish(
            run_id=100,
            conversation_id=200,
            event=AgentEventType.RUN_FAILED,
            data={"status": "failed"},
        )
        late_cancelled = await publisher.publish(
            run_id=100,
            conversation_id=200,
            event=AgentEventType.RUN_CANCELLED,
            data={"status": "cancelled"},
        )
        duplicate_completed = await publisher.publish(
            run_id=100,
            conversation_id=200,
            event=AgentEventType.RUN_COMPLETED,
            data={"status": "completed"},
        )
        return (
            started,
            completed,
            late_failed,
            late_cancelled,
            duplicate_completed,
            await store.replay(100),
        )

    (
        started,
        completed,
        late_failed,
        late_cancelled,
        duplicate_completed,
        replayed,
    ) = asyncio.run(publish_sequence())

    assert started.sequence == 1
    assert completed.sequence == 2
    assert late_failed is None
    assert late_cancelled is None
    assert duplicate_completed is None
    assert redis.sequence == 2
    assert redis.terminal == "run_completed"
    assert [event.event for event in replayed] == [
        AgentEventType.MESSAGE_STARTED,
        AgentEventType.RUN_COMPLETED,
    ]
