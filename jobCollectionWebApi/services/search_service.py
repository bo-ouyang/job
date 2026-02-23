from typing import List, Optional, Tuple, Any
import logging
from common.databases.PostgresManager import db_manager # Use PostgresManager
from crud.job import job as crud_job # Reuse existing DB search logic

logger = logging.getLogger(__name__)

class SearchService:
    """职位搜索服务 (PostgreSQL Implementation)"""
    
    def __init__(self):
        pass

    async def search_jobs(
        self,
        *,
        keyword: Optional[str] = None,
        location: Optional[str] = None,
        experience: Optional[str] = None,
        education: Optional[str] = None,
        industry: Optional[str] = None,
        salary_min: Optional[float] = None,
        salary_max: Optional[float] = None,
        skip: int = 0,
        limit: int = 20
    ) -> Tuple[List[dict], int]:
        """
        基于 PostgreSQL 的职位搜索
        """
        async with db_manager.async_session() as session:
            # 直接复用 crud.job.search 方法
            # 注意：该方法目前是基于 ilike，后续可在 crud/job.py 中进一步优化为全文检索
            jobs, total = await crud_job.search(
                session,
                keyword=keyword,
                location=location,
                experience=experience,
                education=education,
                industry=industry,
                salary_min=salary_min,
                salary_max=salary_max,
                skip=skip,
                limit=limit
            )
            
            # 转换为字典格式以保持与原 ES 返回结构一致 (API 层的期望)
            job_list = []
            for job in jobs:
                # 序列化 Job 对象为字典
                # 注意：这里需要手动处理关联对象，或者使用 Pydantic model_validate
                # 简单起见，手动构建类似 ES 的 source 结构
                
                # 处理 tags
                skills = []
                if job.tags:
                    try:
                        import json
                        skills = job.tags if isinstance(job.tags, (list, dict)) else json.loads(job.tags)
                        if isinstance(skills, str): skills = [skills]
                    except:
                        skills = [str(job.tags)]


                job_dict = {
                    "id": job.id,
                    "title": job.title,
                    "description": job.description,
                    "requirements": job.requirements,
                    "salary_min": job.salary_min,
                    "salary_max": job.salary_max,
                    "location": job.location, # Fix key name from city to location
                    "experience": job.experience,
                    "education": job.education,
                    "publish_date": job.publish_date.isoformat() if job.publish_date else None,
                    "company": {
                        "id": job.company.id if job.company else 0,
                        "name": job.company.name if job.company else ""
                    },
                    "industry": {
                        "id": job.industry.id if job.industry else 0,
                        "name": job.industry.name if job.industry else ""
                    },
                    "tags": skills
                }
                job_list.append(job_dict)
                
            return job_list, total

    async def upsert_job(self, job_data: dict):
        """
        同步更新单个职位到 ES (PostgreSQL 模式下无需操作)
        数据已在 CRUD 层写入 DB
        """
        pass

    async def delete_job(self, job_id: int):
        """
        从 ES 删除单个职位 (PostgreSQL 模式下无需操作)
        """
        pass

search_service = SearchService()
