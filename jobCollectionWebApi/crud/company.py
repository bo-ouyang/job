from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from common.databases.models.company import Company
from jobCollectionWebApi.schemas.company_schema import CompanyCreate, CompanyUpdate

from .base import CRUDBase


class CRUDCompany(CRUDBase[Company, CompanyCreate, CompanyUpdate]):
    """Company CRUD operations."""

    async def get_by_name(self, db: AsyncSession, name: str) -> Optional[Company]:
        stmt = select(Company).where(Company.name == name)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def _apply_filters(
        stmt,
        *,
        keyword: Optional[str] = None,
        industry: Optional[str] = None,
        location: Optional[str] = None,
    ):
        if keyword:
            kw = keyword.strip()
            if kw:
                like_kw = f"%{kw}%"
                stmt = stmt.where(
                    or_(
                        Company.name.ilike(like_kw),
                        Company.description.ilike(like_kw),
                    )
                )

        if industry:
            industry_kw = industry.strip()
            if industry_kw:
                stmt = stmt.where(Company.industry.ilike(f"{industry_kw}%"))

        if location:
            location_kw = location.strip()
            if location_kw:
                stmt = stmt.where(Company.location.ilike(f"{location_kw}%"))

        return stmt

    async def search(
        self,
        db: AsyncSession,
        *,
        keyword: Optional[str] = None,
        industry: Optional[str] = None,
        location: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Company]:
        stmt = select(Company).options(
            load_only(
                Company.id,
                Company.name,
                Company.industry,
                Company.scale,
                Company.stage,
                Company.location,
                Company.logo,
                Company.description,
                Company.created_at,
            )
        )
        stmt = self._apply_filters(
            stmt,
            keyword=keyword,
            industry=industry,
            location=location,
        )
        stmt = stmt.order_by(Company.created_at.desc(), Company.id.desc()).offset(skip).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()

    async def count_search(
        self,
        db: AsyncSession,
        *,
        keyword: Optional[str] = None,
        industry: Optional[str] = None,
        location: Optional[str] = None,
    ) -> int:
        stmt = select(func.count(Company.id))
        stmt = self._apply_filters(
            stmt,
            keyword=keyword,
            industry=industry,
            location=location,
        )
        result = await db.execute(stmt)
        return int(result.scalar_one() or 0)


company = CRUDCompany(Company)
