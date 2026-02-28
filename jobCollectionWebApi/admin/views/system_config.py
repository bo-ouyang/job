from common.databases.models.system_config import SystemConfig

from .base import AdminRestrictedView


class SystemConfigView(AdminRestrictedView):
    fields = [
        SystemConfig.id,
        SystemConfig.key,
        SystemConfig.category,
        SystemConfig.value,
        SystemConfig.description,
        SystemConfig.is_active,
        SystemConfig.updated_at,
    ]
    exclude_fields_from_create = [SystemConfig.created_at, SystemConfig.updated_at]
    exclude_fields_from_edit = [SystemConfig.created_at, SystemConfig.updated_at]
    search_builder = True
