from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from common.databases.models.product import Product
from .base import CRUDBase
from pydantic import BaseModel

# Schema placeholders (normally in schemas/product.py)
class ProductCreate(BaseModel):
    name: str
    code: str
    price: float
    original_price: Optional[float] = None
    description: Optional[str] = None
    category: Optional[str] = None
    image_url: Optional[str] = None

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = None
    is_active: Optional[bool] = None

class CRUDProduct(CRUDBase[Product, ProductCreate, ProductUpdate]):
    async def get_by_code(self, db: AsyncSession, code: str) -> Optional[Product]:
        stmt = select(Product).where(Product.code == code)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_active_products(self, db: AsyncSession) -> List[Product]:
        stmt = select(Product).where(Product.is_active == True)
        result = await db.execute(stmt)
        return result.scalars().all()

product = CRUDProduct(Product)
