from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from common.databases.models.payment import PaymentOrder, PaymentStatus
from .base import CRUDBase
from jobCollectionWebApi.schemas.payment import PaymentOrderCreate, PaymentOrderSchema

class CRUDPaymentOrder(CRUDBase[PaymentOrder, PaymentOrderCreate, PaymentOrderSchema]):
    
    async def get_by_order_no(self, db: AsyncSession, order_no: str) -> Optional[PaymentOrder]:
        stmt = select(PaymentOrder).where(PaymentOrder.order_no == order_no)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_order_no_for_update(self, db: AsyncSession, order_no: str) -> Optional[PaymentOrder]:
        """带行锁查询，防止并发修改"""
        stmt = select(PaymentOrder).where(PaymentOrder.order_no == order_no).with_for_update()
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_order(
        self, 
        db: AsyncSession, 
        user_id: int, 
        obj_in: PaymentOrderCreate, 
        order_no: str
    ) -> PaymentOrder:
        db_obj = PaymentOrder(
            order_no=order_no,
            user_id=user_id,
            amount=obj_in.amount,
            payment_method=obj_in.payment_method,
            product_type=obj_in.product_type,
            extra_data=obj_in.extra_data,
            status=PaymentStatus.PENDING
        )
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj

payment_order = CRUDPaymentOrder(PaymentOrder)
