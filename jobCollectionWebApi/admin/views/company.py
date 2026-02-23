from common.databases.models.company import Company
from .base import OperationsRestrictedView

class CompanyView(OperationsRestrictedView):
    fields = [Company.id, Company.name, Company.industry, Company.scale]
    exclude_fields_from_create = [Company.created_at, Company.updated_at]
    exclude_fields_from_edit = [Company.created_at, Company.updated_at]
