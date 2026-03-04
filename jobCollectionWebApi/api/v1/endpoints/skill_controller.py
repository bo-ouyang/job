from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from crud import skill as crud_skill
from schemas.skill_schema import SkillList, SkillFrequencyList
from dependencies import get_db
from dependencies import CommonQueryParams

router = APIRouter()

@router.get("/", response_model=SkillList)
async def read_skills(
    db: AsyncSession = Depends(get_db),
    commons: CommonQueryParams = Depends(),
    category: str = Query(None, max_length=100, description="技能分类"),
):
    """获取技能列表"""
    if category:
        skills = await crud_skill.get_by_category(
            db, category=category, skip=commons.skip, limit=commons.limit
        )
    else:
        skills = await crud_skill.search(
            db, keyword=commons.keyword, skip=commons.skip, limit=commons.limit
        )
    
    total = await crud_skill.count(db)
    
    return SkillList(
        items=skills,
        total=total,
        page=commons.skip // commons.limit + 1,
        size=commons.limit,
        pages=(total + commons.limit - 1) // commons.limit
    )

@router.get("/frequency", response_model=SkillFrequencyList)
async def read_skills_frequency(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
):
    """获取技能频率统计"""
    skills_freq = await crud_skill.get_frequency(db, limit=limit)
    return SkillFrequencyList(
        skills=skills_freq,
        total=len(skills_freq)
    )
