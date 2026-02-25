import asyncio
from jobCollectionWebApi.core.celery_app import celery_app
from common.databases.PostgresManager import db_manager
from crud.job import job as crud_job
from common.search.conn import get_es
from config import settings
from core.logger import sys_logger as logger


async def _sync_job_logic(job_id: int):
    """Core async logic for syncing job"""
    try:
        async with db_manager.async_session() as session:
            job = await crud_job.get_with_relations(session, job_id)
            if not job:
                logger.warning(f"Job {job_id} not found in PostgreSQL. It might have been deleted.")
                return

            import json
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
            doc = {
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
            "created_at": job.created_at.isoformat() if job.created_at else None
            }
            
            es = await get_es()
            # 如果文档已存在会执行完全覆盖，符合 Upsert 语义
            await es.index(index=settings.ES_INDEX_JOB, id=str(job_id), body=doc)
            logger.info(f"Successfully synced job {job_id} to Elasticsearch.")
    except Exception as e:
        logger.error(f"Failed to sync job {job_id}: {e}")
        raise e

@celery_app.task(bind=True, max_retries=3, name="sync_job_to_es")
def sync_job_to_es(self, job_id: int):
    """把单独一条的变动映射到 ES 中"""
    loop = asyncio.get_event_loop()
    loop.run_until_complete(_sync_job_logic(job_id))
    
@celery_app.task(bind=True, max_retries=3, name="delete_job_from_es")
def delete_job_from_es(self, job_id: int):
    """当 PostgreSQL 中删除时，对应的同步删除 ES 信息"""
    async def _delete():
        try:
            es = await get_es()
            await es.delete(index=settings.ES_INDEX_JOB, id=str(job_id), ignore_unavailable=True)
            logger.info(f"Successfully deleted job {job_id} from Elasticsearch.")
        except Exception as e:
            logger.error(f"Failed to delete job {job_id} from ES: {e}")
            raise e
            
    loop = asyncio.get_event_loop()
    loop.run_until_complete(_delete())
