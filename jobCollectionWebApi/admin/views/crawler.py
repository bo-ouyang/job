from starlette_admin import action, row_action, StringField, TextAreaField
from common.databases.models.boss_spider_filter import BossSpiderFilter
from common.databases.models.boss_crawl_task import BossCrawlTask
from common.databases.models.crawler_control import CrawlerEvent, CrawlerRun, CrawlerWorker
from common.databases.PostgresManager import db_manager
from services.crawler_service import CrawlerService
from services.v2.crawler_control_service import crawler_control_service
from .base import AdminRestrictedView


async def dispatch_crawler_control_command(request, *, task_id: str, command: str):
    """Route legacy admin buttons through the cross-machine control plane."""

    actor = getattr(request.state, "user_obj", None)
    ip_address = request.client.host if getattr(request, "client", None) else None
    async with db_manager.async_session() as session:
        result = await crawler_control_service.command_task(
            session,
            task_id=int(task_id),
            command=command,
            actor=actor,
            ip_address=ip_address,
        )
        await session.commit()
        return result

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
        result = await dispatch_crawler_control_command(request, task_id=pk, command="retry")
        return f"任务已进入重试队列，运行ID: {result.run_id}"

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
        result = await dispatch_crawler_control_command(request, task_id=pk, command="pause")
        return f"已请求暂停，运行状态: {result.status}"

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
        result = await dispatch_crawler_control_command(request, task_id=pk, command="resume")
        return f"任务已进入恢复队列，运行ID: {result.run_id}"

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
        result = await dispatch_crawler_control_command(request, task_id=pk, command="stop")
        return f"已请求停止，运行状态: {result.status}"

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
        result = await dispatch_crawler_control_command(request, task_id=pk, command="start")
        return f"任务已进入启动队列，运行ID: {result.run_id}"


class CrawlerWorkerAdminView(AdminRestrictedView):
    label = "爬虫执行节点"
    can_create = False
    can_edit = False
    can_delete = False
    fields = [
        CrawlerWorker.id,
        CrawlerWorker.name,
        CrawlerWorker.hostname,
        CrawlerWorker.platform,
        CrawlerWorker.status,
        CrawlerWorker.max_concurrency,
        CrawlerWorker.active_runs,
        CrawlerWorker.last_heartbeat_at,
        CrawlerWorker.updated_at,
    ]
    sortable_fields = [CrawlerWorker.last_heartbeat_at, CrawlerWorker.updated_at]
    column_default_sort = [(CrawlerWorker.last_heartbeat_at, True)]


class CrawlerRunAdminView(AdminRestrictedView):
    label = "爬虫运行监控"
    can_create = False
    can_edit = False
    can_delete = False
    fields = [
        CrawlerRun.id,
        CrawlerRun.task_id,
        CrawlerRun.worker_id,
        CrawlerRun.spider_name,
        CrawlerRun.desired_status,
        CrawlerRun.status,
        CrawlerRun.pid,
        CrawlerRun.metrics,
        CrawlerRun.exit_code,
        CrawlerRun.error_msg,
        CrawlerRun.started_at,
        CrawlerRun.heartbeat_at,
        CrawlerRun.finished_at,
        CrawlerRun.created_at,
    ]
    sortable_fields = [CrawlerRun.created_at, CrawlerRun.heartbeat_at, CrawlerRun.finished_at]
    column_default_sort = [(CrawlerRun.created_at, True)]


class CrawlerEventAdminView(AdminRestrictedView):
    label = "爬虫运行事件"
    can_create = False
    can_edit = False
    can_delete = False
    fields = [
        CrawlerEvent.id,
        CrawlerEvent.run_id,
        CrawlerEvent.worker_id,
        CrawlerEvent.event_type,
        CrawlerEvent.level,
        CrawlerEvent.message,
        CrawlerEvent.created_at,
    ]
    sortable_fields = [CrawlerEvent.created_at]
    column_default_sort = [(CrawlerEvent.created_at, True)]

