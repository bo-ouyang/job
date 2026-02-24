import json
import os
import time
from datetime import datetime
from aiohttp import web
from scrapy import Selector
from sqlalchemy import select, update
from common.databases.PostgresManager import db_manager
from common.databases.models.job import Job
from .boss_base_spider import BossBaseSpider
from jobCollection.items.boss_job_item import BossJobDetailItem
from urllib.parse import urlparse

class BossDetailSpider(BossBaseSpider):
    name = "boss_detail"
    # Specific task file for details to avoid collision if we ever separate them
    #TASK_FILE = "task_detail_status.json" 
    
    custom_settings = {
        # "DOWNLOAD_TIMEOUT": 1800,
        # "CONCURRENT_REQUESTS": 1,
        # "ITEM_PIPELINES": {
        #     "jobCollection.pipelines.boss_pipeline.BossJobPipeline": 300,
        # }
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_job_id = None # encrypt_job_id
        self.task_start_time = None
        self.redis_key = "boss_spider_detail_queue"

    async def handle_redis_data(self, data):
        """Process data from Redis Queue"""
        try:
            url = data.get('url')
            payload_data = data.get('data')
            data_type = data.get('type')

            if data_type == 'detail_html':
                # payload_data is HTML string
                await self.process_detail_html(url, payload_data)
                self.logger.info(f"开始处理详情页： {url}")
            else:
                self.logger.warning(f"Unknown Data Type from Redis: {data_type}")

        except Exception as e:
            self.logger.error(f"处理Redis数据失败: {e}")

    async def process_detail_html(self, url, html_content):
        try:
            sel = Selector(text=html_content)
            
            # Extract basic info
            job_desc = sel.css('.job-detail-section > .job-sec-text::text').getall()
            job_desc = "\n".join([x.strip() for x in job_desc if x.strip()])
            
          
            parsed_path = urlparse(url).path        # 提取 /job_detail/12345.html (自动去掉 ?ka=...)
            filename = os.path.basename(parsed_path) # 提取 12345.html
            encrypt_job_id = filename.replace(".html", "") # 提取 12345
          
            success = await self.update_job_in_db(encrypt_job_id, job_desc)
            
            if success:
                self.logger.info(f"成功更新职位 {encrypt_job_id}")
                self.redis_client.set(encrypt_job_id,'done',ex=10)
                # Check if this result matches the current waiting task
                if self.current_job_id == encrypt_job_id:
                     # Mark Task as Done
                    self.current_job_id = None # Reset current_job_id after task completion
                    self.task_start_time = None
                else:
                     self.logger.warning(f"收到了延迟/非请求数据 {encrypt_job_id}。当前任务是 {self.current_job_id}。不重置状态。")
                
                #await self.fetch_and_assign_new_task()
            else:
                self.logger.error(f"更新职位 {encrypt_job_id} 到数据库失败")

        except Exception as e:
             self.logger.error(f"处理HTML失败: {e}")

    async def update_job_in_db(self, encrypt_job_id, job_desc):
        try:
            async with (await db_manager.get_session()) as session:
                stmt = select(Job).where(Job.encrypt_job_id == encrypt_job_id)
                result = await session.execute(stmt)
                job = result.scalar_one_or_none()
                
                if job:
                    job.description = job_desc
                    #job.location = location  # Assuming Job model has location field? If not, skip or use address
                    # job.skills = ... # parse from html if needed
                    job.is_crawl = 1
                    job.updated_at = datetime.now()
                    await session.commit()
                    
                    return True
                else:
                    self.logger.warning(f"Job {encrypt_job_id} not found in DB")
                    return False
        except Exception as e:
            self.logger.error(f"DB Update Error: {e}")
            return False

    async def check_task_logic(self):
        """Check if we need to fetch a new task"""
        # We no longer use the file. We track state via self.current_job_id
        # processing_detail_html sets self.current_job_id = None when done.
        
        if self.current_job_id is None:
            self.logger.info("当前任务ID为空，正在获取新任务...")
            await self.fetch_and_assign_new_task()
        else:
            # Check for timeout (e.g. 60 seconds)
            if self.task_start_time and (time.time() - self.task_start_time > 60):
                self.logger.warning(f"任务 {self.current_job_id} 超时。正在重置...")
                self.redis_client.set(self.current_job_id, 'timeout', ex=60)
                self.current_job_id = None
                self.task_start_time = None
            else:
                pass

    async def fetch_and_assign_new_task(self):
        # Fetch 1 pending job
        async with (await db_manager.get_session()) as session:
            # Check if we have any pending jobs
            # Try to pick one that hasn't been crawled (is_crawl=0)
            stmt = select(Job).where(
                (Job.is_crawl == 0) & 
                (Job.encrypt_job_id != None) & 
                (Job.encrypt_job_id != '')
            ).limit(1).order_by(Job.id.asc())
            
            result = await session.execute(stmt)
            job = result.scalar_one_or_none()
            
            if job:
                self.logger.info(f"Assigning Job: {job.title} ({job.encrypt_job_id})")
                self.current_job_id = job.encrypt_job_id
                self.task_start_time = time.time()
                
                url = f"https://www.zhipin.com/job_detail/{job.encrypt_job_id}.html"
                
                # Set processing state (no expiry or long expiry to be safe)
                self.redis_client.set(job.encrypt_job_id, 'processing', ex=30)
                
                # Mark as processing in DB to prevent duplicates if spider restarts
                job.is_crawl = 2 
                job.updated_at = datetime.now()
                await session.commit()
                
                # Push to Redis for Controller
                await self.push_browser_command(url)
            else:
                self.logger.info("没有找到待处理的任务。")
                # Optional: Push a "wait" or "stop" command?
                # For now, just do nothing, controller will wait on BLPOP
                
  
