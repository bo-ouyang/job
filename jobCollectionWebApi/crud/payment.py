from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.databases.models.payment import PaymentOrder, PaymentStatus
from jobCollectionWebApi.schemas.payment_schema import PaymentOrderCreate, PaymentOrderSchema

from .base import CRUDBase


class CRUDPaymentOrder(CRUDBase[PaymentOrder, PaymentOrderCreate, PaymentOrderSchema]):
    async def get_by_order_no(self, db: AsyncSession, order_no: str) -> Optional[PaymentOrder]:
        stmt = select(PaymentOrder).where(PaymentOrder.order_no == order_no)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_order_no_for_update(self, db: AsyncSession, order_no: str) -> Optional[PaymentOrder]:
        stmt = select(PaymentOrder).where(PaymentOrder.order_no == order_no).with_for_update()
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_orders(
        self,
        db: AsyncSession,
        user_id: int,
        skip: int = 0,
        limit: int = 20,
    ) -> list[PaymentOrder]:
        return await self.list_orders(
            db=db,
            user_id=user_id,
            skip=skip,
            limit=limit,
        )

    async def count_user_orders(self, db: AsyncSession, user_id: int) -> int:
        return await self.count_orders(db=db, user_id=user_id)

    async def list_orders(
        self,
        db: AsyncSession,
        user_id: Optional[int] = None,
        status: Optional[str] = None,
        order_no: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> list[PaymentOrder]:
        stmt = select(PaymentOrder)

        if user_id is not None:
            stmt = stmt.where(PaymentOrder.user_id == user_id)
        if status:
            stmt = stmt.where(PaymentOrder.status == status)
        if order_no:
            stmt = stmt.where(PaymentOrder.order_no.ilike(f"%{order_no}%"))

        stmt = stmt.order_by(PaymentOrder.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()

    async def count_orders(
        self,
        db: AsyncSession,
        user_id: Optional[int] = None,
        status: Optional[str] = None,
        order_no: Optional[str] = None,
    ) -> int:
        stmt = select(func.count()).select_from(PaymentOrder)

        if user_id is not None:
            stmt = stmt.where(PaymentOrder.user_id == user_id)
        if status:
            stmt = stmt.where(PaymentOrder.status == status)
        if order_no:
            stmt = stmt.where(PaymentOrder.order_no.ilike(f"%{order_no}%"))

        result = await db.execute(stmt)
        return int(result.scalar_one() or 0)

    async def create_order(
        self,
        db: AsyncSession,
        user_id: int,
        obj_in: PaymentOrderCreate,
        order_no: str,
    ) -> PaymentOrder:
        db_obj = PaymentOrder(
            order_no=order_no,
            user_id=user_id,
            amount=obj_in.amount,
            payment_method=(
                obj_in.payment_method.value
                if hasattr(obj_in.payment_method, "value")
                else obj_in.payment_method
            ),
            product_type=obj_in.product_type,
            extra_data=obj_in.extra_data,
            status=PaymentStatus.PENDING,
        )
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj


payment_order = CRUDPaymentOrder(PaymentOrder)
