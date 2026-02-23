import json
import time
import os
from aiohttp import web
from sqlalchemy import select, update
from common.databases.PostgresManager import db_manager
from common.databases.models.spider_boss_crawl_url import SpiderBossCrawlUrl
from jobCollection.items.boss_job_item import BossJobItem
from .boss_base_spider import BossBaseSpider
from datetime import datetime
from scrapy.exceptions import CloseSpider
import hashlib
class BossListSpider(BossBaseSpider):
    name = "boss_list"
    allowed_domains = ["zhipin.com"]
    TASK_FILE = "task_status.json"
    
    custom_settings = {
        "DOWNLOAD_TIMEOUT": 1800,
        "CONCURRENT_REQUESTS": 1,
        "ITEM_PIPELINES": {
            "jobCollection.pipelines.redis_dedup_pipeline.RedisDeduplicationPipeline": 200,
            "jobCollection.pipelines.boss_pipeline.BossJobPipeline": 300,
        }
    }

    def __init__(self, task_id=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_task_id = None
        self.target_task_id = int(task_id) if task_id else None
        self.redis_key = "boss_spider_list_queue"
        self.task_url = ''
        self.hashlib = hashlib

    async def push_monitor_command(self, url):
        """Push command with request ID for Controller"""
        req_id = self.hashlib.md5(url.encode('utf-8')).hexdigest()
        payload = {
            "url": url,
            "req_id": req_id,
            "type": "list",
            "timestamp": time.time()
        }
        self.redis_client.lpush("boss_monitor_command_queue", json.dumps(payload))
        self.logger.info(f"Pushed Monitor Command: {url} (ReqID: {req_id})")
        # Initialize status for Controller to wait on
        self.redis_client.set(req_id, 'processing', ex=300)

    async def handle_redis_data(self, data):
        """Process data from Redis Queue"""
        try:
            data_type = data.get('type')
            
            if data_type == 'list':
                await self.process_list_data(data)
                self.logger.info("Processed Redis Data for List")
            else:
                 self.logger.warning(f"Unknown Data Type from Redis for Monitor: {data_type}")

        except Exception as e:
            self.logger.error(f"Error handling Redis data: {e}")

    async def process_list_data(self, payload):
        job_list = payload.get('data', [])
        has_more = payload.get('has_more', False)
        source_url = payload.get('url', '')
        # --- Extract Context from URL ---
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
        parsed_url = urlparse(source_url)
        query_params = parse_qs(parsed_url.query)
        
        url_industry = query_params.get('industry', [None])[0]
        url_city = query_params.get('city', [None])[0]
        current_page = int(query_params.get('page', ['1'])[0])

        req_id = self.hashlib.md5(self.task_url.encode('utf-8')).hexdigest()
        self.logger.info(f"Received List: {len(job_list)} jobs. has_more={has_more}, page={current_page}")
        
        if job_list:
            for job in job_list:
                item = BossJobItem()
                item['job_name'] = job.get('jobName')
                item['salary_desc'] = job.get('salaryDesc')
                item['job_experience'] = job.get('jobExperience')
                item['job_degree'] = job.get('jobDegree')
                item['city_name'] = job.get('cityName')
                item['area_district'] = job.get('areaDistrict')
                item['business_district'] = job.get('businessDistrict')
                item['job_labels'] = job.get('jobLabels', [])
                item['skills'] = job.get('skills', [])
                item['welfare_list'] = job.get('welfareList', [])
                item['encrypt_job_id'] = job.get('encryptJobId')
                item['encrypt_brand_id'] = job.get('encryptBrandId')
                item['brand_name'] = job.get('brandName')
                item['brand_logo'] = job.get('brandLogo')
                item['brand_stage_name'] = job.get('brandStageName')
                item['brand_industry'] = job.get('brandIndustry')
                item['brand_scale_name'] = job.get('brandScaleName')
                item['longitude'] = job.get('gps', {}).get('longitude') if job.get('gps') else None
                item['latitude'] = job.get('gps', {}).get('latitude') if job.get('gps') else None
                item['boss_name'] = job.get('bossName')
                item['boss_title'] = job.get('bossTitle')
                item['boss_avatar'] = job.get('bossAvatar')
                
                # Use URL Industry if available, fallback to job's own
                item['industry_code'] = int(url_industry) if url_industry else int(job.get('industry', ''))
                if url_city:
                    item['city_code'] = int(url_city)
                
                await self.item_queue.put(item)
        
        # --- Pagination / Status Logic ---
        if has_more:
            self.logger.info(f"Page {current_page} processed. has_more=True. Signaling GUI to scroll.")
            # Signal GUI to continue scrolling
            self.redis_client.set(req_id, 'more', ex=300)
            
            # Update DB page count
            # if self.current_task_id:
            #     await self.update_task_page(self.current_task_id, current_page + 1)
        else:
            self.logger.info("No more pages (has_more=False). Task Done.")
            self.redis_client.set(req_id, 'done', ex=300)
            
            if self.current_task_id:
                await self.update_db_status(self.current_task_id, 'done')
                self.current_task_id = None # Free up for next task

    async def update_task_page(self, task_id, page):
         async with (await db_manager.get_session()) as session:
            stmt = update(SpiderBossCrawlUrl).where(SpiderBossCrawlUrl.id == task_id).values(page=page, updated_at=datetime.now())
            await session.execute(stmt)
            await session.commit()

    async def check_task_logic(self):
        """Sync Logic implementation - Replaced file sync with direct DB/Redis checks if needed"""
        if self.current_task_id is None:
            await self.fetch_and_assign_new_task()
        elif self.current_task_id:
            await self.sync_db_status_to_gui()

    async def sync_db_status_to_gui(self):
        """Check DB status (Pause/Stop)"""
        try:
            if not self.current_task_id:
                return

            async with (await db_manager.get_session()) as session:
                task = await session.get(SpiderBossCrawlUrl, self.current_task_id)
                if not task:
                    return

                db_status = task.status
                
                if db_status == 'paused':
                    self.logger.info(f"Task {self.current_task_id} PAUSED by User.")
                    # Wait logic could be added here or in main loop
                
                elif db_status == 'stopped':
                    self.logger.info(f"Task {self.current_task_id} STOPPED by User.")
                    await self.update_db_status(self.current_task_id, 'stopped')
                    self.current_task_id = None
                    if self.target_task_id:
                        raise CloseSpider(reason="Task Stopped")

                elif db_status in ['pending', 'processing']:
                    if db_status == 'pending':
                         task.status = 'processing'
                         await session.commit()

        except CloseSpider:
            raise
        except Exception as e:
            self.logger.error(f"Error syncing DB status: {e}")

    async def fetch_and_assign_new_task(self):
        async with (await db_manager.get_session()) as session:
            # Sort by ID only (spider_boss_crawl_url has no priority)
            stmt = select(SpiderBossCrawlUrl).where(SpiderBossCrawlUrl.status == 'pending').order_by(SpiderBossCrawlUrl.id.asc())
            
            if self.target_task_id:
                stmt = stmt.where(SpiderBossCrawlUrl.id == self.target_task_id)
                
            stmt = stmt.limit(1)
            result = await session.execute(stmt)
            task = result.scalar_one_or_none()
            
            if task:
                self.logger.info(f"Assigning New Task: [{task.id}] {task.url}")
                task.status = 'processing'
                await session.commit()
                
                self.current_task_id = task.id
                self.task_url = task.url
                # Push to Redis for Controller
                await self.push_monitor_command(task.url)

    async def update_db_status(self, task_id, status, error_msg=None):
        async with (await db_manager.get_session()) as session:
            stmt = update(SpiderBossCrawlUrl).where(SpiderBossCrawlUrl.id == task_id).values(status=status, last_crawl_time=datetime.now(), error_msg=error_msg)
            await session.execute(stmt)
            await session.commit()
