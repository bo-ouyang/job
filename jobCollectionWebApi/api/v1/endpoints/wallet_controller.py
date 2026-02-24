from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies import get_db, get_current_user
from crud import wallet as crud_wallet
from pydantic import BaseModel
from typing import List
from common.databases.models.wallet import WalletTransaction
from datetime import datetime

router = APIRouter()

class TopUpRequest(BaseModel):
    amount: float

@router.get("/balance")
async def get_balance(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """查询余额"""
    wallet = await crud_wallet.wallet.get_by_user(db, current_user.id)
    if not wallet:
        return {"balance": 0.0, "status": "active"}
    return {"balance": wallet.balance, "status": wallet.status}

@router.post("/topup/simulate")
async def simulate_topup(
    params: TopUpRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """(测试用) 模拟账户充值"""
    # 在真实生产环境中，这里应该是支付宝/微信充值回调的逻辑，或者是创建充值订单跳转支付
    # 这里直接加余额方便测试
    wallet = await crud_wallet.wallet.add_balance(
        db, 
        user_id=current_user.id, 
        amount=params.amount, 
        source="manual_simulation"
    )
    return {"message": "Top up successful", "new_balance": wallet.balance}

class TransactionSchema(BaseModel):
    id: int
    amount: float
    balance_after: float
    transaction_type: str
    description: str = None
    created_at: datetime
    related_order_no: str = None

    class Config:
        from_attributes = True

@router.get("/transactions", response_model=List[TransactionSchema])
async def read_transactions(
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取我的交易流水"""
    return await crud_wallet.wallet.get_transactions(
        db, 
        user_id=current_user.id, 
        skip=skip, 
        limit=limit
    )
