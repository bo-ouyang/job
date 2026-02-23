# api/api.py
from fastapi import APIRouter

# 使用相对导入
from api.v1.endpoints import (
    job_controller as job,
    company_controller as company,
    skill_controller as skill,
    analysis_controller as analysis,
    auth_controller as auth,
    user_controller as user,
    industry_controller as industry,
    upload_controller as upload,
    resume_controller as resume,
    favorite_controller as favorite,
    application_controller as application,
    message_controller as message,
    ws_controller as ws,
    payment_controller as payment,
    wallet_controller as wallet,
    city_controller as city
)
api_router = APIRouter()

# 包含各个子路由
api_router.include_router(job.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(company.router, prefix="/companies", tags=["companies"])
api_router.include_router(skill.router, prefix="/skills", tags=["skills"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(user.router, prefix="/users", tags=["users"])
api_router.include_router(industry.router, prefix="/industries", tags=["industries"])
api_router.include_router(upload.router, prefix="/upload", tags=["upload"])
api_router.include_router(resume.router, prefix="/resumes", tags=["resumes"])
api_router.include_router(favorite.router, prefix="/favorites", tags=["favorites"])
api_router.include_router(application.router, prefix="/applications", tags=["applications"])
api_router.include_router(message.router, prefix="/messages", tags=["messages"])
api_router.include_router(ws.router, prefix="/ws", tags=["websocket"])
api_router.include_router(payment.router, prefix="/payment", tags=["payment"])
api_router.include_router(wallet.router, prefix="/wallet", tags=["wallet"])
api_router.include_router(city.router, prefix="/cities", tags=["cities"])
