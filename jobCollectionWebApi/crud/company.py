from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import defer
from common.databases.models.company import Company
from jobCollectionWebApi.schemas.company import CompanyCreate, CompanyUpdate
from .base import CRUDBase

class CRUDCompany(CRUDBase[Company, CompanyCreate, CompanyUpdate]):
    """公司 CRUD 操作"""
    
    async def get_by_name(self, db: AsyncSession, name: str) -> Optional[Company]:
        """根据名称获取公司"""
        stmt = select(Company).where(Company.name == name)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def search(
        self, 
        db: AsyncSession, 
        *, 
        keyword: Optional[str] = None,
        industry: Optional[str] = None,
        location: Optional[str] = None,
        skip: int = 0, 
        limit: int = 50
    ) -> List[Company]:
        """搜索公司"""
        stmt = select(Company)
        
        if keyword:
            stmt = stmt.where(
                (Company.name.ilike(f"%{keyword}%")) | 
                (Company.description.ilike(f"%{keyword}%"))
            )
        
        if industry:
            stmt = stmt.where(Company.industry.ilike(f"{industry}%"))
        
        if location:
            stmt = stmt.where(Company.location.ilike(f"{location}%"))
        
        stmt = stmt.options(
            defer(Company.introduction),
            defer(Company.website)
        ).offset(skip).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()

company = CRUDCompany(Company)
