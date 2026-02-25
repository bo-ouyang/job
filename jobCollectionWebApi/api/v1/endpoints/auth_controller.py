from datetime import timedelta
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status, Request, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession
from core.logger import sys_logger as logger
from config import settings
from dependencies import get_db, get_client_info
from crud import user as crud_user, verification_code as crud_verification_code
from schemas.token import (
    Token, WechatLoginRequest, PhoneLoginRequest, SendSMSRequest, 
    RefreshTokenRequest, LoginResponse, LoginRequest
)
from schemas.user import UserCreate, UserPublic, UserDetail
from core.security import (
    create_access_token, create_refresh_token, verify_token,
    generate_verification_code, blacklist_token
)
from core.status_code import StatusCode
from dependencies import get_current_user
from services.auth_service import auth_service
from services.wechat_service import wechat_service 
from services.sms_service import sms_service
router = APIRouter()

@router.post("/register", response_model=LoginResponse)
async def register(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db)
):
    """用户注册"""
    success, result, error = await auth_service.register_user(db, user_in.model_dump())
    if not success:
        raise HTTPException(
            status_code=StatusCode.BAD_REQUEST,
            detail=error
        )
    return result

@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
    client_info: dict = Depends(get_client_info)
):
    """用户名/邮箱 + 密码登录"""
    try:
        return await auth_service.login_with_password(db, request, client_info)
    except ValueError as e:
        raise HTTPException(
            status_code=StatusCode.UNAUTHORIZED,
            detail=str(e)
        )

@router.post("/login/wechat", response_model=LoginResponse)
async def login_wechat(
    request: WechatLoginRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    client_info: dict = Depends(get_client_info)
):
    """微信登录"""
    try:
        return await auth_service.login_with_wechat(db, request.code, client_info)
    except ValueError as e:
        raise HTTPException(
            status_code=StatusCode.BAD_REQUEST,
            detail=str(e)
        )

@router.post("/login/phone", response_model=LoginResponse)
async def login_phone(
    request: PhoneLoginRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    client_info: dict = Depends(get_client_info)
):
    """手机号登录"""
    try:
        return await auth_service.login_with_phone(
            db, request.phone, request.verification_code, client_info
        )
    except ValueError as e:
        raise HTTPException(
            status_code=StatusCode.BAD_REQUEST,
            detail=str(e)
        )

@router.post("/send-sms")
async def send_sms(
    request: SendSMSRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    client_info: dict = Depends(get_client_info)
):
    """发送验证码短信"""
    # 生成验证码
    code = generate_verification_code()
    
    # 保存验证码到数据库
    await crud_verification_code.create_code(
        db, request.phone, code, request.type
    )
    
    # 发送短信（异步）
    background_tasks.add_task(
        sms_service.send_verification_code, request.phone, code
    )
    
    # 在开发环境中返回验证码（便于测试）
    if settings.DEBUG:
        return {
            "message": "验证码发送成功",
            "debug_code": code  # 仅在开发环境返回
        }
    
    return {"message": "验证码发送成功"}

@router.post("/refresh-token", response_model=Token)
async def refresh_token(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    """刷新访问令牌"""
    try:
        return await auth_service.refresh_access_token(db, request.refresh_token)
    except ValueError as e:
        raise HTTPException(
            status_code=StatusCode.UNAUTHORIZED,
            detail=str(e)
        )

@router.post("/logout")
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """用户登出"""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "")
        await blacklist_token(token)
    
    return {"message": "登出成功"}

@router.get("/me", response_model=UserDetail)
async def get_current_user_info(
    current_user: dict = Depends(get_current_user)
):
    """获取当前用户信息"""
    return current_user

@router.get("/qrcode/generate")
async def generate_qrcode():
    """生成二维码 Ticket"""
    ticket = await auth_service.create_qrcode_ticket()
    # Mock URL generation - in production this might be a WeChat API URL
    url = f"https://api.qrserver.com/v1/create-qr-code/?size=150x150&data={ticket}"
    return {
        "ticket": ticket,
        "url": url,
        "expire_seconds": 300
    }

@router.get("/qrcode/status")
async def check_qrcode_status(ticket: str):
    """查询二维码状态"""
    return await auth_service.get_qrcode_status(ticket)

@router.post("/qrcode/scan")
async def app_scan(
    ticket: str = Query(...),
    current_user: dict = Depends(get_current_user)
):
    """
    APP端扫码接口 (需登录)
    """
    success = await auth_service.qrcode_scan(ticket, user_id=current_user.id)
    if not success:
        raise HTTPException(status_code=StatusCode.BAD_REQUEST, detail="Ticket无效、已过期或已被扫描")
    return {"message": "扫码成功"}

@router.post("/qrcode/confirm")
async def app_confirm(
    ticket: str = Query(...), 
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    APP端确认登录接口 (需登录)
    """
    success = await auth_service.qrcode_confirm(db, ticket, user_id=current_user.id)
    if not success:
         raise HTTPException(status_code=StatusCode.BAD_REQUEST, detail="确认失败：Ticket无效或状态不匹配")
    return {"message": "已确认登录"}

# --- 开发测试接口 ---

@router.post("/qrcode/dev/scan")
async def simulate_scan(ticket: str = Query(...)):
    """(开发测试) 模拟手机扫码"""
    success = await auth_service.simulate_qrcode_scan(ticket)
    if not success:
        raise HTTPException(status_code=StatusCode.BAD_REQUEST, detail="Ticket无效或已过期")
    return {"message": "已模拟扫码"}

@router.post("/qrcode/dev/confirm")
async def simulate_confirm(
    ticket: str = Query(...), 
    db: AsyncSession = Depends(get_db)
):
    """(开发测试) 模拟手机确认登录"""
    success = await auth_service.simulate_qrcode_confirm(db, ticket)
    if not success:
         raise HTTPException(status_code=StatusCode.BAD_REQUEST, detail="确认失败")
    return {"message": "已模拟确认登录"}
