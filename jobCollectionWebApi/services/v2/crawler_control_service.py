from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import secrets
from typing import Any, Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
TERMINAL_RUN_STATUSES = {"stopped", "succeeded", "failed", "stale"}
MONOTONIC_METRICS = {
    "itemsScraped",
    "pagesProcessed",
    "responsesReceived",
    "errors",
    "captchaCount",
    "retries",
    "bytesReceived",
}


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
        if current_status in {"paused", "pausing"}:
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

        run = await db.get(CrawlerRun, task.latest_run_id) if task.latest_run_id else None
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
                run.worker_id = None
                run.execution_token = None
                run.pid = None
                run.finished_at = None
            elif transition.status == "stopped":
                run.finished_at = self._now()
                run.heartbeat_at = self._now()
                run.pid = None
                run.execution_token = None
                if run.worker_id:
                    worker = await db.get(CrawlerWorker, run.worker_id)
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
        worker = await db.get(CrawlerWorker, heartbeat.worker_id)
        if worker is None:
            worker = CrawlerWorker(id=heartbeat.worker_id)
        worker.name = heartbeat.name
        worker.hostname = heartbeat.hostname
        worker.platform = heartbeat.platform
        worker.status = "online"
        worker.capabilities = heartbeat.capabilities
        worker.max_concurrency = heartbeat.max_concurrency
        worker.active_runs = heartbeat.active_runs
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
        run = await self._authorized_run(db, run_id, heartbeat.execution_token)
        run.status = heartbeat.status
        run.pid = heartbeat.pid
        run.metrics = merge_run_metrics(run.metrics, heartbeat.metrics)
        run.checkpoint = dict(heartbeat.checkpoint or run.checkpoint or {})
        run.heartbeat_at = self._now()
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
        run = await self._authorized_run(db, run_id, batch.execution_token)
        for item in batch.events:
            db.add(
                CrawlerEvent(
                    run_id=run.id,
                    worker_id=run.worker_id,
                    event_type=item.event_type,
                    level=item.level,
                    message=item.message,
                    payload=item.payload,
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
        run = await self._authorized_run(db, run_id, payload.execution_token)
        run.status = payload.status
        run.desired_status = "stopped"
        run.exit_code = payload.exit_code
        run.error_msg = payload.error_msg
        run.metrics = merge_run_metrics(run.metrics, payload.metrics)
        run.checkpoint = dict(payload.checkpoint or run.checkpoint or {})
        run.finished_at = self._now()
        run.heartbeat_at = self._now()
        run.pid = None
        task = await db.get(BossCrawlTask, run.task_id)
        if task is not None:
            task.desired_status = "stopped"
            task.status = {"succeeded": "done", "failed": "error"}.get(payload.status, "stopped")
            task.error_msg = payload.error_msg
            task.last_crawl_time = legacy_task_timestamp(self._now())
            db.add(task)
        if run.worker_id:
            worker = await db.get(CrawlerWorker, run.worker_id)
            if worker is not None:
                worker.active_runs = max(0, int(worker.active_runs or 0) - 1)
                db.add(worker)
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
        workers = list(
            (
                await db.execute(
                    select(CrawlerWorker).where(CrawlerWorker.last_heartbeat_at < cutoff)
                )
            ).scalars().all()
        )
        for worker in workers:
            worker.status = "offline"
            worker.active_runs = 0
            db.add(worker)
        runs = list(
            (
                await db.execute(
                    select(CrawlerRun).where(
                        CrawlerRun.status.in_(ACTIVE_RUN_STATUSES),
                        CrawlerRun.heartbeat_at.is_not(None),
                        CrawlerRun.heartbeat_at < cutoff,
                    )
                )
            ).scalars().all()
        )
        for run in runs:
            run.status = "stale"
            run.desired_status = "stopped"
            run.finished_at = self._now()
            run.pid = None
            run.error_msg = "Crawler Agent heartbeat timed out"
            db.add(run)
        await db.flush()
        return {"workers_offline": len(workers), "runs_stale": len(runs)}

    async def _authorized_run(
        self,
        db: AsyncSession,
        run_id: int,
        execution_token: str,
    ) -> CrawlerRun:
        run = await db.get(CrawlerRun, run_id)
        if run is None:
            raise CrawlerNotFoundError(f"crawler run {run_id} not found")
        if not run.execution_token or not secrets.compare_digest(
            run.execution_token,
            execution_token,
        ):
            raise CrawlerExecutionTokenError("crawler run execution token mismatch")
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
