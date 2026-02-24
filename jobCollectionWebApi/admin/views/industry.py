from common.databases.models.industry import Industry
from .base import OperationsRestrictedView

class IndustryView(OperationsRestrictedView):
    fields = [Industry.id, Industry.code, Industry.name, Industry.level, Industry.parent]
    search_builder = True
