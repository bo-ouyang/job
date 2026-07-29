from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_db
from schemas.v2.career import AIPricingResponse
from services.ai_access_service import ai_access_service


router = APIRouter()


@router.get("/pricing", response_model=AIPricingResponse)
async def get_pricing(db: AsyncSession = Depends(get_db)):
    pricing = await ai_access_service.get_public_pricing(
        db,
        ["career_compass", "career_advice", "resume_parse"],
    )
    return {
        "career_report": pricing["career_compass"],
        "career_question": pricing["career_advice"],
        "ai_conversation": pricing["career_advice"],
        "market_question": pricing["career_advice"],
        "resume_parse": pricing["resume_parse"],
    }
