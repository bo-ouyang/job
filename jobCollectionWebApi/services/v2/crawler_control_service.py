from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re
import secrets
from typing import Any, Dict, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.crawler_metrics import PROGRESS_FACT_METRICS
from common.crawler_sanitization import redact_crawler_text
from common.databases.models.admin_log import AdminLog
from common.databases.models.boss_crawl_task import BossCrawlTask
from common.databases.models.crawler_control import CrawlerEvent, CrawlerRun, CrawlerWorker
from config import settings
from schemas.v2.crawler import (
    CrawlerCommandResponse,
    CrawlerDesiredStateResponse,
    CrawlerEventBatch,
    CrawlerEventView,
    CrawlerListResponse,
    CrawlerOverviewResponse,
    CrawlerRunAssignment,
    CrawlerRunFinishRequest,
    CrawlerRunHeartbeat,
    CrawlerRunView,
    CrawlerTaskView,
    CrawlerWorkerHeartbeat,
    CrawlerWorkerView,
)


ACTIVE_RUN_STATUSES = {
    "queued",
    "starting",
    "running",
    "pausing",
    "paused",
    "stopping",
}
# Only statuses that represent an Agent-owned execution lease may expire from
# missing heartbeats.  Queued runs have not started and paused runs are
# deliberately waiting for an operator, so neither owns a live heartbeat.
STALE_RECONCILABLE_RUN_STATUSES = {
    "starting",
    "running",
    "pausing",
    "stopping",
}
TERMINAL_RUN_STATUSES = {"stopped", "succeeded", "failed", "stale"}
MONOTONIC_METRICS = {
    "itemsScraped",
    "pagesProcessed",
    "responsesReceived",
    "errors",
    "captchaCount",
    "retries",
    "bytesReceived",
    "listSeenCount",
    "jobsDiscovered",
    "uniqueCount",
    "duplicateCount",
    "detailSuccessCount",
    "detailFailedCount",
}
MONOTONIC_CHECKPOINTS = {
    "page",
    "listPage",
    "currentPage",
    "scrollRound",
    "currentScrollRound",
    "cardIndex",
}
WORKFLOW_CHECKPOINTS = {
    "taskUrl",
    "hasMore",
    "lastDiscoveredJobId",
    "lastCompletedJobId",
    "lastFailure",
}

_SENSITIVE_FIELD_NAMES = {
    "authorization",
    "body",
    "content",
    "cookie",
    "cookies",
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
    "setcookie",
    "token",
}
_SENSITIVE_FIELD_SUFFIXES = (
    "authorization",
    "body",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "header",
    "headers",
    "password",
    "proxy",
    "secret",
    "token",
)
def _is_sensitive_field(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
    return normalized in _SENSITIVE_FIELD_NAMES or normalized.endswith(
        _SENSITIVE_FIELD_SUFFIXES
    )


def sanitize_crawler_value(value: Any, *, depth: int = 0) -> Any:
    """Bound telemetry JSON and remove credential/request-shaped fields."""
    if depth >= 4:
        return "[truncated]"
    if isinstance(value, str):
        return redact_crawler_text(value, max_length=2000)
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for raw_key, child in list(value.items())[:30]:
            key = str(raw_key)[:100]
            if _is_sensitive_field(key):
                continue
            result[key] = sanitize_crawler_value(child, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [sanitize_crawler_value(child, depth=depth + 1) for child in value[:30]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:2000]


class CrawlerTransitionError(ValueError):
    pass


class CrawlerNotFoundError(LookupError):
    pass


class CrawlerExecutionTokenError(PermissionError):
    pass


@dataclass(frozen=True)
class CrawlerTransition:
    desired_status: str
    status: str


def transition_for_command(current_status: Optional[str], command: str) -> CrawlerTransition:
    if command == "start":
        if current_status is None or current_status in TERMINAL_RUN_STATUSES:
            return CrawlerTransition("running", "queued")
    elif command == "pause":
        if current_status in {"starting", "running"}:
            return CrawlerTransition("paused", "pausing")
    elif command == "resume":
        if current_status == "paused":
            return CrawlerTransition("running", "queued")
    elif command == "stop":
        if current_status in {"queued", "paused"}:
            return CrawlerTransition("stopped", "stopped")
        if current_status in {"starting", "running", "pausing", "stopping"}:
            return CrawlerTransition("stopped", "stopping")
    elif command == "retry":
        if current_status is None or current_status in {"failed", "stale", "stopped"}:
            return CrawlerTransition("running", "queued")
    raise CrawlerTransitionError(
        f"command {command!r} is invalid for crawler run status {current_status!r}"
    )


def merge_run_metrics(current: Optional[Dict[str, Any]], incoming: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = dict(current or {})
    for key, value in (incoming or {}).items():
        if key in MONOTONIC_METRICS and isinstance(value, (int, float)) and not isinstance(value, bool):
            previous = merged.get(key)
            if isinstance(previous, (int, float)) and not isinstance(previous, bool):
                merged[key] = max(previous, value)
            else:
                merged[key] = value
        else:
            merged[key] = value
    return merged


def merge_agent_heartbeat_metrics(
    current: Optional[Dict[str, Any]], incoming: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Merge operational observations while preserving Progress-owned facts."""

    operational = {
        key: value
        for key, value in (incoming or {}).items()
        if key not in PROGRESS_FACT_METRICS
    }
    return merge_run_metrics(current, operational)


def merge_run_checkpoint(
    current: Optional[Dict[str, Any]], incoming: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Merge an Agent snapshot without regressing workflow-owned progress."""

    merged = dict(current or {})
    for key, value in (incoming or {}).items():
        if key in WORKFLOW_CHECKPOINTS and key in merged:
            continue
        if key in MONOTONIC_CHECKPOINTS:
            previous = merged.get(key)
            if (
                isinstance(previous, (int, float))
                and not isinstance(previous, bool)
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            ):
                merged[key] = max(previous, value)
                continue
        merged[key] = value
    return merged


def heartbeat_run_status(
    current_status: str, desired_status: str, reported_status: str
) -> str:
    """Accept only cooperative forward acknowledgements from a heartbeat."""

    if current_status in TERMINAL_RUN_STATUSES:
        return current_status
    if desired_status == "paused":
        if reported_status == "paused" and current_status in {
            "starting",
            "running",
            "pausing",
            "paused",
        }:
            return "paused"
        return current_status
    if desired_status == "stopped":
        return current_status
    if (
        desired_status == "running"
        and reported_status == "running"
        and current_status in {"starting", "running"}
    ):
        return "running"
    return current_status


def finish_run_status(current_status: str, desired_status: str, reported_status: str) -> str:
    """Do not turn an operator-requested pause/stop into a successful run."""
    if reported_status == "succeeded" and (
        current_status in {"pausing", "paused", "stopping"}
        or desired_status in {"paused", "stopped"}
    ):
        return "stopped"
    return reported_status


def worker_is_online(last_heartbeat_at: datetime, *, now: datetime, stale_seconds: int) -> bool:
    if last_heartbeat_at.tzinfo is None:
        last_heartbeat_at = last_heartbeat_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return last_heartbeat_at >= now - timedelta(seconds=max(1, stale_seconds))


def worker_has_capacity(*, active_runs: int, max_concurrency: int) -> bool:
    return max(0, int(active_runs or 0)) < max(1, int(max_concurrency or 1))


def legacy_task_timestamp(value: datetime) -> datetime:
    """BossCrawlTask.last_crawl_time is an existing timezone-naive column."""

    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def spider_args_for_task(task: BossCrawlTask) -> Dict[str, Any]:
    """Build the typed Agent arguments while always preserving the durable task URL."""

    values = dict(getattr(task, "spider_args", None) or {})
    values["taskUrl"] = task.url
    return values


class CrawlerControlService:
    def __init__(self, *, now=None, stale_seconds: int = 45):
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.stale_seconds = stale_seconds

    async def command_task(
        self,
        db: AsyncSession,
        *,
        task_id: int,
        command: str,
        actor,
        ip_address: Optional[str] = None,
    ) -> CrawlerCommandResponse:
        task = (
            await db.execute(
                select(BossCrawlTask)
                .where(BossCrawlTask.id == task_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if task is None:
            raise CrawlerNotFoundError(f"crawler task {task_id} not found")

        run = None
        if task.latest_run_id:
            run = (
                await db.execute(
                    select(CrawlerRun)
                    .where(CrawlerRun.id == task.latest_run_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
        current_status = run.status if run else None
        transition = transition_for_command(current_status, command)

        if command in {"start", "retry"}:
            run = CrawlerRun(
                task_id=task.id,
                spider_name=task.spider_name or "boss_list_drission",
                spider_args=spider_args_for_task(task),
                desired_status=transition.desired_status,
                status=transition.status,
            )
            db.add(run)
            await db.flush()
            task.latest_run_id = run.id
        else:
            run.desired_status = transition.desired_status
            run.status = transition.status
            if command == "resume":
                # A paused run may still hold a worker lease.  Release it
                # while the run row is locked, before fencing the old token;
                # clearing worker_id first would make the capacity leak
                # impossible to repair idempotently.
                if run.worker_id:
                    worker = (
                        await db.execute(
                            select(CrawlerWorker)
                            .where(CrawlerWorker.id == run.worker_id)
                            .with_for_update()
                        )
                    ).scalar_one_or_none()
                    if worker is not None:
                        worker.active_runs = max(0, int(worker.active_runs or 0) - 1)
                        db.add(worker)
                run.worker_id = None
                run.execution_token = None
                run.pid = None
                run.finished_at = None
                run.heartbeat_at = self._now()
            elif transition.status == "stopped":
                run.finished_at = self._now()
                run.heartbeat_at = self._now()
                run.pid = None
                run.execution_token = None
                if run.worker_id:
                    worker = (
                        await db.execute(
                            select(CrawlerWorker)
                            .where(CrawlerWorker.id == run.worker_id)
                            .with_for_update()
                        )
                    ).scalar_one_or_none()
                    if worker is not None:
                        worker.active_runs = max(0, int(worker.active_runs or 0) - 1)
                        db.add(worker)

        task.desired_status = transition.desired_status
        task.status = transition.status
        if transition.status == "stopped":
            task.last_crawl_time = legacy_task_timestamp(self._now())
        db.add(task)
        db.add(
            AdminLog(
                user_id=getattr(actor, "id", None),
                username=getattr(actor, "username", None),
                action=f"CRAWLER_{command.upper()}",
                model_name="BossCrawlTask",
                object_id=str(task.id),
                details=json.dumps(
                    {"run_id": str(run.id), "desired_status": transition.desired_status},
                    ensure_ascii=False,
                ),
                ip_address=ip_address,
            )
        )
        await db.flush()
        return CrawlerCommandResponse(
            task_id=str(task.id),
            run_id=str(run.id),
            desired_status=run.desired_status,
            status=run.status,
        )

    async def heartbeat_worker(
        self,
        db: AsyncSession,
        heartbeat: CrawlerWorkerHeartbeat,
    ) -> CrawlerWorkerView:
        worker = (
            await db.execute(
                select(CrawlerWorker)
                .where(CrawlerWorker.id == heartbeat.worker_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if worker is None:
            worker = CrawlerWorker(id=heartbeat.worker_id)
            worker.active_runs = 0
        worker.name = heartbeat.name
        worker.hostname = heartbeat.hostname
        worker.platform = heartbeat.platform
        worker.status = "online"
        worker.capabilities = heartbeat.capabilities
        worker.max_concurrency = heartbeat.max_concurrency
        # active_runs is a server-side lease fact maintained by claim/finish.
        # A heartbeat carries a potentially stale client snapshot and must not
        # overwrite a locked value (especially with a lower count).
        worker.last_heartbeat_at = self._now()
        db.add(worker)
        await db.flush()
        return self._worker_view(worker)

    async def claim_run(
        self,
        db: AsyncSession,
        *,
        worker_id: str,
        allowed_spiders: list[str],
    ) -> Optional[CrawlerRunAssignment]:
        worker = (
            await db.execute(
                select(CrawlerWorker)
                .where(CrawlerWorker.id == worker_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if worker is None:
            raise CrawlerNotFoundError(f"crawler worker {worker_id} not found")
        if not worker_has_capacity(
            active_runs=worker.active_runs,
            max_concurrency=worker.max_concurrency,
        ):
            return None
        statement = (
            select(CrawlerRun)
            .where(CrawlerRun.status == "queued", CrawlerRun.desired_status == "running")
            .order_by(CrawlerRun.created_at.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if allowed_spiders:
            statement = statement.where(CrawlerRun.spider_name.in_(allowed_spiders))
        run = (await db.execute(statement)).scalar_one_or_none()
        if run is None:
            return None
        token = secrets.token_hex(32)
        run.worker_id = worker_id
        run.execution_token = token
        run.status = "starting"
        run.started_at = run.started_at or self._now()
        run.heartbeat_at = self._now()
        worker.active_runs = max(0, int(worker.active_runs or 0)) + 1
        db.add(run)
        db.add(worker)
        await db.flush()
        return CrawlerRunAssignment(
            run_id=str(run.id),
            task_id=str(run.task_id),
            spider_name=run.spider_name,
            spider_args=run.spider_args or {},
            execution_token=token,
            desired_status=run.desired_status,
            checkpoint=run.checkpoint or {},
        )

    async def desired_state(
        self,
        db: AsyncSession,
        *,
        run_id: int,
        execution_token: str,
    ) -> CrawlerDesiredStateResponse:
        run = await self._authorized_run(db, run_id, execution_token)
        return CrawlerDesiredStateResponse(
            run_id=str(run.id),
            desired_status=run.desired_status,
            status=run.status,
        )

    async def heartbeat_run(
        self,
        db: AsyncSession,
        *,
        run_id: int,
        heartbeat: CrawlerRunHeartbeat,
    ) -> CrawlerDesiredStateResponse:
        task_id = (
            await db.execute(
                select(CrawlerRun.task_id).where(CrawlerRun.id == run_id)
            )
        ).scalar_one_or_none()
        if task_id is None:
            raise CrawlerNotFoundError(f"crawler run {run_id} not found")
        task = (
            await db.execute(
                select(BossCrawlTask)
                .where(BossCrawlTask.id == task_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        run = await self._authorized_run(
            db, run_id, heartbeat.execution_token, for_update=True
        )
        if run.status in TERMINAL_RUN_STATUSES:
            return CrawlerDesiredStateResponse(
                run_id=str(run.id),
                desired_status=run.desired_status,
                status=run.status,
            )
        run.status = heartbeat_run_status(
            run.status, run.desired_status, heartbeat.status
        )
        run.pid = heartbeat.pid
        run.metrics = merge_agent_heartbeat_metrics(
            run.metrics, sanitize_crawler_value(heartbeat.metrics)
        )
        run.checkpoint = merge_run_checkpoint(
            run.checkpoint, sanitize_crawler_value(heartbeat.checkpoint)
        )
        run.heartbeat_at = self._now()
        if run.status == "paused":
            worker_id = run.worker_id
            if worker_id:
                worker = (
                    await db.execute(
                        select(CrawlerWorker)
                        .where(CrawlerWorker.id == worker_id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                ).scalar_one_or_none()
                if worker is not None:
                    worker.active_runs = max(
                        0, int(worker.active_runs or 0) - 1
                    )
                    db.add(worker)
            run.worker_id = None
            run.execution_token = None
            run.proxy_identity_hash = None
            run.pid = None
            if task is not None and (
                task.latest_run_id is None or task.latest_run_id == run.id
            ):
                task.status = "paused"
                task.desired_status = "paused"
                db.add(task)
        db.add(run)
        await db.flush()
        return CrawlerDesiredStateResponse(
            run_id=str(run.id),
            desired_status=run.desired_status,
            status=run.status,
        )

    async def append_events(
        self,
        db: AsyncSession,
        *,
        run_id: int,
        batch: CrawlerEventBatch,
    ) -> int:
        run = await self._authorized_run(
            db, run_id, batch.execution_token, for_update=True,
            reject_terminal=True,
        )
        for item in batch.events:
            db.add(
                CrawlerEvent(
                    run_id=run.id,
                    worker_id=run.worker_id,
                    event_type=item.event_type,
                    level=item.level,
                    message=sanitize_crawler_value(item.message),
                    payload=sanitize_crawler_value(item.payload),
                )
            )
        await db.flush()
        return len(batch.events)

    async def finish_run(
        self,
        db: AsyncSession,
        *,
        run_id: int,
        payload: CrawlerRunFinishRequest,
    ) -> CrawlerRunView:
        task_id = (
            await db.execute(
                select(CrawlerRun.task_id).where(CrawlerRun.id == run_id)
            )
        ).scalar_one_or_none()
        if task_id is None:
            raise CrawlerNotFoundError(f"crawler run {run_id} not found")
        task = (
            await db.execute(
                select(BossCrawlTask)
                .where(BossCrawlTask.id == task_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        run = await self._authorized_run(
            db, run_id, payload.execution_token, for_update=True
        )
        if run.status in TERMINAL_RUN_STATUSES:
            return CrawlerRunView.model_validate(run)
        run.status = finish_run_status(
            run.status, run.desired_status, payload.status
        )
        run.desired_status = "stopped"
        run.exit_code = payload.exit_code
        safe_error = sanitize_crawler_value(payload.error_msg)
        run.error_msg = safe_error
        run.metrics = merge_run_metrics(
            run.metrics, sanitize_crawler_value(payload.metrics)
        )
        run.checkpoint = merge_run_checkpoint(
            run.checkpoint, sanitize_crawler_value(payload.checkpoint)
        )
        run.finished_at = self._now()
        run.heartbeat_at = self._now()
        run.pid = None
        if task is not None and (
            task.latest_run_id is None or task.latest_run_id == run.id
        ):
            task.desired_status = "stopped"
            task.status = {"succeeded": "done", "failed": "error"}.get(run.status, "stopped")
            task.error_msg = safe_error
            task.last_crawl_time = legacy_task_timestamp(self._now())
            db.add(task)
        worker_id = run.worker_id
        if worker_id:
            worker = (
                await db.execute(
                    select(CrawlerWorker)
                    .where(CrawlerWorker.id == worker_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalar_one_or_none()
            if worker is not None:
                worker.active_runs = max(0, int(worker.active_runs or 0) - 1)
                db.add(worker)
        run.worker_id = None
        run.proxy_identity_hash = None
        db.add(run)
        await db.flush()
        await db.refresh(run)
        return CrawlerRunView.model_validate(run)

    async def get_overview(self, db: AsyncSession) -> CrawlerOverviewResponse:
        # Dashboard polling doubles as the reconciliation trigger, so stale
        # workers/runs are corrected even when the machine-side Agent is gone.
        await self.reconcile_stale(db)
        now = self._now()
        workers = list((await db.execute(select(CrawlerWorker))).scalars().all())
        active_runs = int(
            (await db.execute(select(func.count(CrawlerRun.id)).where(CrawlerRun.status.in_(ACTIVE_RUN_STATUSES)))).scalar_one()
        )
        failed_runs = int(
            (await db.execute(select(func.count(CrawlerRun.id)).where(CrawlerRun.status.in_({"failed", "stale"})))).scalar_one()
        )
        pending_tasks = int(
            (await db.execute(select(func.count(BossCrawlTask.id)).where(BossCrawlTask.status == "pending"))).scalar_one()
        )
        runs = list((await db.execute(select(CrawlerRun.metrics))).scalars().all())
        return CrawlerOverviewResponse(
            workers_online=sum(
                worker_is_online(worker.last_heartbeat_at, now=now, stale_seconds=self.stale_seconds)
                for worker in workers
            ),
            workers_total=len(workers),
            runs_active=active_runs,
            runs_failed=failed_runs,
            tasks_pending=pending_tasks,
            items_scraped=sum(int((metrics or {}).get("itemsScraped") or 0) for metrics in runs),
            pages_processed=sum(int((metrics or {}).get("pagesProcessed") or 0) for metrics in runs),
            errors=sum(int((metrics or {}).get("errors") or 0) for metrics in runs),
            updated_at=now,
        )

    async def list_workers(self, db: AsyncSession) -> CrawlerListResponse:
        await self.reconcile_stale(db)
        workers = list(
            (await db.execute(select(CrawlerWorker).order_by(CrawlerWorker.updated_at.desc()))).scalars().all()
        )
        return CrawlerListResponse(items=[self._worker_view(worker) for worker in workers], total=len(workers))

    async def list_tasks(self, db: AsyncSession, *, limit: int = 100, offset: int = 0) -> CrawlerListResponse:
        total = int((await db.execute(select(func.count(BossCrawlTask.id)))).scalar_one())
        tasks = list(
            (
                await db.execute(
                    select(BossCrawlTask)
                    .order_by(BossCrawlTask.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).scalars().all()
        )
        return CrawlerListResponse(
            items=[CrawlerTaskView.model_validate(task) for task in tasks],
            total=total,
        )

    async def get_run(self, db: AsyncSession, run_id: int) -> CrawlerRunView:
        run = await db.get(CrawlerRun, run_id)
        if run is None:
            raise CrawlerNotFoundError(f"crawler run {run_id} not found")
        return CrawlerRunView.model_validate(run)

    async def list_events(
        self,
        db: AsyncSession,
        *,
        run_id: int,
        after_id: Optional[int] = None,
        limit: int = 200,
    ) -> CrawlerListResponse:
        statement = select(CrawlerEvent).where(CrawlerEvent.run_id == run_id)
        if after_id is not None:
            statement = statement.where(CrawlerEvent.id > after_id)
        events = list(
            (
                await db.execute(statement.order_by(CrawlerEvent.id.asc()).limit(limit))
            ).scalars().all()
        )
        return CrawlerListResponse(
            items=[CrawlerEventView.model_validate(event) for event in events],
            total=len(events),
        )

    async def reconcile_stale(self, db: AsyncSession) -> Dict[str, int]:
        cutoff = self._now() - timedelta(seconds=self.stale_seconds)
        stale_worker_ids = set(
            (
                await db.execute(
                    select(CrawlerWorker.id).where(
                        CrawlerWorker.last_heartbeat_at < cutoff
                    )
                )
            ).scalars().all()
        )
        candidate_rows = (
            await db.execute(
                select(CrawlerRun.id, CrawlerRun.task_id).where(
                    CrawlerRun.status.in_(STALE_RECONCILABLE_RUN_STATUSES),
                    or_(
                        CrawlerRun.worker_id.in_(stale_worker_ids)
                        if stale_worker_ids
                        else False,
                        (
                            CrawlerRun.heartbeat_at.is_not(None)
                            & (CrawlerRun.heartbeat_at < cutoff)
                        ),
                    ),
                )
            )
        ).all()

        offline_worker_ids = set()
        stale_count = 0
        for run_id, task_id in sorted(candidate_rows, key=lambda row: (row[1], row[0])):
            task = (
                await db.execute(
                    select(BossCrawlTask)
                    .where(BossCrawlTask.id == task_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalar_one_or_none()
            run = (
                await db.execute(
                    select(CrawlerRun)
                    .where(CrawlerRun.id == run_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalar_one_or_none()
            if run is None or run.status not in STALE_RECONCILABLE_RUN_STATUSES:
                continue

            worker_id = run.worker_id
            worker = None
            if worker_id:
                worker = (
                    await db.execute(
                        select(CrawlerWorker)
                        .where(CrawlerWorker.id == worker_id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                ).scalar_one_or_none()

            run_timed_out = bool(
                run.heartbeat_at is not None and run.heartbeat_at < cutoff
            )
            worker_timed_out = bool(
                worker is not None
                and worker.last_heartbeat_at is not None
                and worker.last_heartbeat_at < cutoff
            )
            if not (run_timed_out or worker_timed_out):
                continue

            if worker is not None:
                worker.active_runs = max(0, int(worker.active_runs or 0) - 1)
                if worker_timed_out:
                    worker.status = "offline"
                    offline_worker_ids.add(worker.id)
                db.add(worker)

            run.status = "stale"
            run.desired_status = "stopped"
            run.finished_at = self._now()
            run.heartbeat_at = self._now()
            run.pid = None
            run.error_msg = "Crawler Agent heartbeat timed out"
            run.worker_id = None
            run.execution_token = None
            run.proxy_identity_hash = None
            db.add(run)
            if task is not None and (
                task.latest_run_id is None or task.latest_run_id == run.id
            ):
                task.status = "error"
                task.desired_status = "stopped"
                task.error_msg = run.error_msg
                task.last_crawl_time = legacy_task_timestamp(self._now())
                db.add(task)
            stale_count += 1

        for worker_id in sorted(stale_worker_ids.difference(offline_worker_ids)):
            worker = (
                await db.execute(
                    select(CrawlerWorker)
                    .where(CrawlerWorker.id == worker_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalar_one_or_none()
            if (
                worker is None
                or worker.status == "offline"
                or worker.last_heartbeat_at is None
                or worker.last_heartbeat_at >= cutoff
            ):
                continue
            worker.status = "offline"
            db.add(worker)
            offline_worker_ids.add(worker.id)
        await db.flush()
        return {
            "workers_offline": len(offline_worker_ids),
            "runs_stale": stale_count,
        }

    async def _authorized_run(
        self,
        db: AsyncSession,
        run_id: int,
        execution_token: str,
        *,
        for_update: bool = False,
        reject_terminal: bool = False,
    ) -> CrawlerRun:
        statement = (
            select(CrawlerRun)
            .where(CrawlerRun.id == run_id)
            .execution_options(populate_existing=True)
        )
        if for_update:
            statement = statement.with_for_update()
        run = (await db.execute(statement)).scalar_one_or_none()
        if run is None:
            raise CrawlerNotFoundError(f"crawler run {run_id} not found")
        if not run.execution_token or not secrets.compare_digest(
            run.execution_token,
            execution_token,
        ):
            raise CrawlerExecutionTokenError("crawler run execution token mismatch")
        if reject_terminal and run.status in TERMINAL_RUN_STATUSES:
            raise CrawlerExecutionTokenError(
                "crawler run is terminal; execution token is no longer writable"
            )
        return run

    def _worker_view(self, worker: CrawlerWorker) -> CrawlerWorkerView:
        return CrawlerWorkerView(
            id=worker.id,
            name=worker.name,
            hostname=worker.hostname,
            platform=worker.platform,
            status=worker.status,
            online=worker_is_online(
                worker.last_heartbeat_at,
                now=self._now(),
                stale_seconds=self.stale_seconds,
            ),
            capabilities=worker.capabilities or {},
            max_concurrency=worker.max_concurrency,
            active_runs=worker.active_runs,
            last_heartbeat_at=worker.last_heartbeat_at,
        )


crawler_control_service = CrawlerControlService(
    stale_seconds=settings.CRAWLER_AGENT_STALE_SECONDS,
)
