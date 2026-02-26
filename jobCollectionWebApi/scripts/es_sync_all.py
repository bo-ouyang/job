import asyncio
import sys
import os
import json

from sqlalchemy import select
from sqlalchemy.orm import selectinload

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.databases.PostgresManager import db_manager
from config import settings
from common.search.conn import get_es, es_manager
from common.databases.models.job import Job
from elasticsearch.helpers import async_bulk
from core.logger import sys_logger as logger
#logging.basicConfig(level=logging.INFO)

async def fetch_jobs_from_pg(session, skip: int, limit: int):
    """Fetch jobs with company and industry relations"""
    stmt = (
        select(Job)
        .options(selectinload(Job.company), selectinload(Job.industry))
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()

def format_job_for_es(job: Job) -> dict:
    """Serialize SQLAlchemy Job model into ES dict"""
    skills = []
    if job.tags:
        try:
            skills = json.loads(job.tags) if isinstance(job.tags, str) else job.tags
            if isinstance(skills, str): skills = [skills]
        except Exception:
            skills = [str(job.tags)]
            
    def _parse_list(field_data):
        if not field_data: return []
        if isinstance(field_data, list): return field_data
        try:
            res = json.loads(field_data)
            return res if isinstance(res, list) else [str(res)]
        except Exception:
            return [str(field_data)]
            
    return {
        "_index": settings.ES_INDEX_JOB,
        "_id": str(job.id),
        "_source": {
            "id": job.id,
            "title": job.title,
            "description": job.description or "",
            "requirements": job.requirements or "",
            "salary_min": job.salary_min,
            "salary_max": job.salary_max,
            "salary_unit": job.salary_unit or "月",
            "salary_desc": job.salary_desc or "",
            "city": job.location.split('-')[0] if job.location else "", 
            "city_code": job.city_code,
            "district": job.area_district or "", 
            "experience": job.experience,
            "education": job.education,
            "company_name": job.company.name if job.company else "",
            "industry": job.industry.name if job.industry else "",
            "industry_code": job.industry_code,
            "ai_summary": job.ai_summary or "",
            "ai_skills": _parse_list(job.ai_skills),
            "ai_benefits": _parse_list(job.ai_benefits),
            "job_labels": _parse_list(job.job_labels),
            "welfare": _parse_list(job.welfare),
            "work_type": job.work_type or "",
            "boss_name": job.boss_name or "",
            "boss_title": job.boss_title or "",
            "skills": skills,
            "tags": skills,
            "publish_date": job.publish_date.isoformat() if job.publish_date else None,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "location": job.location
        }
    }

async def sync_all_jobs_to_es():
    """Bulk copy jobs from Postgres to Elasticsearch"""
    es = await get_es()
    await db_manager.initialize()
    
    batch_size = 200
    skip = 0
    total_synced = 0
    
    async with db_manager.async_session() as session:
        while True:
            logger.info(f"Fetching rows {skip} to {skip + batch_size} from PostgreSQL...")
            jobs = await fetch_jobs_from_pg(session, skip, batch_size)
            
            if not jobs:
                logger.info("No more rows to sync. Job completed.")
                break
                
            actions = [format_job_for_es(job) for job in jobs]
            
            from elasticsearch.helpers import BulkIndexError
            try:
                success, failed = await async_bulk(es, actions, stats_only=True,chunk_size=200,request_timeout=60)
                total_synced += success
                logger.info(f"Successfully Bulk Inserted: {success} | Failed: {failed}")
            except BulkIndexError as e:
                logger.error(f"Failed to index {len(e.errors)} documents. First error details: {e.errors[0]}")
                break
            
            skip += batch_size
            
    logger.info(f"Total jobs synced to Elasticsearch: {total_synced}")
    await es_manager.close()

if __name__ == "__main__":
    asyncio.run(sync_all_jobs_to_es())
