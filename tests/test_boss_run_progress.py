import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from jobCollection.items.boss_job_item import BossJobItem


class FakeTransaction:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        self.session.transaction_active = True
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.session.transaction_active = False
        if exc_type is None:
            self.session.commits += 1
        else:
            self.session.rollbacks += 1


class FakeAsyncSession:
    def __init__(self):
        self.transaction_active = False
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    def begin(self):
        return FakeTransaction(self)


class FakeProgressRepository:
    def __init__(self, run, account=None):
        self.run = run
        self.account = account
        self.run_jobs = {}
        self.events = []

    async def lock_run(self, session, run_id, execution_token):
        assert session.transaction_active
        assert run_id == self.run.id
        if execution_token != self.run.execution_token:
            raise PermissionError("crawler run execution token mismatch")
        return self.run

    async def existing_run_jobs(self, session, run_id, job_ids):
        return {
            job_id: self.run_jobs[job_id]
            for job_id in job_ids
            if job_id in self.run_jobs
        }

    async def upsert_run_jobs(
        self, session, run_id, task_id, job_ids, list_page=1, scroll_round=0
    ):
        for job_id, database_id in job_ids.items():
            self.run_jobs.setdefault(
                job_id,
                SimpleNamespace(
                    run_id=run_id,
                    task_id=task_id,
                    encrypt_job_id=job_id,
                    job_id=database_id,
                    detail_status="pending",
                    detail_attempts=0,
                    list_page=1,
                    scroll_round=0,
                    card_index=0,
                    last_error=None,
                    detail_completed_at=None,
                ),
            ).job_id = database_id
            row = self.run_jobs[job_id]
            row.list_page = list_page
            row.scroll_round = scroll_round

    async def count_run_jobs(self, session, run_id):
        return sum(row.run_id == run_id for row in self.run_jobs.values())

    async def lock_run_job(self, session, run_id, job_id):
        return self.run_jobs.get(job_id)

    async def count_run_job_statuses(self, session, run_id):
        counts = {"pending": 0, "processing": 0, "done": 0, "error": 0}
        for row in self.run_jobs.values():
            if row.run_id == run_id:
                counts[row.detail_status] += 1
        return counts

    async def add_event(self, session, event):
        self.events.append(event)

    async def lock_account(self, session, account_id):
        assert self.account is None or account_id == self.account.id
        return self.account


class FakeWriter:
    def __init__(self):
        self.job_ids = {}
        self.dispatched = []
        self.detail_error = None

    async def upsert_jobs(self, session, items):
        assert session.transaction_active
        result = {}
        for item in items:
            job_id = item["encrypt_job_id"]
            self.job_ids.setdefault(job_id, len(self.job_ids) + 100)
            result[job_id] = self.job_ids[job_id]
        return result

    async def update_details(self, session, items):
        assert session.transaction_active
        if self.detail_error is not None:
            raise self.detail_error
        return {
            item["encrypt_job_id"]: self.job_ids[item["encrypt_job_id"]]
            for item in items
        }

    def dispatch_es_sync(self, job_id):
        self.dispatched.append(job_id)


def make_progress_state():
    run = SimpleNamespace(
        id=11,
        task_id=22,
        worker_id="worker-1",
        account_id=33,
        proxy_identity_hash="proxy-hash",
        desired_status="running",
        status="running",
        metrics={},
        checkpoint={},
        execution_token="execution-token-1",
    )
    account = SimpleNamespace(
        id=33,
        status="in_use",
        cooldown_until=None,
    )
    session = FakeAsyncSession()
    repository = FakeProgressRepository(run, account)
    writer = FakeWriter()
    return run, account, session, repository, writer


def create_progress(loop, session, repository, writer):
    from jobCollection.boss.progress import SqlAlchemyRunProgress

    async def session_factory():
        return session

    return SqlAlchemyRunProgress(
        run_id=11,
        task_id=22,
        task_url="https://www.zhipin.com/web/geek/jobs?position=1",
        execution_token="execution-token-1",
        loop=loop,
        session_factory=session_factory,
        repository=repository,
        writer=writer,
    )


@pytest.mark.asyncio
async def test_pipeline_delegates_batch_transaction_to_shared_writer():
    from jobCollection.pipelines.boss_pipeline import BossJobPipeline

    writer = SimpleNamespace(write_batch=AsyncMock(return_value=[17]))
    pipeline = BossJobPipeline(writer=writer)
    item = BossJobItem(encrypt_job_id="job-1")

    await pipeline._db_write([item])

    writer.write_batch.assert_awaited_once()
    assert writer.write_batch.await_args.args[0] == [item]


@pytest.mark.asyncio
async def test_pipeline_drops_item_after_permanent_database_failure():
    from scrapy.exceptions import DropItem

    from jobCollection.pipelines.boss_pipeline import BossJobPipeline

    pipeline = BossJobPipeline()
    pipeline._write_batch_with_retries = AsyncMock(return_value=False)
    spider = SimpleNamespace(pipeline_failed=False)
    item = BossJobItem(encrypt_job_id="job-failed")

    with pytest.raises(DropItem, match="PostgreSQL write failed"):
        await pipeline.process_item(item, spider)

    assert spider.pipeline_failed is True


@pytest.mark.asyncio
async def test_submit_rejects_blocking_the_owner_loop():
    loop = asyncio.get_running_loop()
    run, _, session, repository, writer = make_progress_state()
    progress = create_progress(loop, session, repository, writer)

    with pytest.raises(RuntimeError, match="owner event loop"):
        progress.list_jobs_discovered(
            progress.task_url,
            ({"encryptJobId": "job-1"},),
            False,
        )

    await asyncio.to_thread(progress.close)


@pytest.mark.asyncio
async def test_close_rejects_blocking_owner_loop_without_closing_progress():
    loop = asyncio.get_running_loop()
    run, _, session, repository, writer = make_progress_state()
    progress = create_progress(loop, session, repository, writer)

    with pytest.raises(RuntimeError, match="owner event loop"):
        progress.close()

    assert progress._closing is False
    await asyncio.to_thread(progress.close)


@pytest.mark.asyncio
async def test_submit_cancels_owner_loop_future_after_timeout():
    from jobCollection.boss.progress import SqlAlchemyRunProgress

    loop = asyncio.get_running_loop()
    cancelled = asyncio.Event()
    progress = SqlAlchemyRunProgress(
        run_id=11,
        task_id=22,
        task_url="https://www.zhipin.com/web/geek/jobs?position=1",
        execution_token="execution-token-1",
        loop=loop,
        session_factory=AsyncMock(),
        timeout=0.01,
    )

    async def never_finishes(_jobs, _has_more, _page, _scroll):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    progress._persist_discovered = never_finishes

    with pytest.raises(TimeoutError):
        await asyncio.to_thread(
            progress.list_jobs_discovered,
            progress.task_url,
            ({"encryptJobId": "job-1"},),
            False,
        )

    await asyncio.wait_for(cancelled.wait(), timeout=1)
    await asyncio.to_thread(progress.close)


@pytest.mark.asyncio
async def test_sync_progress_uses_owner_loop_and_propagates_async_failure():
    from jobCollection.boss.progress import SqlAlchemyRunProgress

    loop = asyncio.get_running_loop()
    progress = SqlAlchemyRunProgress(
        run_id=11,
        task_id=22,
        task_url="https://www.zhipin.com/web/geek/jobs?position=1",
        execution_token="execution-token-1",
        loop=loop,
        session_factory=AsyncMock(),
    )
    owner_thread = None

    async def fail(_jobs, _has_more, _list_page, _scroll_round):
        nonlocal owner_thread
        import threading

        owner_thread = threading.get_ident()
        raise RuntimeError("database transaction failed")

    progress._persist_discovered = fail

    import threading

    browser_thread = await asyncio.to_thread(threading.get_ident)
    with pytest.raises(RuntimeError, match="database transaction failed"):
        await asyncio.to_thread(
            progress.list_jobs_discovered,
            progress.task_url,
            ({"encryptJobId": "job-1"},),
            False,
        )

    assert owner_thread == threading.get_ident()
    assert owner_thread != browser_thread
    await asyncio.to_thread(progress.close)


@pytest.mark.asyncio
async def test_progress_rejects_a_stale_execution_token_before_writing():
    loop = asyncio.get_running_loop()
    run, _, session, repository, writer = make_progress_state()
    progress = create_progress(loop, session, repository, writer)
    progress.execution_token = "superseded-token"

    with pytest.raises(PermissionError, match="execution token mismatch"):
        await asyncio.to_thread(
            progress.list_jobs_discovered,
            progress.task_url,
            ({"encryptJobId": "job-stale", "jobName": "Stale"},),
            False,
        )

    assert repository.run_jobs == {}
    assert writer.job_ids == {}
    await asyncio.to_thread(progress.close)


@pytest.mark.asyncio
async def test_progress_rejects_writes_after_run_is_terminal_even_with_current_token():
    from jobCollection.boss.progress import SqlAlchemyProgressRepository

    run = SimpleNamespace(id=11, execution_token="execution-token-1", status="succeeded")

    class Result:
        def scalar_one_or_none(self): return run
    class Session:
        async def execute(self, statement):
            assert statement._for_update_arg is not None
            return Result()

    with pytest.raises(PermissionError, match="terminal"):
        await SqlAlchemyProgressRepository().lock_run(
            Session(), 11, "execution-token-1"
        )


@pytest.mark.asyncio
async def test_list_discovery_upserts_jobs_and_pending_checkpoint_idempotently():
    loop = asyncio.get_running_loop()
    run, _, session, repository, writer = make_progress_state()
    progress = create_progress(loop, session, repository, writer)
    jobs = (
        {"encryptJobId": "job-1", "jobName": "Backend"},
        {"encryptJobId": "job-2", "jobName": "Frontend"},
    )

    await asyncio.to_thread(
        progress.list_jobs_discovered, progress.task_url, jobs, True
    )
    await asyncio.to_thread(
        progress.list_jobs_discovered, progress.task_url, jobs, False
    )

    assert set(repository.run_jobs) == {"job-1", "job-2"}
    assert {row.detail_status for row in repository.run_jobs.values()} == {
        "pending"
    }
    assert run.metrics["listSeenCount"] == 2
    assert run.metrics["jobsDiscovered"] == 2
    assert run.checkpoint == {
        "taskUrl": progress.task_url,
        "hasMore": False,
        "lastDiscoveredJobId": "job-2",
        "page": 1,
        "scrollRound": 0,
    }
    assert session.commits == 2
    assert writer.dispatched == [100, 101, 100, 101]
    await asyncio.to_thread(progress.close)


@pytest.mark.asyncio
async def test_list_count_increases_for_disjoint_scroll_batches():
    loop = asyncio.get_running_loop()
    run, _, session, repository, writer = make_progress_state()
    progress = create_progress(loop, session, repository, writer)

    for job_id in ("job-1", "job-2", "job-3"):
        await asyncio.to_thread(
            progress.list_jobs_discovered,
            progress.task_url,
            ({"encryptJobId": job_id, "jobName": job_id},),
            True,
        )

    assert run.metrics["listSeenCount"] == 3
    assert run.metrics["jobsDiscovered"] == 3
    await asyncio.to_thread(progress.close)


@pytest.mark.asyncio
async def test_empty_terminal_list_still_persists_resume_checkpoint():
    loop = asyncio.get_running_loop()
    run, _, session, repository, writer = make_progress_state()
    progress = create_progress(loop, session, repository, writer)

    await asyncio.to_thread(
        progress.list_jobs_discovered,
        progress.task_url,
        (),
        False,
        4,
        9,
    )

    assert run.checkpoint == {
        "taskUrl": progress.task_url,
        "hasMore": False,
        "page": 4,
        "scrollRound": 9,
    }
    assert session.commits == 1
    await asyncio.to_thread(progress.close)


@pytest.mark.asyncio
async def test_detail_is_done_only_after_job_write_and_duplicate_does_not_count_twice():
    from jobCollection.boss.parsers import BossJobDetail

    loop = asyncio.get_running_loop()
    run, _, session, repository, writer = make_progress_state()
    progress = create_progress(loop, session, repository, writer)
    await asyncio.to_thread(
        progress.list_jobs_discovered,
        progress.task_url,
        ({"encryptJobId": "job-1", "jobName": "Backend"},),
        False,
    )
    detail = BossJobDetail(
        encrypt_job_id="job-1",
        description="Build reliable services",
        data={"encryptJobId": "job-1", "skills": ["Python"]},
    )

    writer.detail_error = RuntimeError("job update failed")
    with pytest.raises(RuntimeError, match="job update failed"):
        await asyncio.to_thread(
            progress.detail_succeeded,
            progress.task_url,
            "job-1",
            detail,
        )
    assert repository.run_jobs["job-1"].detail_status == "pending"

    writer.detail_error = None
    await asyncio.to_thread(
        progress.detail_succeeded, progress.task_url, "job-1", detail
    )
    await asyncio.to_thread(
        progress.detail_succeeded, progress.task_url, "job-1", detail
    )

    run_job = repository.run_jobs["job-1"]
    assert run_job.detail_status == "done"
    assert run_job.detail_attempts == 1
    assert run_job.detail_completed_at is not None
    assert run.metrics["detailSuccessCount"] == 1
    assert run.metrics["itemsScraped"] == 1
    assert run.checkpoint["lastCompletedJobId"] == "job-1"
    assert session.rollbacks == 1
    await asyncio.to_thread(progress.close)


@pytest.mark.asyncio
async def test_detail_attempt_and_card_position_are_persisted_before_click():
    loop = asyncio.get_running_loop()
    run, _, session, repository, writer = make_progress_state()
    progress = create_progress(loop, session, repository, writer)
    await asyncio.to_thread(
        progress.list_jobs_discovered,
        progress.task_url,
        ({"encryptJobId": "job-1", "jobName": "Backend"},),
        False,
        4,
        7,
    )

    await asyncio.to_thread(
        progress.detail_started,
        progress.task_url,
        "job-1",
        2,
        4,
        7,
        3,
    )

    run_job = repository.run_jobs["job-1"]
    assert run_job.detail_status == "processing"
    assert run_job.detail_attempts == 2
    assert (run_job.list_page, run_job.scroll_round, run_job.card_index) == (
        4,
        7,
        3,
    )
    await asyncio.to_thread(progress.close)


@pytest.mark.asyncio
async def test_done_job_ignores_a_late_failure_without_metric_regression():
    from jobCollection.boss.parsers import BossJobDetail
    from jobCollection.boss.workflow import DetailFailure

    loop = asyncio.get_running_loop()
    run, _, session, repository, writer = make_progress_state()
    progress = create_progress(loop, session, repository, writer)
    await asyncio.to_thread(
        progress.list_jobs_discovered,
        progress.task_url,
        ({"encryptJobId": "job-1", "jobName": "Backend"},),
        False,
    )
    await asyncio.to_thread(
        progress.detail_succeeded,
        progress.task_url,
        "job-1",
        BossJobDetail("job-1", "Done", {"encryptJobId": "job-1"}),
    )

    await asyncio.to_thread(
        progress.detail_failed,
        DetailFailure(progress.task_url, "job-1", 3, "late timeout"),
    )

    run_job = repository.run_jobs["job-1"]
    assert run_job.detail_status == "done"
    assert run_job.last_error is None
    assert run.metrics["detailSuccessCount"] == 1
    assert run.metrics.get("detailFailedCount", 0) == 0
    await asyncio.to_thread(progress.close)


@pytest.mark.asyncio
async def test_late_success_corrects_error_fact_counts_and_keeps_attempts():
    from jobCollection.boss.parsers import BossJobDetail
    from jobCollection.boss.workflow import DetailFailure

    loop = asyncio.get_running_loop()
    run, _, session, repository, writer = make_progress_state()
    progress = create_progress(loop, session, repository, writer)
    await asyncio.to_thread(
        progress.list_jobs_discovered,
        progress.task_url,
        ({"encryptJobId": "job-1", "jobName": "Backend"},),
        False,
    )
    await asyncio.to_thread(
        progress.detail_failed,
        DetailFailure(progress.task_url, "job-1", 3, "timeout"),
    )

    await asyncio.to_thread(
        progress.detail_succeeded,
        progress.task_url,
        "job-1",
        BossJobDetail("job-1", "Recovered", {"encryptJobId": "job-1"}),
    )

    run_job = repository.run_jobs["job-1"]
    assert run_job.detail_status == "done"
    assert run_job.detail_attempts == 3
    assert run.metrics["detailSuccessCount"] == 1
    assert run.metrics["detailFailedCount"] == 0
    assert run.metrics["errors"] == 0
    await asyncio.to_thread(progress.close)


@pytest.mark.asyncio
async def test_third_detail_failure_is_error_and_records_task_url_once():
    from jobCollection.boss.workflow import DetailFailure

    loop = asyncio.get_running_loop()
    run, _, session, repository, writer = make_progress_state()
    progress = create_progress(loop, session, repository, writer)
    await asyncio.to_thread(
        progress.list_jobs_discovered,
        progress.task_url,
        ({"encryptJobId": "job-1", "jobName": "Backend"},),
        False,
    )
    failure = DetailFailure(
        task_url=progress.task_url,
        job_id="job-1",
        attempt=3,
        error="matching detail packet not received",
    )

    await asyncio.to_thread(progress.detail_failed, failure)
    await asyncio.to_thread(progress.detail_failed, failure)

    run_job = repository.run_jobs["job-1"]
    assert run_job.detail_status == "error"
    assert run_job.detail_attempts == 3
    assert run_job.last_error == "matching detail packet not received"
    assert run.metrics["detailFailedCount"] == 1
    assert run.metrics["errors"] == 1
    assert run.metrics["retries"] == 3
    assert run.checkpoint["lastFailure"] == {
        "taskUrl": progress.task_url,
        "jobId": "job-1",
        "attempt": 3,
        "error": "matching detail packet not received",
    }
    detail_events = [
        event for event in repository.events if event.event_type == "detail_failed"
    ]
    assert len(detail_events) == 1
    assert detail_events[0].payload["taskUrl"] == progress.task_url
    assert detail_events[0].payload["jobId"] == "job-1"
    await asyncio.to_thread(progress.close)


@pytest.mark.asyncio
async def test_three_started_attempts_then_failure_preserve_real_retry_count():
    from jobCollection.boss.workflow import DetailFailure

    loop = asyncio.get_running_loop()
    run, _, session, repository, writer = make_progress_state()
    progress = create_progress(loop, session, repository, writer)
    await asyncio.to_thread(
        progress.list_jobs_discovered,
        progress.task_url,
        ({"encryptJobId": "job-real-retry", "jobName": "Backend"},),
        False,
    )

    for attempt in (1, 2, 3):
        await asyncio.to_thread(
            progress.detail_started,
            progress.task_url,
            "job-real-retry",
            attempt,
            1,
            0,
            0,
        )
    await asyncio.to_thread(
        progress.detail_failed,
        DetailFailure(
            progress.task_url,
            "job-real-retry",
            3,
            "Cookie: a=1; session=private Authorization: Bearer auth-secret",
        ),
    )

    run_job = repository.run_jobs["job-real-retry"]
    serialized_checkpoint = str(run.checkpoint)
    assert run_job.detail_status == "error"
    assert run_job.detail_attempts == 3
    assert run.metrics["retries"] == 3
    assert "private" not in run_job.last_error
    assert "auth-secret" not in run_job.last_error
    assert "private" not in serialized_checkpoint
    assert "auth-secret" not in serialized_checkpoint
    await asyncio.to_thread(progress.close)


def test_progress_sanitizer_preserves_fact_counter_names():
    from jobCollection.boss.progress import SqlAlchemyRunProgress

    sanitized = SqlAlchemyRunProgress._safe_payload(
        {
            "responsesReceived": 12,
            "requestCount": 7,
            "response_body": "private",
            "request_headers": {"Cookie": "secret"},
        }
    )

    assert sanitized == {"responsesReceived": 12, "requestCount": 7}


def test_progress_text_sanitizer_covers_naked_bearer_and_request_or_generic_body():
    from jobCollection.boss.progress import SqlAlchemyRunProgress

    values = SqlAlchemyRunProgress._safe_payload(
        [
            "Bearer naked-secret",
            "request body: private-request",
            "body: private-generic",
            "The body is healthy and bearer plants grow here",
        ]
    )

    assert "naked-secret" not in values[0]
    assert "private-request" not in values[1]
    assert "private-generic" not in values[2]
    assert values[3] == "The body is healthy and bearer plants grow here"


def test_progress_event_message_uses_the_same_text_sanitizer():
    from jobCollection.boss.progress import SqlAlchemyRunProgress

    progress = object.__new__(SqlAlchemyRunProgress)
    progress.run_id = 101
    progress.worker_id = "worker-1"

    event = progress._event(
        "detail_error",
        "error",
        "Bearer message-secret request body: private-body",
        {},
        worker_id=None,
    )

    assert "message-secret" not in event.message
    assert "private-body" not in event.message


@pytest.mark.asyncio
async def test_pause_required_cools_account_releases_proxy_and_writes_safe_event():
    from jobCollection.boss.workflow import WorkflowEvent

    loop = asyncio.get_running_loop()
    run, account, session, repository, writer = make_progress_state()
    progress = create_progress(loop, session, repository, writer)

    await asyncio.to_thread(
        progress.emit,
        WorkflowEvent(
            kind="pause_required",
            task_url=progress.task_url,
            reason="captcha",
        ),
    )

    assert run.desired_status == "paused"
    assert run.status == "pausing"
    assert run.proxy_identity_hash is None
    assert account.status == "cooldown"
    assert account.cooldown_until > datetime.now(timezone.utc)
    event = repository.events[-1]
    assert event.event_type == "pause_required"
    assert event.level == "warning"
    assert event.payload == {
        "taskUrl": progress.task_url,
        "reason": "captcha",
    }
    assert "response" not in str(event.payload).lower()
    await asyncio.to_thread(progress.close)


def test_progress_safe_payload_redacts_sensitive_values_inside_error_strings():
    from jobCollection.boss.progress import SqlAlchemyRunProgress

    payload = SqlAlchemyRunProgress._safe_payload(
        {"error": "Cookie: a=1; session=secret Authorization: Bearer auth-secret"}
    )
    serialized = str(payload)
    assert "session=secret" not in serialized
    assert "auth-secret" not in serialized
    assert "[REDACTED]" in serialized


def test_job_list_conflict_updates_use_non_empty_guards():
    from datetime import datetime
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.dialects.postgresql import insert

    from common.databases.models.job import Job
    from jobCollection.boss.writer import BossJobWriter

    statement = insert(Job).values(encrypt_job_id="job-1", title="")
    values = BossJobWriter._list_conflict_updates(statement, datetime.utcnow())
    sql = str(
        statement.on_conflict_do_update(
            index_elements=["encrypt_job_id"], set_=values
        ).compile(dialect=postgresql.dialect())
    )
    assert "CASE WHEN" in sql
    assert "excluded.title" in sql
    assert "jobs.title" in sql
    assert "excluded.longitude" in sql


@pytest.mark.asyncio
async def test_desired_action_reads_pause_and_stop_from_database():
    loop = asyncio.get_running_loop()
    run, _, session, repository, writer = make_progress_state()
    progress = create_progress(loop, session, repository, writer)

    run.desired_status = "paused"
    assert await asyncio.to_thread(progress.desired_action) == "pause"
    run.desired_status = "stopped"
    assert await asyncio.to_thread(progress.desired_action) == "stop"
    run.desired_status = "running"
    assert await asyncio.to_thread(progress.desired_action) is None
    await asyncio.to_thread(progress.close)
