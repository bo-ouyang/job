from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from common.databases.models.wallet import UserWallet, WalletTransaction, TransactionType, WalletStatus
from common.databases.models.payment import PaymentOrder, PaymentStatus
from .base import CRUDBase
from pydantic import BaseModel

class WalletCreate(BaseModel):
    user_id: int

class WalletUpdate(BaseModel):
    pass

class CRUDWallet(CRUDBase[UserWallet, WalletCreate, WalletUpdate]):
    async def get_by_user(self, db: AsyncSession, user_id: int) -> Optional[UserWallet]:
        stmt = select(UserWallet).where(UserWallet.user_id == user_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
        
    async def create_wallet(self, db: AsyncSession, user_id: int) -> UserWallet:
        db_obj = UserWallet(user_id=user_id)
        db.add(db_obj)
        await db.flush()
        return db_obj

    async def add_balance(
        self, 
        db: AsyncSession, 
        user_id: int, 
        amount: float, 
        source: str, 
        order_no: str = None,
        transaction_type: TransactionType = None
    ) -> UserWallet:
        """充值/增加余额 (带行锁)"""
        # 使用 with_for_update() 锁定行，防止并发更新覆盖
        stmt = select(UserWallet).where(UserWallet.user_id == user_id).with_for_update()
        result = await db.execute(stmt)
        wallet = result.scalar_one_or_none()
        
        if not wallet:
            # 如果钱包不存在，先创建 (此处极小概率并发，依靠唯一索引约束)
            wallet = await self.create_wallet(db, user_id)
            
        wallet.balance += amount
        
        # 记录交易
        tx = WalletTransaction(
            wallet_id=wallet.id,
            amount=amount,
            balance_after=wallet.balance,
            transaction_type=transaction_type or (TransactionType.DEPOSIT if amount > 0 else TransactionType.REFUND),
            related_order_no=order_no,
            description=source
        )
        db.add(wallet)
        db.add(tx)
        await db.flush()
        return wallet

    async def consume_balance(self, db: AsyncSession, user_id: int, amount: float, description: str, order_no: str = None) -> bool:
        """消费余额 (带行锁)"""
        # 使用 with_for_update() 锁定行
        stmt = select(UserWallet).where(UserWallet.user_id == user_id).with_for_update()
        result = await db.execute(stmt)
        wallet = result.scalar_one_or_none()

        if not wallet or wallet.status != WalletStatus.ACTIVE:
            return False
            
        if wallet.balance < amount:
            return False
            
        wallet.balance -= amount
        
        tx = WalletTransaction(
            wallet_id=wallet.id,
            amount=-amount,
            balance_after=wallet.balance,
            transaction_type=TransactionType.CONSUME,
            related_order_no=order_no,
            description=description
        )
        db.add(wallet)
        db.add(tx)
        await db.flush()
        return True

    async def get_transactions(
        self, 
        db: AsyncSession, 
        user_id: int, 
        skip: int = 0, 
        limit: int = 20
    ) -> list[WalletTransaction]:
        """获取交易流水"""
        stmt = (
            select(WalletTransaction)
            .join(UserWallet)
            .where(UserWallet.user_id == user_id)
            .order_by(WalletTransaction.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

wallet = CRUDWallet(UserWallet)
