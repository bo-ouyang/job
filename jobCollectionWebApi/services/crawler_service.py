from sqlalchemy import select
from common.databases.PostgresManager import db_manager
from common.databases.models.boss_spider_filter import BossSpiderFilter
from common.databases.models.boss_crawl_task import BossCrawlTask
import logging

import logging
import subprocess
import sys
import os

logger = logging.getLogger(__name__)

class CrawlerService:
    @staticmethod
    async def generate_tasks_from_filters(filter_ids: list = None, additional_params: str = None):
        """
        根据选中的筛选器生成爬取任务 (聚合所有选中的筛选器为一个URL)
        :param filter_ids: 选中的筛选器ID列表
        :param additional_params: 额外的手动输入参数
        """
        generated_count = 0
        base_url = "https://www.zhipin.com/web/geek/jobs"
        
        async with db_manager.async_session() as session:
            # 1. 获取筛选器
            stmt = select(BossSpiderFilter).where(BossSpiderFilter.is_active == 1)
            if filter_ids:
                stmt = stmt.where(BossSpiderFilter.id.in_(map(int, filter_ids)))
            
            result = await session.execute(stmt)
            filters = result.scalars().all()
            
            # Helper to create/check task
            async def process_task(url_params):
                if not url_params:
                    return 0
                
                # 去重
                unique_params = list(set(url_params))
                full_url = f"{base_url}?{'&'.join(unique_params)}"
                
                stmt = select(BossCrawlTask).where(BossCrawlTask.url == full_url)
                existing_task = (await session.execute(stmt)).scalar_one_or_none()
                
                if not existing_task:
                    new_task = BossCrawlTask(url=full_url, status='pending')
                    session.add(new_task)
                    return 1
                return 0

            # 2. 聚合所有筛选条件为一个参数列表
            aggregated_params = []
            
            for f in filters:
                if f.filter_name and f.filter_value:
                    key = f.filter_name.strip()
                    val = f.filter_value.strip()
                    aggregated_params.append(f"{key}={val}")

            # 3. 添加额外参数
            if additional_params:
                clean_additional = additional_params.lstrip('?&').strip()
                if clean_additional:
                    # 支持手动输入的 query string (e.g. "a=1&b=2")
                    aggregated_params.append(clean_additional)

            # 4. 生成单个任务
            if aggregated_params:
                generated_count += await process_task(aggregated_params)
            else:
                 logger.warning("No valid params found to generate task.")
            
            await session.commit()
            
        return generated_count

    @staticmethod
    async def reset_tasks(task_ids: list):
        """
        重置指定任务的状态为 pending
        """
        if not task_ids:
            return 0
            
        async with db_manager.async_session() as session:
            for task_id in task_ids:
                task = await session.get(BossCrawlTask, int(task_id))
                if task:
                    task.status = 'pending'
                    task.error_msg = None
                    session.add(task)
            await session.commit()
        return len(task_ids)

    @staticmethod
    async def update_task_status(task_ids: list, status: str):
        """
        批量更新任务状态
        :param task_ids: 任务ID列表
        :param status: 新状态 (pending, processing, paused, stopped, error, done)
        """
        if not task_ids:
            return 0
            
        async with db_manager.async_session() as session:
            for task_id in task_ids:
                task = await session.get(BossCrawlTask, int(task_id))
                if task:
                    task.status = status
                    # 如果是重置为 pending，清除错误信息
                    if status == 'pending':
                        task.error_msg = None
                    session.add(task)
            await session.commit()
        return len(task_ids)

    @staticmethod
    async def run_crawler_task(task_id: int):
        """
        Run a specific crawler task using subprocess
        """
        # 1. Determine paths
        # Service is in jobCollectionWebApi/services/
        # Project root is d:/Code/job
        # Scrapy project is d:/Code/job/jobCollection
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(current_dir))
        scrapy_project_dir = os.path.join(project_root, "jobCollection")
        
        # 2. Check if directory exists
        if not os.path.exists(scrapy_project_dir):
            logger.error(f"Scrapy project directory not found: {scrapy_project_dir}")
            return False, "Scrapy project directory not found"
            
        # 3. Construct command
        # 修复 Bug 1: 真正要启动的爬虫名字叫 `boss_list`，并非 `boss_monitor`
        # 修复拓展: 同时传递 task_id 和 url 供单独页面爬取使用
        
        task_url = ""
        async with db_manager.async_session() as session:
            task = await session.get(BossCrawlTask, int(task_id))
            if task:
                task_url = task.url
                
        cmd = [
            sys.executable, 
            "-m", "scrapy", "crawl", "boss_list", 
            "-a", f"task_id={task_id}",
            "-a", f"task_url={task_url}"
        ]
        
        try:
            logger.info(f"Launching crawler for task {task_id} in {scrapy_project_dir}")
            # Use Popen to run in background (fire and forget)
            subprocess.Popen(
                cmd, 
                cwd=scrapy_project_dir,
                # shell=True # Shell=True might be needed on Windows for path resolution, but problematic for PID
            )
            return True, "Crawler started in background"
        except Exception as e:
            logger.error(f"Failed to launch crawler: {e}")
            return False, str(e)

