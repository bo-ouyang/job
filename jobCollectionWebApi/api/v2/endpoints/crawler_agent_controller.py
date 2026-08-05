import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from dependencies import get_db
from schemas.v2.crawler import (
    CrawlerDesiredStateResponse,
    CrawlerEventBatch,
    CrawlerRunAssignment,
    CrawlerRunClaimRequest,
    CrawlerRunFinishRequest,
    CrawlerRunHeartbeat,
    CrawlerRunView,
    CrawlerWorkerHeartbeat,
    CrawlerWorkerView,
)
from services.v2.crawler_control_service import (
    CrawlerExecutionTokenError,
    CrawlerNotFoundError,
    crawler_control_service,
)


router = APIRouter()


async def require_crawler_agent(
    crawler_agent_token: Optional[str] = Header(None, alias="X-Crawler-Agent-Token"),
) -> bool:
    configured = settings.CRAWLER_AGENT_TOKEN
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Crawler Agent API is disabled",
        )
    if not crawler_agent_token or not secrets.compare_digest(configured, crawler_agent_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Crawler Agent token",
        )
    return True


def _agent_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CrawlerNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=409, detail=str(exc))


@router.post("/workers/heartbeat", response_model=CrawlerWorkerView)
async def heartbeat_crawler_worker(
    payload: CrawlerWorkerHeartbeat,
    db: AsyncSession = Depends(get_db),
    _authorized=Depends(require_crawler_agent),
):
    return await crawler_control_service.heartbeat_worker(db, payload)


@router.post("/runs/claim", response_model=Optional[CrawlerRunAssignment])
async def claim_crawler_run(
    payload: CrawlerRunClaimRequest,
    db: AsyncSession = Depends(get_db),
    _authorized=Depends(require_crawler_agent),
):
    return await crawler_control_service.claim_run(
        db,
        worker_id=payload.worker_id,
        allowed_spiders=payload.allowed_spiders,
    )


@router.get("/runs/{run_id}/desired-state", response_model=CrawlerDesiredStateResponse)
async def get_crawler_desired_state(
    run_id: int,
    execution_token: str = Header(
        ...,
        alias="X-Crawler-Execution-Token",
        min_length=1,
        max_length=64,
    ),
    db: AsyncSession = Depends(get_db),
    _authorized=Depends(require_crawler_agent),
):
    try:
        return await crawler_control_service.desired_state(
            db,
            run_id=run_id,
            execution_token=execution_token,
        )
    except (CrawlerNotFoundError, CrawlerExecutionTokenError) as exc:
        raise _agent_error(exc) from exc


@router.post("/runs/{run_id}/heartbeat", response_model=CrawlerDesiredStateResponse)
async def heartbeat_crawler_run(
    run_id: int,
    payload: CrawlerRunHeartbeat,
    db: AsyncSession = Depends(get_db),
    _authorized=Depends(require_crawler_agent),
):
    try:
        return await crawler_control_service.heartbeat_run(db, run_id=run_id, heartbeat=payload)
    except (CrawlerNotFoundError, CrawlerExecutionTokenError) as exc:
        raise _agent_error(exc) from exc


@router.post("/runs/{run_id}/events")
async def append_crawler_events(
    run_id: int,
    payload: CrawlerEventBatch,
    db: AsyncSession = Depends(get_db),
    _authorized=Depends(require_crawler_agent),
):
    try:
        accepted = await crawler_control_service.append_events(db, run_id=run_id, batch=payload)
        return {"accepted": accepted}
    except (CrawlerNotFoundError, CrawlerExecutionTokenError) as exc:
        raise _agent_error(exc) from exc


@router.post("/runs/{run_id}/finish", response_model=CrawlerRunView)
async def finish_crawler_run(
    run_id: int,
    payload: CrawlerRunFinishRequest,
    db: AsyncSession = Depends(get_db),
    _authorized=Depends(require_crawler_agent),
):
    try:
        return await crawler_control_service.finish_run(db, run_id=run_id, payload=payload)
    except (CrawlerNotFoundError, CrawlerExecutionTokenError) as exc:
        raise _agent_error(exc) from exc
