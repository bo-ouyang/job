import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from common.databases.PostgresManager import db_manager
from common.databases.models.company import Company
from common.databases.models.industry import Industry
from common.databases.models.job import Job
from jobCollection.items.boss_job_item import BossJobDetailItem

logger = logging.getLogger(__name__)


class BossJobPipeline:
    """
    Pipeline 写入策略：asyncio.Queue 解耦 Spider 与 DB 写入。

    - process_item: 仅 put 到队列，永不阻塞 Spider。
    - _consumer:    后台任务，每次取出队列里所有可用 item（最多 BATCH_SIZE 条）
                    作为一个事务批量写入，兼顾实时性和效率。
    """

    _BATCH_SIZE = int(os.getenv("BOSS_PIPELINE_BATCH_SIZE", "15"))
    _DB_RETRIES = int(os.getenv("BOSS_PIPELINE_DB_RETRIES", "3"))
    _DB_RETRY_DELAY = float(os.getenv("BOSS_PIPELINE_DB_RETRY_DELAY", "1.0"))
    _IDLE_FLUSH_INTERVAL = float(os.getenv("BOSS_PIPELINE_IDLE_FLUSH", "2.0"))

    async def open_spider(self, spider):
        await db_manager.initialize()
        self._queue: asyncio.Queue = asyncio.Queue()
        self._consumer_task = asyncio.create_task(self._consumer())

    async def close_spider(self, spider):
        # 等待队列里所有 item 处理完再关闭
        await self._queue.join()
        self._consumer_task.cancel()
        try:
            await self._consumer_task
        except asyncio.CancelledError:
            pass

    async def process_item(self, item, spider):
        """立即返回，不阻塞 Spider；由后台消费者负责写 DB。"""
        if item is not None:
            await self._queue.put(item)
        return item

    async def _consumer(self):
        """
        后台消费者：
        1. 等待第一条 item（有就拿，最多等 _IDLE_FLUSH_INTERVAL 秒）
        2. 继续 drain 队列里已有的 item（非阻塞），凑到 _BATCH_SIZE 为止
        3. 写入 DB，task_done
        4. 循环
        """
        while True:
            batch = []
            # 1. 等待第一条 item
            try:
                first = await asyncio.wait_for(
                    self._queue.get(), timeout=self._IDLE_FLUSH_INTERVAL
                )
                batch.append(first)
            except asyncio.TimeoutError:
                continue  # 队列空，继续等待

            # 2. Drain 剩余可用 item（非阻塞）
            while len(batch) < self._BATCH_SIZE:
                try:
                    item = self._queue.get_nowait()
                    batch.append(item)
                except asyncio.QueueEmpty:
                    break

            # 3. 写入 DB（带重试）
            for attempt in range(1, self._DB_RETRIES + 1):
                try:
                    await self._db_write(batch)
                    break
                except Exception as e:
                    if attempt < self._DB_RETRIES:
                        logger.warning(f"DB 写入失败（第 {attempt} 次），{self._DB_RETRY_DELAY}s 后重试: {e}")
                        await asyncio.sleep(self._DB_RETRY_DELAY)
                    else:
                        logger.error(f"DB 写入放弃（已重试 {self._DB_RETRIES} 次）: {e}")

            # 4. 通知队列这批已处理
            for _ in batch:
                self._queue.task_done()

    # ------------------------------------------------------------------ #
    #  DB 写入
    # ------------------------------------------------------------------ #

    async def _db_write(self, batch: list):
        if not batch:
            return

        # 过滤掉 None（去重 pipeline drop 后可能传入 None）
        batch = [i for i in batch if i is not None]
        if not batch:
            return

        detail_updates = [i for i in batch if isinstance(i, BossJobDetailItem)]
        regular_inserts = [i for i in batch if not isinstance(i, BossJobDetailItem)]

        async with (await db_manager.get_session()) as session:
            async with session.begin():
                if detail_updates:
                    await self._write_detail_updates(session, detail_updates)
                if regular_inserts:
                    await self._write_jobs(session, regular_inserts)

    async def _write_detail_updates(self, session, items):
        for item in items:
            if not item.get("job_desc"):
                continue
            values = {
                "description": item["job_desc"],
                "updated_at": datetime.now(),
                "is_crawl": 1,
            }
            if item.get("longitude"):
                values["longitude"] = item["longitude"]
            if item.get("latitude"):
                values["latitude"] = item["latitude"]
            if item.get("skills"):
                values["tags"] = item["skills"]

            stmt = (
                update(Job)
                .where(Job.encrypt_job_id == item["encrypt_job_id"])
                .values(**values)
                .returning(Job.id)
            )
            res = await session.execute(stmt)
            job_id = res.scalar()
            if job_id:
                self._dispatch_es_sync(job_id)

        logger.info(f"更新 job 详情 {len(items)} 条")

    async def _write_jobs(self, session, items):
        items = [i for i in items if i is not None]
        if not items:
            return
        # 1. 行业 code -> id 映射
        industry_codes = {i.get("industry_code") for i in items if i.get("industry_code")}
        industry_map: dict = {}
        if industry_codes:
            res = await session.execute(
                select(Industry).where(Industry.code.in_(industry_codes))
            )
            industry_map = {ind.code: ind.id for ind in res.scalars()}

        # 2. 公司 Upsert
        brand_map: dict = {}
        brand_ids = {i["encrypt_brand_id"] for i in items if i.get("encrypt_brand_id")}
        if brand_ids:
            res = await session.execute(
                select(Company).where(Company.source_id.in_(brand_ids))
            )
            brand_map = {c.source_id: c.id for c in res.scalars()}

            missing = {bid: next(i for i in items if i.get("encrypt_brand_id") == bid)
                       for bid in brand_ids if bid not in brand_map}
            if missing:
                company_rows = [
                    {
                        "source_id": bid,
                        "name": item.get("brand_name"),
                        "logo": item.get("brand_logo"),
                        "scale": item.get("brand_scale_name"),
                        "stage": item.get("brand_stage_name"),
                        "industry": item.get("brand_industry"),
                        "created_at": datetime.now(),
                        "updated_at": datetime.now(),
                    }
                    for bid, item in missing.items()
                ]
                stmt = insert(Company).values(company_rows)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["source_id"],
                    set_={"name": stmt.excluded.name, "updated_at": datetime.now()},
                )
                await session.execute(stmt)
                res = await session.execute(
                    select(Company).where(Company.source_id.in_(missing.keys()))
                )
                brand_map.update({c.source_id: c.id for c in res.scalars()})

        # 3. 构造 Job 行
        now = datetime.now()
        job_rows = []
        for item in items:
            salary_desc = item.get("salary_desc", "")
            salary_min, salary_max = 0, 0
            m = re.search(r"(\d+)-(\d+)K", salary_desc, re.IGNORECASE)
            if m:
                salary_min = int(m.group(1)) * 1000
                salary_max = int(m.group(2)) * 1000

            job_rows.append({
                "title": item.get("job_name"),
                "salary_min": salary_min,
                "salary_max": salary_max,
                "salary_desc": salary_desc,
                "location": (
                    (item.get("city_name") or "")
                    + (item.get("area_district") or "")
                    + (item.get("business_district") or "")
                ),
                "experience": item.get("job_experience"),
                "education": item.get("job_degree"),
                "tags": item.get("skills") or [],
                "job_labels": item.get("job_labels") or [],
                "welfare": item.get("welfare_list") or [],
                "source_site": "BossZhipin",
                "source_url": f"https://www.zhipin.com/job_detail/{item.get('encrypt_job_id', '')}.html",
                "encrypt_job_id": item.get("encrypt_job_id"),
                "company_id": brand_map.get(item.get("encrypt_brand_id")),
                "industry_id": industry_map.get(item.get("industry_code")),
                "industry_code": item.get("industry_code"),
                "city_code": item.get("city_code"),
                "major_name": item.get("major_name"),
                "longitude": float(item.get("longitude") or 0),
                "latitude": float(item.get("latitude") or 0),
                "boss_name": item.get("boss_name"),
                "boss_title": item.get("boss_title"),
                "boss_avatar": item.get("boss_avatar"),
                "publish_date": now,
                "created_at": now,
                "updated_at": now,
                "is_crawl": 0,
            })

        if not job_rows:
            return

        # 4. Upsert
        stmt = insert(Job).values(job_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["encrypt_job_id"],
            set_={
                "title": stmt.excluded.title,
                "salary_min": stmt.excluded.salary_min,
                "salary_max": stmt.excluded.salary_max,
                "major_name": stmt.excluded.major_name,
                "updated_at": datetime.now(),
            },
        ).returning(Job.id)
        res = await session.execute(stmt)
        upserted_ids = res.scalars().all()
        logger.info(f"写入 job {len(job_rows)} 条（upserted={len(upserted_ids)}）")

        for jid in upserted_ids:
            self._dispatch_es_sync(jid)

    @staticmethod
    def _dispatch_es_sync(job_id: int):
        try:
            webapi_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                "jobCollectionWebApi",
            )
            if webapi_dir not in sys.path:
                sys.path.append(webapi_dir)
            from tasks.es_sync import sync_job_to_es
            sync_job_to_es.delay(job_id)
        except Exception as e:
            logger.warning(f"ES 同步任务分发失败 (job_id={job_id}): {e}")
