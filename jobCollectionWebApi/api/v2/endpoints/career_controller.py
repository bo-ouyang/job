from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_db
from schemas.v2.career import (
    CareerLatestReportResponse,
    CareerOverviewQuery,
    CareerOverviewResponse,
    CareerQuestionRequest,
    CareerReportRequest,
    CareerSubmissionResponse,
)
from services.v2.career_service import career_service


router = APIRouter()


@router.get("/overview", response_model=CareerOverviewResponse)
async def get_overview(
    query: CareerOverviewQuery = Depends(),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await career_service.get_overview(db, current_user, query)


@router.get("/reports/latest", response_model=CareerLatestReportResponse)
async def get_latest_report(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await career_service.get_latest_report(db, current_user.id)


@router.post("/reports", response_model=CareerSubmissionResponse, status_code=202)
async def generate_report(
    payload: CareerReportRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=100),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await career_service.submit_agent_request(
        db,
        current_user,
        content=career_service.report_prompt(payload.filters),
        filters=payload.filters,
        idempotency_key=idempotency_key,
        title="职业分析报告",
        message_type="career_report_request",
    )


@router.post("/questions", response_model=CareerSubmissionResponse, status_code=202)
async def ask_question(
    payload: CareerQuestionRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=100),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await career_service.submit_agent_request(
        db,
        current_user,
        content=payload.question,
        filters=payload.filters,
        idempotency_key=idempotency_key,
        title="职业顾问问答",
        message_type="career_question",
    )
