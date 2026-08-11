# api/api.py
from fastapi import APIRouter

# 使用相对导入
from api.v1.endpoints import (
    auth_controller as auth,
    user_controller as user,
    industry_controller as industry,
    upload_controller as upload,
    resume_controller as resume,
    message_controller as message,
    ws_controller as ws,
    payment_controller as payment,
    wallet_controller as wallet,
    city_controller as city,
    ai_controller as ai,
    city_hot_controller as city_hot,
    agent_controller as agent,
)
api_router = APIRouter()

# 包含各个子路由

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(user.router, prefix="/users", tags=["users"])
api_router.include_router(industry.router, prefix="/industries", tags=["industries"])
api_router.include_router(upload.router, prefix="/upload", tags=["upload"])
api_router.include_router(resume.router, prefix="/resumes", tags=["resumes"])
api_router.include_router(message.router, prefix="/messages", tags=["messages"])
api_router.include_router(ws.router, prefix="/ws", tags=["websocket"])
api_router.include_router(payment.router, prefix="/payment", tags=["payment"])
api_router.include_router(wallet.router, prefix="/wallet", tags=["wallet"])
api_router.include_router(city.router, prefix="/cities", tags=["cities"])
api_router.include_router(city_hot.router, prefix="/city_hots", tags=["city_hots"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(agent.router, prefix="/agent", tags=["agent"])
