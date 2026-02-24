from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.sql import text
from common.databases.models.skills import Skills
#from models.job import job_skills
from jobCollectionWebApi.schemas.skill import SkillCreate, SkillUpdate, SkillFrequency
from .base import CRUDBase

class CRUDSkill(CRUDBase[Skills, SkillCreate, SkillUpdate]):
    """技能 CRUD 操作"""
    
    async def get_by_name(self, db: AsyncSession, name: str) -> Optional[Skills]:
        """根据名称获取技能"""
        stmt = select(Skills).where(Skills.name == name)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_frequency(self, db: AsyncSession, *, limit: int = 20) -> List[SkillFrequency]:
        """获取技能出现频率"""
        sql = text("""
            SELECT s.name, s.category, COUNT(js.job_id) as frequency
            FROM skills s
            JOIN job_skills js ON s.id = js.skill_id
            GROUP BY s.id, s.name, s.category
            ORDER BY frequency DESC
            LIMIT :limit
        """)
        result = await db.execute(sql, {"limit": limit})
        rows = result.fetchall()
        
        return [
            SkillFrequency(
                name=row[0],
                category=row[1],
                frequency=row[2]
            )
            for row in rows
        ]
    
    async def get_by_category(
        self, db: AsyncSession, category: str, *, skip: int = 0, limit: int = 100
    ) -> List[Skills]:
        """根据分类获取技能"""
        stmt = (
            select(Skills)
            .where(Skills.category == category)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()
    
    async def search(
        self, 
        db: AsyncSession, 
        *, 
        name: Optional[str] = None,
        category: Optional[str] = None,
        skip: int = 0, 
        limit: int = 50
    ) -> List[Skills]:
        """搜索技能"""
        stmt = select(Skills)
        
        if name:
            stmt = stmt.where(Skills.name.contains(name))
        
        if category:
            stmt = stmt.where(Skills.category == category)
        
        stmt = stmt.offset(skip).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()

skill = CRUDSkill(Skills)
