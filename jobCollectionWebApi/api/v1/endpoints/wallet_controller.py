from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from crud import user as crud_user
from crud import wallet as crud_wallet
from dependencies import get_current_admin_user, get_current_user, get_db
from schemas.transaction_schema import TransactionPage, TransactionSchema

router = APIRouter()


class TopUpRequest(BaseModel):
    amount: float


class AdminManualTopupRequest(BaseModel):
    user_id: int
    amount: float = Field(..., gt=0)
    remark: Optional[str] = None


@router.get("/balance")
async def get_balance(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    wallet = await crud_wallet.wallet.get_by_user(db, current_user.id)
    if not wallet:
        return {"balance": 0.0, "status": "active"}
    return {"balance": wallet.balance, "status": wallet.status}


@router.post("/topup/simulate")
async def simulate_topup(
    params: TopUpRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    wallet = await crud_wallet.wallet.add_balance(
        db,
        user_id=current_user.id,
        amount=params.amount,
        source="manual_simulation",
    )
    return {"message": "Top up successful", "new_balance": wallet.balance}


@router.post("/admin/manual-topup")
async def admin_manual_topup(
    payload: AdminManualTopupRequest,
    db: AsyncSession = Depends(get_db),
    admin_user: dict = Depends(get_current_admin_user),
):
    target_user = await crud_user.user.get(db, id=payload.user_id)
    if not target_user:
        return {"ok": False, "message": "User not found"}

    source = f"admin_topup by {admin_user.id}"
    if payload.remark:
        source = f"{source}: {payload.remark}"

    wallet = await crud_wallet.wallet.add_balance(
        db,
        user_id=payload.user_id,
        amount=payload.amount,
        source=source,
    )
    return {"ok": True, "message": "Top up successful", "new_balance": wallet.balance}


@router.get("/transactions", response_model=List[TransactionSchema])
async def read_transactions(
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await crud_wallet.wallet.get_transactions(
        db,
        user_id=current_user.id,
        skip=skip,
        limit=limit,
    )


@router.get("/transactions/page", response_model=TransactionPage)
async def read_transactions_page(
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    page = max(page, 1)
    size = min(max(size, 1), 100)
    skip = (page - 1) * size

    items = await crud_wallet.wallet.get_transactions(
        db,
        user_id=current_user.id,
        skip=skip,
        limit=size,
    )
    total = await crud_wallet.wallet.count_transactions(db, user_id=current_user.id)
    return TransactionPage(items=items, total=total, page=page, size=size)
