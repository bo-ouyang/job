from typing import List, Optional,Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func, and_, desc
import json
import asyncio
from collections import Counter
from common.databases.models.job import Job
from common.databases.models.skills import Skills
from common.databases.models.company import Company
from common.databases.models.industry import Industry
from sqlalchemy.orm import selectinload, defer

from jobCollectionWebApi.schemas.job import JobCreate, JobUpdate
from .base import CRUDBase
from sqlalchemy.orm import selectinload, aliased
from common.databases.models.industry import Industry

class CRUDJob(CRUDBase[Job, JobCreate, JobUpdate]):
    """职位 CRUD 操作"""
    
    # ES Sync removed for PostgreSQL migration

    async def create(self, db: AsyncSession, *, obj_in: JobCreate) -> Job:
        """创建职位"""
        db_obj = await super().create(db, obj_in=obj_in)
        await db.commit() 
        
        return db_obj

    async def update(
        self, db: AsyncSession, *, db_obj: Job, obj_in: JobUpdate | dict
    ) -> Job:
        """更新职位"""
        db_obj = await super().update(db, db_obj=db_obj, obj_in=obj_in)
        await db.commit()
        
        return db_obj

    async def remove(self, db: AsyncSession, *, id: int) -> Job:
        """删除职位并同步到 ES"""
        db_obj = await super().remove(db, id=id)
        if db_obj:
            await db.commit()
            # ES delete removed
        return db_obj

    async def get_by_source_url(self, db: AsyncSession, source_url: str) -> Optional[Job]:
        """根据来源URL获取职位"""
        stmt = select(Job).where(Job.source_url == source_url)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_multi_with_company(
        self, db: AsyncSession, *, skip: int = 0, limit: int = 100
    ) -> List[Job]:
        """获取职位列表（包含公司信息）"""
        stmt = (
            select(Job)
            .options(
                selectinload(Job.company), 
                selectinload(Job.industry),
                defer(Job.description),
                defer(Job.requirements),
                defer(Job.source_url)
            )
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()
    
    async def get_with_relations(self, db: AsyncSession, id: int) -> Optional[Job]:
        """获取职位详情（包含关联信息）"""
        stmt = (
            select(Job)
            .options(selectinload(Job.company), selectinload(Job.industry))
            .where(Job.id == id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_by_skills(
        self, db: AsyncSession, skill_names: List[str], *, skip: int = 0, limit: int = 50
    ) -> List[Job]:
        """根据技能名称获取职位"""
        stmt = (
            select(Job)
            .join(Job.skills)
            .where(Skills.name.in_(skill_names))
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def search(
        self,
        db: AsyncSession,
        *,
        keyword: Optional[str] = None,
        location: Optional[int] = None,
        experience: Optional[str] = None,
        education: Optional[str] = None,
        industry: Optional[int] = None,
        industry_2: Optional[int] = None, # Add param
        salary_min: Optional[float] = None,
        salary_max: Optional[float] = None,
        skip: int = 0,
        limit: int = 20
    ) -> Tuple[List[Job], int]:
        """数据库备用搜索逻辑 (当 ES 宕机时使用)"""
        stmt = select(Job).options(selectinload(Job.company), selectinload(Job.industry))
        count_stmt = select(func.count()).select_from(Job)

        conditions = []
        if keyword:
            keyword_filter = or_(
                Job.title.ilike(f"%{keyword}%"),
                Job.description.ilike(f"%{keyword}%")
            )
            conditions.append(keyword_filter)
        
        if location:
             # location is int code
            conditions.append(Job.city_code == location)
        
        if experience:
            conditions.append(Job.experience.ilike(f"{experience}%"))
            
        if education:
            conditions.append(Job.education.ilike(f"{education}%"))
            
        if salary_min is not None:
            conditions.append(Job.salary_max >= salary_min*1000)
            
        if salary_max is not None:
            conditions.append(Job.salary_min <= salary_max*1000)
            
        if industry_2:
            conditions.append(Job.industry_code == industry_2)
        elif industry:
             # industry is Parent Code
             sub_industry_codes_stmt = select(Industry.code).where(
                 or_(
                     Industry.code == industry,
                     Industry.parent_id == industry
                 )
             )
             conditions.append(Job.industry_code.in_(sub_industry_codes_stmt))

        if conditions:
            stmt = stmt.where(and_(*conditions))
            count_stmt = count_stmt.where(and_(*conditions))

        # 执行统计总数
        total_result = await db.execute(count_stmt)
        total = total_result.scalar_one()
        # logger.debug(stmt) 
        # 执行查询
        stmt = stmt.order_by(Job.publish_date.desc()).offset(skip).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all(), total

    async def get_statistics_from_db(
        self, 
        db: AsyncSession,
        keyword: Optional[str] = None,
        location: Optional[int] = None,
        experience: Optional[str] = None,
        education: Optional[str] = None,
        industry: Optional[int] = None,
        industry_2: Optional[int] = None,
        salary_min: Optional[float] = None,
        salary_max: Optional[float] = None
    ) -> dict:
        """数据库备用统计逻辑 (支持筛选)"""
        
        # 1. 构建通用过滤条件
        conditions = []
        if keyword:
            keyword_filter = or_(
                Job.title.ilike(f"%{keyword}%"),
                Job.description.ilike(f"%{keyword}%")
            )
            conditions.append(keyword_filter)
        
        if location:
             # location 现在是 city_code (int)
            conditions.append(Job.city_code == location)
        
        if experience:
            conditions.append(Job.experience.ilike(f"{experience}%"))
            
        if education:
            conditions.append(Job.education.ilike(f"{education}%"))
            
        if salary_min is not None:
            conditions.append(Job.salary_max >= salary_min)
            
        if salary_max is not None:
            conditions.append(Job.salary_min <= salary_max)
        
        # 行业筛选逻辑
        if industry_2:
             # 二级行业 (Sub Industry Code)
             conditions.append(Job.industry_code == industry_2)
             
        elif industry:
             # 一级行业 (Parent Industry Code)
             # 查找该父行业下所有子行业的 Code，以及父行业本身的 Code
             # Industry.parent_id 关联的是 Code
             
             # 查询符合条件的 Industry Code
             sub_industry_codes_stmt = select(Industry.code).where(
                 or_(
                     Industry.code == industry,       # 自身
                     Industry.parent_id == industry   # 子行业
                 )
             )
             
             conditions.append(Job.industry_code.in_(sub_industry_codes_stmt))

        base_filter = and_(*conditions) if conditions else True

        # 2. 薪资分布 (优化：单次查询聚合)
        salary_ranges = [
            (0, 10000, "10k以下"), (10000, 15000, "10k-15k"), 
            (15000, 25000, "15k-25k"), (25000, 35000, "25k-35k"), (35000, 999999, "35k以上")
        ]
        
        salary_selects = []
        for low, high, key in salary_ranges:
            # 使用 filter字句在聚合前过滤 (Postgres特性/SQLAlchemy支持)
            salary_selects.append(
                func.count(Job.id).filter(and_(Job.salary_min >= low, Job.salary_min < high)).label(f"count_{low}")
            )
            
        salary_stmt = select(*salary_selects).where(base_filter)
        salary_res = await db.execute(salary_stmt)
        salary_counts = salary_res.one()
        
        salary_dist = []
        for i, (low, high, key) in enumerate(salary_ranges):
             salary_dist.append({"name": key, "value": salary_counts[i]})

        # 3. 行业分布统计 (基于筛选结果)
        industry_stmt = (
            select(Industry.name, func.count(Job.id))
            .join(Job.industry)
            .where(base_filter)
            .group_by(Industry.name)
            .order_by(func.count(Job.id).desc())
            .limit(10)
        )
        industry_res = await db.execute(industry_stmt)
        industry_dist = [{"name": row[0], "value": row[1]} for row in industry_res.all()]

        # 4. 技能分布 (优化：使用数据库 JSON 函数聚合)
        # 注意: 前提是 tags 字段存储的是 JSON 数组
        try:
             skills_stmt = (
                select(
                    func.jsonb_array_elements_text(Job.tags).label("tag"),
                    func.count().label("cnt")
                )
                .where(base_filter)
                .group_by("tag")
                .order_by(desc("cnt"))
                .limit(10)
            )
             skills_res = await db.execute(skills_stmt)
             skill_dist = [{"name": row.tag, "value": row.cnt} for row in skills_res.all()]
        except Exception as e:
             # 降级: 如果数据库不支持或数据格式错误，回退到部分采样统计
             # print(f"DB Skill Aggregation failed: {e}, falling back to sampling.")
             skills_stmt = select(Job.tags).where(base_filter).order_by(Job.publish_date.desc()).limit(10000)
             skills_res = await db.execute(skills_stmt)
             all_tags = []
             for row in skills_res.scalars():
                 if row:
                     try:
                         tags = row if isinstance(row, (list, dict)) else json.loads(row)
                         if isinstance(tags, list): all_tags.extend(tags)
                         else: all_tags.append(str(tags))
                     except:
                         pass
             skill_counts = Counter(all_tags).most_common(12)
             skill_dist = [{"name": name, "value": count} for name, count in skill_counts]

        # 5. 统计总数
        total_stmt = select(func.count(Job.id)).where(base_filter)
        total_res = await db.execute(total_stmt)
        total = total_res.scalar_one()

        return {
            "salary": salary_dist,
            "skills": skill_dist,
            "industries": industry_dist,
            "total_jobs": total
        }

    async def analyze_by_keywords(
        self,
        db: AsyncSession,
        keywords: List[str],
        location: Optional[str] = None,
        industry_codes: Optional[List[int]] = None
    ) -> dict:
        """多关键词聚合分析 (SQL优化版)"""
        # 1. 构建基础过滤条件
        conditions = []
        # if keywords:
        #     keyword_filters = []
        #     for kw in keywords:
        #         keyword_filters.append(Job.title.ilike(f"%{kw}%"))
        #         keyword_filters.append(Job.description.ilike(f"%{kw}%"))
        #     conditions.append(or_(*keyword_filters))
        
        if location:
            conditions.append(Job.location.ilike(f"{location}%"))
            
        if industry_codes:
            conditions.append(Job.industry_code.in_(industry_codes))
            
        base_filter = and_(*conditions) if conditions else True

        # 2. 薪资分布 (SQL Filter 聚合)
        salary_ranges = [
            (0, 10000, "10k以下"), (10000, 15000, "10k-15k"), 
            (15000, 25000, "15k-25k"), (25000, 35000, "25k-35k"), (35000, 999999, "35k以上")
        ]
        
        salary_selects = []
        for low, high, key in salary_ranges:
            salary_selects.append(
                func.count(Job.id).filter(and_(Job.salary_min >= low, Job.salary_min < high)).label(f"count_{low}")
            )
            
        salary_stmt = select(*salary_selects).where(base_filter)
        
        # 3. 行业分布 (JOIN & Group By)
        industry_stmt = (
            select(Industry.name, func.count(Job.id))
            .join(Industry, Industry.code == Job.industry_code)
            .where(base_filter)
            .group_by(Industry.name)
            .order_by(func.count(Job.id).desc())
            .limit(5)
        )
        skills_stmt = (
                select(
                    func.jsonb_array_elements_text(Job.tags).label("tag"),
                    func.count().label("cnt")
                )
                .where(base_filter)
                .group_by("tag")
                .order_by(func.count().desc())
                .limit(10000)
            )
        total_stmt = select(func.count(Job.id)).where(base_filter)
        #print(industry_stmt) 
        # 1. 执行各个查询 (Sequential execution to avoid transaction issues)
        # SQLAlchemy AsyncSession is not thread-safe for concurrent operations like asyncio.gather
        
        salary_res = await db.execute(salary_stmt)
        salary_counts = salary_res.one()

        industry_res = await db.execute(industry_stmt)
        industry_rows = industry_res.all()

        try:
            skills_res = await db.execute(skills_stmt)
            skill_rows = skills_res.all()
        except Exception:
            skill_rows = []

        total_res = await db.execute(total_stmt)
        total = total_res.scalar_one()
        # 格式化结果
        salary_dist = []

        for i, (low, high, key) in enumerate(salary_ranges):
             salary_dist.append({"name": key, "value": salary_counts[i]})
             
        industry_dist = [{"name": row[0], "value": row[1]} for row in industry_rows]
        skill_dist = [{"name": row[0], "value": row[1]} for row in skill_rows][:15]

        return {
            "salary": salary_dist,
            "skills": skill_dist,
            "industries": industry_dist,
            "total_jobs": total
        }

job = CRUDJob(Job)
