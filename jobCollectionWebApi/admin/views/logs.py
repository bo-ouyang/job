from common.databases.models.admin_log import AdminLog
from common.databases.models.analysis import TaskLog
from .base import AdminRestrictedView

class AdminLogView(AdminRestrictedView):
    fields = [AdminLog.id, AdminLog.username, AdminLog.action, AdminLog.model_name, AdminLog.object_id, AdminLog.details, AdminLog.ip_address, AdminLog.created_at]
    
    def can_create(self, request):
        return False

    def can_edit(self, request):
        return False

    def can_delete(self, request):
        return False
    
    sortable_fields = [AdminLog.created_at]


class TaskLogView(AdminRestrictedView):
    fields = [TaskLog.task_id, TaskLog.task_name, TaskLog.status, TaskLog.args, TaskLog.result, TaskLog.execution_time, TaskLog.created_at]
    
    can_create = False
    can_edit = False
    can_delete = False
    
    sortable_fields = [TaskLog.created_at]
    column_default_sort = [(TaskLog.created_at, True)]
