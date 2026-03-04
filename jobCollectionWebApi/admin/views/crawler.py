from starlette_admin import action, row_action, StringField, TextAreaField
from common.databases.models.boss_spider_filter import BossSpiderFilter
from common.databases.models.boss_crawl_task import BossCrawlTask
from services.crawler_service import CrawlerService
from .base import AdminRestrictedView

class BossSpiderFilterView(AdminRestrictedView):
    label = "爬虫筛选配置"
    fields = [
        BossSpiderFilter.id, 
        BossSpiderFilter.filter_name,
        BossSpiderFilter.filter_value,
        BossSpiderFilter.is_active, 
        BossSpiderFilter.note,
        BossSpiderFilter.updated_at
    ]
    search_builder = True
    
    @action(
        name="generate_tasks",
        text="生成爬取任务",
        confirmation="确定要根据当前配置生成爬取任务吗？",
        submit_btn_text="立即生成",
        submit_btn_class="btn-primary",
        form=[
            TextAreaField(
                "additional_params", 
                label="额外筛选参数", 
                help_text="在此输入想要临时添加的参数 (e.g. page=1&query=python)。\n这些参数将追加到现有的配置后面。",
                rows=3
            )
        ]
    )
    async def generate_tasks(self, request, pks):
        data = await request.form()
        additional_params = data.get("additional_params")
        
        count = await CrawlerService.generate_tasks_from_filters(filter_ids=pks, additional_params=additional_params)
        return f"已生成 {count} 个新任务"

class BossCrawlTaskView(AdminRestrictedView):
    label = "爬虫任务队列"
    fields = [
        BossCrawlTask.id, 
        BossCrawlTask.url, 
        BossCrawlTask.status, 
        BossCrawlTask.priority, 
        BossCrawlTask.last_crawl_time, 
        BossCrawlTask.error_msg, 
        BossCrawlTask.pid,
        BossCrawlTask.created_at
    ]
    search_builder = True
    sortable_fields = [BossCrawlTask.created_at, BossCrawlTask.priority]
    column_default_sort = [(BossCrawlTask.created_at, True)]
    
    # Fix: Hide status field in create form to use database default ('pending')
    exclude_fields_from_create = [BossCrawlTask.status, BossCrawlTask.pid]
    exclude_fields_from_edit = [BossCrawlTask.pid]

    @row_action(
        name="reset_task",
        text="重置",
        confirmation="确定要重置该任务状态为pending吗？",
        icon_class="fas fa-redo",
        action_btn_class="btn-info",
        submit_btn_text="确认重置",
        submit_btn_class="btn-info",
    )
    async def reset_task(self, request, pk):
        await CrawlerService.reset_tasks([pk])
        return "任务已重置"

    @row_action(
        name="pause_task",
        text="暂停",
        confirmation="确定要暂停该任务吗？",
        icon_class="fas fa-pause",
        action_btn_class="btn-warning",
        submit_btn_text="确认暂停",
        submit_btn_class="btn-warning",
    )
    async def pause_task(self, request, pk):
        await CrawlerService.update_task_status([pk], 'paused')
        return "任务已暂停"

    @row_action(
        name="resume_task",
        text="恢复",
        confirmation="确定要恢复该任务吗？",
        icon_class="fas fa-play",
        action_btn_class="btn-success",
        submit_btn_text="确认恢复",
        submit_btn_class="btn-success",
    )
    async def resume_task(self, request, pk):
        await CrawlerService.update_task_status([pk], 'pending')
        return "任务已恢复"

    @row_action(
        name="stop_task",
        text="停止",
        confirmation="确定要停止该任务吗？",
        icon_class="fas fa-stop",
        action_btn_class="btn-danger",
        submit_btn_text="确认停止",
        submit_btn_class="btn-danger",
    )
    async def stop_task(self, request, pk):
        await CrawlerService.update_task_status([pk], 'stopped')
        return "任务已停止"

    @row_action(
        name="run_task",
        text="启动爬虫",
        confirmation="确定要立即启动该任务的爬虫进程吗？(后台运行)",
        icon_class="fas fa-play-circle",
        action_btn_class="btn-primary",
        submit_btn_text="立即启动",
        submit_btn_class="btn-primary",
    )
    async def run_task(self, request, pk):
        # Set to pending so spider can pick it up
        await CrawlerService.update_task_status([pk], 'pending')
        success, msg = await CrawlerService.run_crawler_task(pk)
        if success:
            return f"成功: {msg}"
        else:
            # We should probably return an error, but starlette-admin might just show the string
            return f"启动失败: {msg}"

