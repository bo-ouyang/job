from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_db
from schemas.v2.crawler import (
    CrawlerCommandResponse,
    CrawlerListResponse,
    CrawlerOverviewResponse,
    CrawlerRunView,
    CrawlerTaskCommandRequest,
)
from services.v2.crawler_control_service import (
    CrawlerNotFoundError,
    CrawlerTransitionError,
    crawler_control_service,
)


router = APIRouter()


async def require_crawler_admin(current_user=Depends(get_current_user)):
    role = getattr(getattr(current_user, "role", None), "value", getattr(current_user, "role", None))
    if role not in {"admin", "super_admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅管理员可以控制爬虫",
        )
    return current_user


@router.get("/overview", response_model=CrawlerOverviewResponse)
async def get_crawler_overview(
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_crawler_admin),
):
    return await crawler_control_service.get_overview(db)


@router.get("/workers", response_model=CrawlerListResponse)
async def list_crawler_workers(
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_crawler_admin),
):
    return await crawler_control_service.list_workers(db)


@router.get("/tasks", response_model=CrawlerListResponse)
async def list_crawler_tasks(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_crawler_admin),
):
    return await crawler_control_service.list_tasks(db, limit=limit, offset=offset)


@router.post("/tasks/{task_id}/commands", response_model=CrawlerCommandResponse)
async def command_crawler_task(
    task_id: int,
    payload: CrawlerTaskCommandRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_crawler_admin),
):
    try:
        return await crawler_control_service.command_task(
            db,
            task_id=task_id,
            command=payload.action,
            actor=admin,
            ip_address=request.client.host if request.client else None,
        )
    except CrawlerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CrawlerTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/runs/{run_id}", response_model=CrawlerRunView)
async def get_crawler_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_crawler_admin),
):
    try:
        return await crawler_control_service.get_run(db, run_id)
    except CrawlerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/events", response_model=CrawlerListResponse)
async def list_crawler_run_events(
    run_id: int,
    after_id: Optional[int] = Query(None, alias="afterId"),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_crawler_admin),
):
    return await crawler_control_service.list_events(
        db,
        run_id=run_id,
        after_id=after_id,
        limit=limit,
    )
