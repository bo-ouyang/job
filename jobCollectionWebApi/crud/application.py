from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from common.databases.models.application import Application, ApplicationStatus
from schemas.application import ApplicationCreate, ApplicationUpdate
from .base import CRUDBase

from common.databases.models.job import Job

class CRUDApplication(CRUDBase[Application, ApplicationCreate, ApplicationUpdate]):
    """投递记录 CRUD"""
    
    async def get_by_user_job(self, db: AsyncSession, user_id: int, job_id: int) -> Optional[Application]:
        """Check if user already applied to this job"""
        stmt = select(Application).where(
            and_(Application.user_id == user_id, Application.job_id == job_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_multi_by_user(
        self, db: AsyncSession, user_id: int, skip: int = 0, limit: int = 20
    ) -> List[Application]:
        """Get user applications with job details"""
        stmt = (
            select(Application)
            .options(
                selectinload(Application.job).selectinload(Job.company),
                selectinload(Application.job).selectinload(Job.industry)
            )
            .where(Application.user_id == user_id)
            .order_by(Application.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

application = CRUDApplication(Application)
