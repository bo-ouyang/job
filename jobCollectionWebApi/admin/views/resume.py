from common.databases.models.resume import Resume
from .base import OperationsRestrictedView

class ResumeView(OperationsRestrictedView):
    fields = [Resume.id, Resume.name, Resume.user, Resume.desired_position]
    exclude_fields_from_create = [Resume.created_at, Resume.updated_at]
