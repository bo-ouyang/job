"""Scrapy adapter for the shared BOSS job persistence service."""

import asyncio
import logging
import os
from datetime import datetime

from sqlalchemy import update
from scrapy.exceptions import DropItem

from common.databases.PostgresManager import db_manager
from common.databases.models.job import Job
from jobCollection.boss.writer import BossJobWriter
from jobCollection.items.boss_job_item import BossJobDetailItem


logger = logging.getLogger(__name__)


class BossJobPipeline:
    """Wait for the authoritative PostgreSQL write before accepting an item."""

    _DB_RETRIES = int(os.getenv("BOSS_PIPELINE_DB_RETRIES", "3"))
    _DB_RETRY_DELAY = float(os.getenv("BOSS_PIPELINE_DB_RETRY_DELAY", "1.0"))

    def __init__(self, writer=None) -> None:
        self.writer = writer or BossJobWriter()

    async def open_spider(self, spider):
        await db_manager.initialize()

    async def process_item(self, item, spider):
        if item is not None:
            succeeded = await self._write_batch_with_retries([item])
            if not succeeded:
                spider.pipeline_failed = True
                raise DropItem("BOSS PostgreSQL write failed permanently")
        return item

    async def _write_batch_with_retries(self, batch: list) -> bool:
        for attempt in range(1, self._DB_RETRIES + 1):
            try:
                await self._db_write(batch)
                return True
            except Exception as error:
                if attempt < self._DB_RETRIES:
                    logger.warning(
                        "BOSS DB write failed (attempt %s); retrying in %ss: %s",
                        attempt,
                        self._DB_RETRY_DELAY,
                        error,
                    )
                    await asyncio.sleep(self._DB_RETRY_DELAY)
                else:
                    logger.error(
                        "BOSS DB write abandoned after %s attempts: %s",
                        self._DB_RETRIES,
                        error,
                    )
        detail_items = [
            item for item in batch if isinstance(item, BossJobDetailItem)
        ]
        if detail_items:
            try:
                await self._revert_detail_items(detail_items)
            except Exception as error:
                logger.error("Unable to revert failed detail items: %s", error)
        return False

    async def _revert_detail_items(self, items: list):
        encrypt_job_ids = [
            item.get("encrypt_job_id")
            for item in items
            if item.get("encrypt_job_id")
        ]
        if not encrypt_job_ids:
            return
        async with (await db_manager.get_session()) as session:
            async with session.begin():
                await session.execute(
                    update(Job)
                    .where(Job.encrypt_job_id.in_(encrypt_job_ids))
                    .values(is_crawl=0, updated_at=datetime.now())
                )

    async def _db_write(self, batch: list):
        return await self.writer.write_batch(
            batch,
            detail_writer=self._write_detail_updates,
            jobs_writer=self._write_jobs,
            dispatch=self._dispatch_es_sync,
        )

    async def _write_detail_updates(self, session, items):
        return await self.writer.write_detail_updates(session, items)

    async def _write_jobs(self, session, items):
        return await self.writer.write_jobs(session, items)

    @staticmethod
    def _dispatch_es_sync(job_id: int):
        BossJobWriter.dispatch_es_sync(job_id)
