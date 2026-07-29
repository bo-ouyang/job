from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_db
from schemas.v2.career import CareerSubmissionResponse
from schemas.v2.market import (
    MarketDashboardQuery,
    MarketDashboardResponse,
    MarketQuestionRequest,
)
from services.v2.market_dashboard_service import market_dashboard_service
from services.v2.career_service import career_service

router = APIRouter()


@router.get("/dashboard", response_model=MarketDashboardResponse, response_model_by_alias=True)
async def get_market_dashboard(query: MarketDashboardQuery = Depends()):
    return await market_dashboard_service.get_dashboard(query)


@router.post("/questions", response_model=CareerSubmissionResponse, status_code=202)
async def ask_market_question(
    payload: MarketQuestionRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=100),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    filters = payload.context.get("filters", {})
    if not isinstance(filters, dict):
        filters = {}
    return await career_service.submit_agent_request(
        db,
        current_user,
        content=payload.question,
        filters=filters,
        idempotency_key=idempotency_key,
        title="市场数据问答",
        message_type="market_question",
    )
