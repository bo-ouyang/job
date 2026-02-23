from typing import Optional, List, Union, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from .base import CRUDBase
from common.databases.models.resume import Resume, Education, WorkExperience, ProjectExperience
from schemas.resume import ResumeCreate, ResumeUpdate

class CRUDResume(CRUDBase[Resume, ResumeCreate, ResumeUpdate]):
    
    async def get_by_user_id(self, db: AsyncSession, *, user_id: int) -> Optional[Resume]:
        statement = select(Resume).where(Resume.user_id == user_id).options(
            selectinload(Resume.educations),
            selectinload(Resume.work_experiences),
            selectinload(Resume.projects)
        )
        result = await db.execute(statement)
        return result.scalars().first()

    async def create_with_user(
        self, db: AsyncSession, *, obj_in: ResumeCreate, user_id: int
    ) -> Resume:
        obj_in_data = obj_in.model_dump(exclude={'educations', 'work_experiences', 'projects'})
        db_obj = Resume(**obj_in_data, user_id=user_id)
        db.add(db_obj)
        await db.flush() # get ID
        
        # Add nested
        for edu in obj_in.educations:
            db_edu = Education(**edu.model_dump(), resume_id=db_obj.id)
            db.add(db_edu)
            
        for work in obj_in.work_experiences:
            db_work = WorkExperience(**work.model_dump(), resume_id=db_obj.id)
            db.add(db_work)
            
        for proj in obj_in.projects:
            db_proj = ProjectExperience(**proj.model_dump(), resume_id=db_obj.id)
            db.add(db_proj)
            
        await db.commit()
        await db.refresh(db_obj)
        # Reload relationships
        return await self.get_by_user_id(db, user_id=user_id)

    async def update(
        self, 
        db: AsyncSession, 
        *, 
        db_obj: Resume, 
        obj_in: Union[ResumeUpdate, Dict[str, Any]]
    ) -> Resume:
        """Override update to ensure relationships are reloaded"""
        await super().update(db, db_obj=db_obj, obj_in=obj_in)
        # Reload full object with relationships to avoid MissingGreenlet error
        return await self.get_by_user_id(db, user_id=db_obj.user_id)

resume = CRUDResume(Resume)
