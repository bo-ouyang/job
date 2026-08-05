from fastapi import APIRouter

from api.v2.endpoints import (
    career_controller,
    crawler_agent_controller,
    crawler_controller,
    market_controller,
    meta_controller,
    pricing_controller,
    profile_controller,
)

api_router = APIRouter()
api_router.include_router(meta_controller.router, prefix="/meta", tags=["v2-meta"])
api_router.include_router(market_controller.router, prefix="/market", tags=["v2-market"])
api_router.include_router(profile_controller.router, prefix="/profile", tags=["v2-profile"])
api_router.include_router(
    career_controller.router,
    prefix="/career-analysis",
    tags=["v2-career-analysis"],
)
api_router.include_router(pricing_controller.router, prefix="/ai", tags=["v2-ai"])
api_router.include_router(
    crawler_controller.router,
    prefix="/admin/crawlers",
    tags=["v2-crawler-admin"],
)
api_router.include_router(
    crawler_agent_controller.router,
    prefix="/crawler-agent",
    tags=["v2-crawler-agent"],
)
