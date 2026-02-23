import asyncio
from jobCollectionWebApi.core.celery_app import celery_app
# from common.databases.MysqlManager import db_manager
from crud.job import job as crud_job
# We need to import models here for SQLAlchemy to know them? 
# Usually handled by imports in crud or models/__init__
import logging

logger = logging.getLogger(__name__)

async def _sync_job_logic(job_id: int):
    """Core async logic for syncing job"""
    # Create a new session for this task
    async with db_manager.async_session() as session:
        # We need to recreate the logic from CRUDJob._sync_to_es
        # But wait, CRUDJob._sync_to_es is instance method using 'self'. 
        # It calls 'search_service.upsert_job'.
        
        # We can just call crud_job._sync_to_es if we pass the session.
        # But _sync_to_es is internal. Let's make it more accessible or just invoke it.
        # It's better to move the logic here or make a public method on CRUD.
        # But CRUD instance 'job' is available.
        
        try:
            await crud_job._sync_to_es(session, job_id)
            logger.info(f"Successfully synced job {job_id} to ES")
        except Exception as e:
            logger.error(f"Failed to sync job {job_id}: {e}")
            raise e

@celery_app.task(bind=True, max_retries=3, name="sync_job_to_es")
def sync_job_to_es(self, job_id: int):
    """Celery task wrapper - Deprecated for PG migration"""
    logger.info(f"ES Sync task called for job {job_id} but ES is disabled.")
    return
