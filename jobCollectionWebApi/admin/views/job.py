from starlette_admin import row_action
from common.databases.PostgresManager import db_manager
from common.databases.models.job import Job
from .base import OperationsRestrictedView

class JobView(OperationsRestrictedView):
    fields = [Job.id, Job.title, Job.company, Job.salary_desc, Job.location, Job.is_active, Job.created_at]
    exclude_fields_from_create = [Job.created_at, Job.updated_at]
    exclude_fields_from_edit = [Job.created_at, Job.updated_at]
    search_builder = True

    @row_action(
        name="take_down_job",
        text="下架",
        confirmation="确定要下架该职位吗？",
        icon_class="fas fa-eye-slash",
        action_btn_class="btn-warning",
        submit_btn_text="确认下架",
        submit_btn_class="btn-warning",
    )
    async def take_down_job(self, request, pk):
        async with db_manager.async_session() as session:
            obj = await session.get(Job, int(pk))
            if obj:
                title = obj.title
                obj.is_active = False
                session.add(obj)
                await session.commit()
                await self._log_action(request, "OFFLINE", obj, f"Took down job {title}")
        return "职位已下架"

    @row_action(
        name="publish_job",
        text="上架",
        confirmation="确定要重新上架该职位吗？",
        icon_class="fas fa-eye",
        action_btn_class="btn-info",
        submit_btn_text="确认上架",
        submit_btn_class="btn-info",
    )
    async def publish_job(self, request, pk):
        async with db_manager.async_session() as session:
            obj = await session.get(Job, int(pk))
            if obj:
                title = obj.title
                obj.is_active = True
                session.add(obj)
                await session.commit()
                await self._log_action(request, "PUBLISH", obj, f"Published job {title}")
        return "职位已上架"
