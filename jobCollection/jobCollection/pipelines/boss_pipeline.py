import sys
import os

# Ensure the WebAPI directory is in path so Scrapy can import Celery tasks
webapi_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(os.path.join(webapi_dir, 'jobCollectionWebApi'))

import asyncio
import logging
import json
import re
from collections import defaultdict
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from common.databases.PostgresManager import db_manager
from common.databases.models.job import Job
from common.databases.models.company import Company
from common.databases.models.industry import Industry
from common.databases.models.spider_boss_crawl_url import SpiderBossCrawlUrl # If we want to update tasks here, but maybe not in batch?

logger = logging.getLogger(__name__)

class WriteBuffer:
    def __init__(self, max_rows=100, max_wait=3):
        self.queue = asyncio.Queue()
        self.buffer = []
        self.max_rows = max_rows
        self.max_wait = max_wait

    async def push(self, item):
        await self.queue.put(item)

    async def run(self, writer_func):
        while True:
            try:
                try:
                    item = await asyncio.wait_for(self.queue.get(), timeout=self.max_wait)
                    self.buffer.append(item)
                except asyncio.TimeoutError:
                    pass

                # If buffer full or timeout occurred (and we have something)
                # Check buffer size or if we just timed out.
                # Logic: If we got an item, check size. If full, flush.
                # If we timed out, flush if not empty.
                
                should_flush = len(self.buffer) >= self.max_rows or (not self.queue.empty() == False and len(self.buffer) > 0)
                # Actually simpler: always flush if we hit timeout (implicit in flow above) OR if size >= max
                
                if len(self.buffer) >= self.max_rows or (self.buffer and self.queue.empty()):
             	    # Verify queue empty check is robust? 
             	    # Just flushing periodically is fine.
             	    await self.flush(writer_func)

            except Exception as e:
                logger.error(f"Buffer run error: {e}")
                # Don't break, continue
                
    async def flush(self, writer_func):
        if not self.buffer:
            return
        batch = list(self.buffer)
        self.buffer.clear()
        try:
            await writer_func(batch)
        except Exception as e:
            logger.error(f"Flush error: {e}")

class BossJobPipeline:
    def __init__(self):
        self.buffer = WriteBuffer(max_rows=100, max_wait=2)

    async def open_spider(self):
        await db_manager.initialize()
        self.writer_task = asyncio.create_task(self.buffer.run(self._db_write))

    async def close_spider(self):
        await self.buffer.flush(self._db_write)
        self.writer_task.cancel()
        try:
            await self.writer_task
        except asyncio.CancelledError:
            pass
        # await db_manager.close() # Shared DB manager, maybe don't close if handled globally or other spiders

    async def process_item(self, item):
        await self.buffer.push(item)
        return item

    async def _db_write(self, batch):
        """Batch write logic"""
        if not batch: return
        
        from jobCollection.items.boss_job_item import BossJobDetailItem
        
        # Filter None items
        batch = [i for i in batch if i is not None]
        if not batch: return

        # Separate Detail Updates from New Inserts
        detail_updates = [i for i in batch if isinstance(i, BossJobDetailItem)]
        regular_inserts = [i for i in batch if not isinstance(i, BossJobDetailItem)]
        
        async with (await db_manager.get_session()) as session:
            async with session.begin(): # Start transaction
                
                # --- Handle Detail Updates ---
                if detail_updates:
                    for update_item in detail_updates:
                        if not update_item.get('job_desc'): continue
                        
                        update_values = {
                        'description': update_item['job_desc'], 
                        'updated_at': datetime.now(),
                        'is_crawl': 1
                    }
                        
                        if update_item.get('longitude'):
                            update_values['longitude'] = update_item['longitude']
                        if update_item.get('latitude'):
                            update_values['latitude'] = update_item['latitude']
                            
                         # Note: Updating skills might require more complex logic if it's a relation.
                         # For now, we updated 'job_desc' and 'location'.
                         # If 'tags' (skills) need update, we need to serialize them?
                         # The Job model has 'tags' as Text(JSON).
                        if update_item.get('skills'):
                             update_values['tags'] = json.dumps(update_item['skills'], ensure_ascii=False)

                        stmt = update(Job).where(Job.encrypt_job_id == update_item['encrypt_job_id']).values(**update_values).returning(Job.id)
                        res = await session.execute(stmt)
                        updated_id = res.scalar()
                        if updated_id:
                            # 触发 ES 同步
                            try:
                                from tasks.es_sync import sync_job_to_es
                                sync_job_to_es.delay(updated_id)
                            except Exception as e:
                                logger.warning(f"Failed to dispatch Celery sync task for updated job {updated_id}: {e}")
                                
                    logger.info(f"Batch updated {len(detail_updates)} job details.")

                # --- Handle Regular Inserts (Previous Logic) ---
                if regular_inserts:
                    # 1. Resolve Industries
                    industry_codes = set(i.get('industry_code') for i in regular_inserts if i.get('industry_code'))
                    industry_map_code_id = {} # code -> id
                    if industry_codes:
                        stmt = select(Industry).where(Industry.code.in_(industry_codes))
                        res = await session.execute(stmt)
                        for ind in res.scalars():
                            industry_map_code_id[ind.code] = ind.id
                    
                    # 2. Resolve Companies
                    # Collect brand IDs and Names
                    brand_map_source_id = {} # source_id -> id
                    items_with_brand_id = [i for i in regular_inserts if i.get('encrypt_brand_id')]
                    
                    if items_with_brand_id:
                        sids = set(i['encrypt_brand_id'] for i in items_with_brand_id)
                        stmt = select(Company).where(Company.source_id.in_(sids))
                        res = await session.execute(stmt)
                        for com in res.scalars():
                            brand_map_source_id[com.source_id] = com.id

                    # Identify missing Companies
                    missing_companies = {} # source_id -> item
                    for i in regular_inserts:
                        bid = i.get('encrypt_brand_id')
                        if bid and bid not in brand_map_source_id:
                            missing_companies[bid] = i
                    
                    if missing_companies:
                        new_companies = []
                        for bid, item in missing_companies.items():
                            new_companies.append({
                                'source_id': bid,
                                'name': item.get('brand_name'),
                                'logo': item.get('brand_logo'),
                                'scale': item.get('brand_scale_name'),
                                'stage': item.get('brand_stage_name'),
                                'industry': item.get('brand_industry'),
                                'created_at': datetime.now(),
                                'updated_at': datetime.now()
                            })
                        
                        if new_companies:
                            # Upsert based on source_id (encryptBrandId)
                            # Postgres requires constraint name or index elements
                            # Company.source_id is unique
                            stmt_ins = insert(Company).values(new_companies)
                            stmt_ins = stmt_ins.on_conflict_do_update(
                                index_elements=['source_id'],
                                set_={
                                    'name': stmt_ins.excluded.name,
                                    'updated_at': datetime.now()
                                }
                            )
                            await session.execute(stmt_ins)
                            
                            # Re-fetch ids
                            stmt = select(Company).where(Company.source_id.in_(missing_companies.keys()))
                            res = await session.execute(stmt)
                            for com in res.scalars():
                                brand_map_source_id[com.source_id] = com.id

                    # 3. Prepare Jobs
                    job_rows = []
                    for item in regular_inserts:
                        # Logic to parse salary
                        salary_desc = item.get('salary_desc', '')
                        salary_min = 0
                        salary_max = 0
                        match = re.search(r'(\d+)-(\d+)K', salary_desc, re.IGNORECASE)
                        if match:
                            salary_min = int(match.group(1)) * 1000
                            salary_max = int(match.group(2)) * 1000
                        
                        source_url = f"https://www.zhipin.com/job_detail/{item.get('encrypt_job_id', '')}.html"
                        
                        # IDs
                        ind_id = industry_map_code_id.get(item.get('industry_code'))
                        com_id = brand_map_source_id.get(item.get('encrypt_brand_id'))
                        
                        job_rows.append({
                            'title': item.get('job_name'),
                            'salary_min': salary_min,
                            'salary_max': salary_max,
                            'salary_desc': salary_desc,
                            'location': (item.get('city_name') or '') + (item.get('area_district') or '') + (item.get('business_district') or ''),
                            'experience': item.get('job_experience'),
                            'education': item.get('job_degree'),
                            'tags': json.dumps(item.get('skills', []), ensure_ascii=False),
                            'job_labels': json.dumps(item.get('job_labels', []), ensure_ascii=False),
                            'welfare': json.dumps(item.get('welfare_list', []), ensure_ascii=False),
                            'source_site': 'BossZhipin',
                            'source_url': source_url,
                            'encrypt_job_id': item.get('encrypt_job_id'),
                            'company_id': com_id,
                            'industry_id': ind_id,
                            'industry_code': item.get('industry_code'),
                            'city_code': item.get('city_code'),
                            'longitude': float(item.get('longitude') or 0),
                            'latitude': float(item.get('latitude') or 0),
                            'boss_name': item.get('boss_name'),
                            'boss_title': item.get('boss_title'),
                            'boss_avatar': item.get('boss_avatar'),
                            'publish_date': datetime.now(),
                            'updated_at': datetime.now(),
                            'created_at': datetime.now(),
                            'is_crawl': 0
                        })

                    if job_rows:
                        # 4. Bulk Upsert Jobs
                        stmt = insert(Job).values(job_rows)
                        
                        # Update Map excluding primary key and created_at
                        # Use unique constraint on `encrypt_job_id` or `source_url`?
                        # Job model: encrypt_job_id is UNIQUE, source_url is UNIQUE.
                        # We use encrypt_job_id as the primary deduplication key usually.
                        
                        update_cols = {
                            'title': stmt.excluded.title,
                            'salary_min': stmt.excluded.salary_min,
                            'salary_max': stmt.excluded.salary_max,
                            'updated_at': datetime.now()
                            # Do NOT update is_crawl on duplicate key for new list items, 
                            # as we don't want to reset it if we already crawled detail.
                        }
                        
                        stmt = stmt.on_conflict_do_update(
                            index_elements=['encrypt_job_id'],
                            set_=update_cols
                        ).returning(Job.id)
                        res = await session.execute(stmt)
                        upserted_ids = res.scalars().all()
                        
                        logger.info(f"Batch wrote {len(job_rows)} jobs.")
                        
                        # 触发 ES 同步
                        try:
                            from tasks.es_sync import sync_job_to_es
                            for jid in upserted_ids:
                                sync_job_to_es.delay(jid)
                        except Exception as e:
                            logger.warning(f"Failed to dispatch Celery sync task for new batch jobs: {e}")
