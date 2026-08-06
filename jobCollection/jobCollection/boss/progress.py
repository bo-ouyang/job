"""Durable browser-workflow progress and checkpoint persistence."""

import asyncio
import concurrent.futures
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from common.databases.PostgresManager import db_manager
from common.crawler_sanitization import redact_crawler_text
from common.databases.models.boss_crawl_run_job import BossCrawlRunJob
from common.databases.models.boss_crawler_account import BossCrawlerAccount
from common.databases.models.crawler_control import CrawlerEvent, CrawlerRun
from jobCollection.boss.parsers import build_boss_job_item
from jobCollection.boss.writer import BossJobWriter
from jobCollection.items.boss_job_item import BossJobDetailItem


class SqlAlchemyProgressRepository:
    """Small SQLAlchemy repository used by :class:`SqlAlchemyRunProgress`."""

    async def lock_run(self, session, run_id: int, execution_token: str):
        result = await session.execute(
            select(CrawlerRun)
            .where(
                CrawlerRun.id == run_id,
                CrawlerRun.execution_token == execution_token,
            )
            .with_for_update()
        )
        run = result.scalar_one_or_none()
        if run is None:
            raise PermissionError(
                f"crawler run {run_id} execution token mismatch"
            )
        if run.status in {"stopped", "succeeded", "failed", "stale"}:
            raise PermissionError(
                f"crawler run {run_id} is terminal; progress write rejected"
            )
        return run

    async def existing_run_jobs(
        self, session, run_id: int, job_ids: Sequence[str]
    ) -> Dict[str, BossCrawlRunJob]:
        if not job_ids:
            return {}
        result = await session.execute(
            select(BossCrawlRunJob).where(
                BossCrawlRunJob.run_id == run_id,
                BossCrawlRunJob.encrypt_job_id.in_(job_ids),
            )
        )
        return {row.encrypt_job_id: row for row in result.scalars()}

    async def upsert_run_jobs(
        self,
        session,
        run_id: int,
        task_id: int,
        job_ids: Dict[str, Optional[int]],
        list_page: int = 1,
        scroll_round: int = 0,
    ) -> None:
        if not job_ids:
            return
        rows = [
            {
                "run_id": run_id,
                "task_id": task_id,
                "encrypt_job_id": encrypt_job_id,
                "job_id": database_id,
                "detail_status": "pending",
                "detail_attempts": 0,
                "list_page": max(1, int(list_page or 1)),
                "scroll_round": max(0, int(scroll_round or 0)),
            }
            for encrypt_job_id, database_id in job_ids.items()
        ]
        statement = insert(BossCrawlRunJob).values(rows)
        statement = statement.on_conflict_do_update(
            constraint="uq_boss_crawl_run_job_run_encrypt_job",
            set_={
                "job_id": statement.excluded.job_id,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        await session.execute(statement)

    async def count_run_jobs(self, session, run_id: int) -> int:
        result = await session.execute(
            select(func.count())
            .select_from(BossCrawlRunJob)
            .where(BossCrawlRunJob.run_id == run_id)
        )
        return int(result.scalar_one())

    async def count_run_job_statuses(self, session, run_id: int) -> Dict[str, int]:
        result = await session.execute(
            select(BossCrawlRunJob.detail_status, func.count())
            .where(BossCrawlRunJob.run_id == run_id)
            .group_by(BossCrawlRunJob.detail_status)
        )
        counts = {"pending": 0, "processing": 0, "done": 0, "error": 0}
        counts.update({str(status): int(count) for status, count in result.all()})
        return counts

    async def lock_run_job(self, session, run_id: int, job_id: str):
        result = await session.execute(
            select(BossCrawlRunJob)
            .where(
                BossCrawlRunJob.run_id == run_id,
                BossCrawlRunJob.encrypt_job_id == job_id,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def add_event(self, session, event: CrawlerEvent) -> None:
        session.add(event)

    async def lock_account(self, session, account_id: int):
        result = await session.execute(
            select(BossCrawlerAccount)
            .where(BossCrawlerAccount.id == account_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()


class SqlAlchemyRunProgress:
    """Synchronous ProgressPort that executes async DB work on the owner loop.

    DrissionPage invokes these methods from its browser worker thread.  No
    async database method is ever run in that thread: every operation is
    submitted to the Spider's already-running event loop and its exception is
    synchronously propagated back to the workflow.
    """

    def __init__(
        self,
        *,
        run_id: int,
        task_id: int,
        task_url: str,
        execution_token: str,
        loop: asyncio.AbstractEventLoop,
        session_factory=None,
        repository=None,
        writer=None,
        worker_id: Optional[str] = None,
        major_name: str = "",
        timeout: float = 30.0,
        cooldown_seconds: Optional[int] = None,
    ) -> None:
        self.run_id = int(run_id)
        self.task_id = int(task_id)
        self.task_url = task_url
        if not execution_token:
            raise ValueError("execution_token is required")
        self.execution_token = execution_token
        self.loop = loop
        self.session_factory = session_factory or db_manager.get_session
        self.repository = repository or SqlAlchemyProgressRepository()
        self.writer = writer or BossJobWriter()
        self.worker_id = worker_id
        self.major_name = major_name
        self.timeout = timeout
        self.cooldown_seconds = cooldown_seconds or int(
            os.getenv("BOSS_ACCOUNT_COOLDOWN_SECONDS", "1800")
        )
        self._condition = threading.Condition()
        self._pending: set[concurrent.futures.Future] = set()
        self._closing = False

    def list_jobs_discovered(
        self,
        task_url: str,
        jobs: Sequence[dict],
        has_more: Optional[bool],
        list_page: int = 1,
        scroll_round: int = 0,
    ) -> None:
        if task_url != self.task_url:
            raise ValueError("list callback task URL does not match the run")
        self._submit(
            self._persist_discovered(
                tuple(jobs), has_more, list_page, scroll_round
            )
        )

    def jobs_discovered(
        self, job_ids: Sequence[str], has_more: Optional[bool]
    ) -> None:
        jobs = tuple({"encryptJobId": job_id} for job_id in job_ids)
        self._submit(self._persist_discovered(jobs, has_more, 1, 0))

    def detail_started(
        self,
        task_url: str,
        job_id: str,
        attempt: int,
        list_page: int,
        scroll_round: int,
        card_index: int,
    ) -> None:
        self._submit(
            self._persist_detail_started(
                task_url,
                job_id,
                attempt,
                list_page,
                scroll_round,
                card_index,
            )
        )

    def detail_succeeded(self, task_url, job_id, detail) -> None:
        self._submit(self._persist_detail_success(task_url, job_id, detail))

    def detail_failed(self, failure) -> None:
        self._submit(self._persist_detail_failure(failure))

    def emit(self, event) -> None:
        self._submit(self._persist_event(event))

    def desired_action(self) -> Optional[str]:
        return self._submit(self._read_desired_action())

    def close(self) -> None:
        self._guard_owner_loop()
        with self._condition:
            self._closing = True
            pending = tuple(self._pending)
        for future in pending:
            self._wait_future(future)

    def _guard_owner_loop(self) -> None:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is self.loop:
            raise RuntimeError("run progress cannot block its owner event loop")

    def _wait_future(self, future):
        try:
            return future.result(timeout=self.timeout)
        except concurrent.futures.TimeoutError as error:
            future.cancel()
            raise TimeoutError(
                f"run progress operation timed out after {self.timeout}s"
            ) from error

    def _submit(self, coroutine):
        try:
            self._guard_owner_loop()
        except RuntimeError:
            coroutine.close()
            raise
        with self._condition:
            if self._closing:
                coroutine.close()
                raise RuntimeError("run progress is closed")
            try:
                future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
            except Exception:
                coroutine.close()
                raise
            self._pending.add(future)

        def completed(done_future):
            with self._condition:
                self._pending.discard(done_future)
                self._condition.notify_all()

        future.add_done_callback(completed)
        return self._wait_future(future)

    async def _persist_discovered(
        self, jobs, has_more, list_page=1, scroll_round=0
    ):
        unique_jobs: Dict[str, dict] = {}
        for job in jobs:
            if not isinstance(job, dict):
                continue
            job_id = str(job.get("encryptJobId") or "").strip()
            if job_id:
                unique_jobs.setdefault(job_id, job)
        items = [
            build_boss_job_item(job, self.task_url, self.major_name)
            for job in unique_jobs.values()
        ]
        session = await self.session_factory()
        database_ids: Dict[str, int] = {}
        async with session:
            async with session.begin():
                run = await self.repository.lock_run(
                    session, self.run_id, self.execution_token
                )
                if unique_jobs:
                    database_ids = await self.writer.upsert_jobs(session, items)
                    if set(database_ids) != set(unique_jobs):
                        missing = sorted(set(unique_jobs).difference(database_ids))
                        raise RuntimeError(
                            "job upsert did not return database ids: "
                            + ", ".join(missing)
                        )
                    await self.repository.upsert_run_jobs(
                        session,
                        self.run_id,
                        self.task_id,
                        database_ids,
                        list_page,
                        scroll_round,
                    )
                metrics = dict(run.metrics or {})
                total = await self.repository.count_run_jobs(
                    session, self.run_id
                )
                metrics["listSeenCount"] = max(
                    int(metrics.get("listSeenCount") or 0), total
                )
                metrics["jobsDiscovered"] = max(
                    int(metrics.get("jobsDiscovered") or 0), total
                )
                run.metrics = metrics
                checkpoint = dict(run.checkpoint or {})
                checkpoint.update({
                    "taskUrl": self.task_url,
                    "hasMore": has_more,
                    "page": max(1, int(list_page or 1)),
                    "scrollRound": max(0, int(scroll_round or 0)),
                })
                if unique_jobs:
                    checkpoint["lastDiscoveredJobId"] = next(reversed(unique_jobs))
                run.checkpoint = checkpoint

        for database_id in database_ids.values():
            self.writer.dispatch_es_sync(database_id)

    async def _persist_detail_started(
        self,
        task_url,
        job_id,
        attempt,
        list_page,
        scroll_round,
        card_index,
    ):
        if task_url != self.task_url:
            raise ValueError("detail callback task URL does not match the run")
        normalized_id = str(job_id or "").strip()
        session = await self.session_factory()
        async with session:
            async with session.begin():
                run = await self.repository.lock_run(
                    session, self.run_id, self.execution_token
                )
                run_job = await self.repository.lock_run_job(
                    session, self.run_id, normalized_id
                )
                if run_job is None:
                    raise LookupError(
                        f"run job {self.run_id}/{normalized_id} was not discovered"
                    )
                if run_job.detail_status in {"done", "error"}:
                    return
                old_attempts = int(run_job.detail_attempts or 0)
                requested_attempt = max(1, min(int(attempt or 1), 3))
                run_job.detail_status = "processing"
                run_job.detail_attempts = max(
                    old_attempts,
                    requested_attempt,
                )
                metrics = dict(run.metrics or {})
                metrics["retries"] = int(metrics.get("retries") or 0) + max(
                    0, run_job.detail_attempts - old_attempts
                )
                run.metrics = metrics
                run_job.list_page = max(1, int(list_page or 1))
                run_job.scroll_round = max(0, int(scroll_round or 0))
                run_job.card_index = max(0, int(card_index or 0))
                checkpoint = dict(run.checkpoint or {})
                checkpoint.update(
                    {
                        "page": run_job.list_page,
                        "scrollRound": run_job.scroll_round,
                        "cardIndex": run_job.card_index,
                        "currentJobId": normalized_id,
                    }
                )
                run.checkpoint = checkpoint

    async def _persist_detail_success(self, task_url, job_id, detail):
        if task_url != self.task_url:
            raise ValueError("detail callback task URL does not match the run")
        normalized_id = str(job_id or "").strip()
        if detail.encrypt_job_id != normalized_id:
            raise ValueError("detail payload job ID does not match clicked job")
        detail_item = self._detail_item(detail)
        session = await self.session_factory()
        database_ids: Dict[str, int] = {}
        async with session:
            async with session.begin():
                run = await self.repository.lock_run(
                    session, self.run_id, self.execution_token
                )
                run_job = await self.repository.lock_run_job(
                    session, self.run_id, normalized_id
                )
                if run_job is None:
                    raise LookupError(
                        f"run job {self.run_id}/{normalized_id} was not discovered"
                    )

                # This must precede the terminal checkpoint transition.  Any
                # exception rolls back the transaction and leaves it pending.
                database_ids = await self.writer.update_details(
                    session, [detail_item]
                )
                database_id = database_ids.get(normalized_id)
                if database_id is None:
                    raise RuntimeError("detail writer did not return a job id")
                run_job.job_id = database_id
                run_job.detail_status = "done"
                run_job.detail_attempts = max(
                    int(run_job.detail_attempts or 0), 1
                )
                run_job.last_error = None
                run_job.detail_completed_at = (
                    run_job.detail_completed_at or datetime.now(timezone.utc)
                )
                await self._sync_fact_metrics(session, run)
                checkpoint = dict(run.checkpoint or {})
                checkpoint.update(
                    {
                        "taskUrl": self.task_url,
                        "lastCompletedJobId": normalized_id,
                    }
                )
                run.checkpoint = checkpoint

        for database_id in database_ids.values():
            self.writer.dispatch_es_sync(database_id)

    async def _persist_detail_failure(self, failure):
        if failure.task_url != self.task_url:
            raise ValueError("failure task URL does not match the run")
        job_id = str(failure.job_id or "").strip()
        error = self._safe_payload(
            str(failure.error or "unknown detail failure")[:2000]
        )
        requested_attempts = max(1, min(int(failure.attempt or 1), 3))
        session = await self.session_factory()
        async with session:
            async with session.begin():
                run = await self.repository.lock_run(
                    session, self.run_id, self.execution_token
                )
                run_job = await self.repository.lock_run_job(
                    session, self.run_id, job_id
                )
                if run_job is None:
                    await self.repository.upsert_run_jobs(
                        session, self.run_id, self.task_id, {job_id: None}
                    )
                    run_job = await self.repository.lock_run_job(
                        session, self.run_id, job_id
                    )
                if run_job is None:
                    raise RuntimeError("unable to create detail progress row")

                if run_job.detail_status == "done":
                    return

                old_attempts = int(run_job.detail_attempts or 0)
                new_attempts = max(old_attempts, requested_attempts)
                was_error = run_job.detail_status == "error"
                run_job.detail_attempts = new_attempts
                run_job.last_error = error
                if new_attempts >= 3:
                    run_job.detail_status = "error"

                metrics = dict(run.metrics or {})
                metrics["retries"] = int(metrics.get("retries") or 0) + max(
                    0, new_attempts - old_attempts
                )
                if run_job.detail_status == "error" and not was_error:
                    await self.repository.add_event(
                        session,
                        self._event(
                            "detail_failed",
                            "error",
                            "BOSS detail failed after retry limit",
                            {
                                "taskUrl": self.task_url,
                                "jobId": job_id,
                                "attempt": new_attempts,
                                "error": error,
                            },
                            worker_id=getattr(run, "worker_id", None),
                        ),
                    )
                run.metrics = metrics
                await self._sync_fact_metrics(session, run)
                checkpoint = dict(run.checkpoint or {})
                checkpoint["lastFailure"] = {
                    "taskUrl": self.task_url,
                    "jobId": job_id,
                    "attempt": new_attempts,
                    "error": error,
                }
                run.checkpoint = checkpoint

    async def _sync_fact_metrics(self, session, run) -> None:
        counts = await self.repository.count_run_job_statuses(
            session, self.run_id
        )
        metrics = dict(run.metrics or {})
        total = sum(counts.values())
        metrics["jobsDiscovered"] = total
        metrics["detailSuccessCount"] = counts["done"]
        metrics["detailFailedCount"] = counts["error"]
        metrics["itemsScraped"] = counts["done"]
        metrics["errors"] = counts["error"]
        run.metrics = metrics

    async def _persist_event(self, event):
        kind = str(event.kind or "workflow_event")[:50]
        reason = str(event.reason or "")[:500]
        task_url = str(event.task_url or self.task_url)[:2048]
        if task_url != self.task_url:
            raise ValueError("event task URL does not match the run")
        session = await self.session_factory()
        async with session:
            async with session.begin():
                run = await self.repository.lock_run(
                    session, self.run_id, self.execution_token
                )
                level = "warning" if kind == "pause_required" else "info"
                if kind == "pause_required":
                    run.desired_status = "paused"
                    if run.status in ("starting", "running"):
                        run.status = "pausing"
                    elif run.status == "queued":
                        run.status = "paused"
                    run.proxy_identity_hash = None
                    if reason != "operator_pause" and run.account_id is not None:
                        account = await self.repository.lock_account(
                            session, run.account_id
                        )
                        if account is not None:
                            account.status = "cooldown"
                            account.cooldown_until = datetime.now(
                                timezone.utc
                            ) + timedelta(seconds=self.cooldown_seconds)
                elif kind == "stop_requested" and run.status in (
                    "starting",
                    "running",
                    "pausing",
                    "paused",
                ):
                    run.status = "stopping"

                await self.repository.add_event(
                    session,
                    self._event(
                        kind,
                        level,
                        f"BOSS workflow: {reason}"[:4000],
                        {"taskUrl": task_url, "reason": reason},
                        worker_id=getattr(run, "worker_id", None),
                    ),
                )

    async def _read_desired_action(self):
        session = await self.session_factory()
        async with session:
            async with session.begin():
                run = await self.repository.lock_run(
                    session, self.run_id, self.execution_token
                )
                if run.desired_status == "paused":
                    return "pause"
                if run.desired_status == "stopped":
                    return "stop"
                return None

    @staticmethod
    def _detail_item(detail):
        data = detail.data if isinstance(detail.data, dict) else {}
        gps = data.get("gps") if isinstance(data.get("gps"), dict) else {}
        return BossJobDetailItem(
            encrypt_job_id=detail.encrypt_job_id,
            job_desc=detail.description,
            longitude=gps.get("longitude") or data.get("longitude"),
            latitude=gps.get("latitude") or data.get("latitude"),
            skills=data.get("skills") or data.get("jobLabels") or [],
        )

    def _event(
        self,
        event_type: str,
        level: str,
        message: str,
        payload: dict,
        *,
        worker_id: Optional[str],
    ) -> CrawlerEvent:
        return CrawlerEvent(
            run_id=self.run_id,
            worker_id=worker_id or self.worker_id,
            event_type=event_type[:50],
            level=level,
            message=redact_crawler_text(message, max_length=4000),
            payload=self._safe_payload(payload),
        )

    @classmethod
    def _safe_payload(cls, value: Any, depth: int = 0) -> Any:
        """Bound event JSON and remove credential/response-shaped fields."""
        if depth >= 4:
            return "[truncated]"
        if isinstance(value, dict):
            result = {}
            for raw_key, child in list(value.items())[:30]:
                key = str(raw_key)[:100]
                normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
                if normalized in {
                    "authorization", "body", "content", "cookie", "cookies",
                    "credential", "credentials", "header", "headers", "password",
                    "proxy", "requestbody", "requestcontent", "requestheaders",
                    "responsebody", "responsecontent", "responseheaders",
                    "responsetext", "secret", "setcookie", "token",
                } or normalized.endswith(
                    (
                        "authorization", "body", "cookie", "cookies", "credential",
                        "credentials", "header", "headers", "password", "proxy",
                        "secret", "token",
                    )
                ):
                    continue
                result[key] = cls._safe_payload(child, depth + 1)
            return result
        if isinstance(value, (list, tuple)):
            return [cls._safe_payload(child, depth + 1) for child in value[:30]]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return redact_crawler_text(value, max_length=2000)
