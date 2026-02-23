from starlette_admin import action, row_action, TextAreaField
from common.databases.models.proxy import Proxy
from .base import AdminRestrictedView
from jobCollectionWebApi.tasks.proxy_tasks import check_proxies_task, fetch_proxies_task, sync_proxies_to_db_task

class ProxyView(AdminRestrictedView):
    label = "代理管理"
    icon = "fa fa-globe"
    
    fields = [
        Proxy.id,
        Proxy.ip,
        Proxy.port,
        Proxy.protocol,
        Proxy.source,
        Proxy.score,
        Proxy.latency,
        Proxy.is_active,
        Proxy.fail_count,
        Proxy.last_checked_at,
        Proxy.created_at
    ]
    
    search_builder = True
    sortable_fields = [Proxy.score, Proxy.latency, Proxy.last_checked_at]
    column_default_sort = [(Proxy.score, True)]

    @action(
        name="check_proxies_action",
        text="立即检测所有代理",
        confirmation="确定要立即触发代理检测任务吗？(后台运行)",
        submit_btn_text="立即检测",
        submit_btn_class="btn-primary"
    )
    async def check_proxies_action(self, request, pks):
        # Trigger Celery task
        check_proxies_task.delay()
        return "代理检测任务已提交"

    @action(
        name="fetch_proxies_action",
        text="立即获取新代理",
        confirmation="请输入代理源URL (Text/HTML with IP:Port):",
        submit_btn_text="立即获取",
        submit_btn_class="btn-success",
        form=[
             TextAreaField(
                "source_url",
                label="代理源URL",
                help_text="输入返回IP:Port列表的URL，例如: http://www.89ip.cn/tqdl.html?api=1&num=100",
                rows=2
            )
        ]
    )
    async def fetch_proxies_action(self, request, pks):
        data = await request.form()
        source_url = data.get("source_url")
        
        if source_url:
            # We need a new task that accepts parameters
            # Or just call legacy fetch_proxies_task if url is empty
            # But celery tasks are async. We should probably create a new task: "fetch_custom_proxies"
            from jobCollectionWebApi.tasks.proxy_tasks import fetch_custom_proxies_task
            fetch_custom_proxies_task.delay(source_url)
            return f"已提交从 {source_url} 获取代理的任务"
        else:
            fetch_proxies_task.delay()
            return "代理获取任务已提交 (默认源)"
        
    @action(
        name="sync_proxies_action",
        text="从Redis同步到DB",
        confirmation="确定要将Redis中的代理状态同步到数据库吗？",
        submit_btn_text="立即同步",
        submit_btn_class="btn-info"
    )
    async def sync_proxies_action(self, request, pks):
        sync_proxies_to_db_task.delay()
        return "同步任务已提交"
