from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from common.databases.models.major import Major, MajorIndustryRelation
from common.databases.models.industry import Industry
from .base import CRUDBase
from schemas.analysis_schema import MajorInDB

class CRUDMajor(CRUDBase[Major, MajorInDB, MajorInDB]):
    
    async def get_categories_with_children(self, db: AsyncSession) -> List[Major]:
        """获取所有层级为1的专业大类，并预加载其子专业"""
        stmt = (
            select(Major)
            .where(Major.level == 1)
            .options(
                selectinload(Major.children).selectinload(Major.industry_relations)
            )
            .order_by(Major.id)
        )
        result = await db.execute(stmt)
        return result.scalars().all()


    async def get_relation_by_major_name(self, db: AsyncSession, major_name: str) -> Optional[MajorIndustryRelation]:
        """根据专业名称获取关联关系 (合并多条记录的行业代码)"""
       
        stmt = select(MajorIndustryRelation).where(MajorIndustryRelation.major_name == major_name)
        result = await db.execute(stmt)
        relations = result.scalars().all()
        
        if not relations:
            return None
            
        # Merge industry codes
        all_codes = set()
        for rel in relations:
            if rel.industry_codes:
                if isinstance(rel.industry_codes, list):
                    all_codes.update(rel.industry_codes)
                elif isinstance(rel.industry_codes, str):
                     # Handle case where it might be a JSON string?
                     # SQLAlchemy JSON type should auto-convert, but just in case
                     import json
                     try:
                         codes = json.loads(rel.industry_codes)
                         if isinstance(codes, list):
                             all_codes.update(codes)
                     except:
                         pass

        # Use the first relation as the base object
        merged_relation = relations[0]
        merged_relation.industry_codes = list(all_codes)
        
        
        return merged_relation

    async def increment_hot_index(self, db: AsyncSession, major_name: str) -> bool:
        """增加专业热度 (更新 MajorIndustryRelation.relevance_score)"""
        # 1. 尝试更新 Relation 表
        stmt = (
            update(MajorIndustryRelation)
            .where(MajorIndustryRelation.major_name == major_name)
            .values(relevance_score=MajorIndustryRelation.relevance_score + 1)
        )
        result = await db.execute(stmt)
        
        if result.rowcount > 0:
            await db.commit()
            return True
        return False

major = CRUDMajor(Major)
