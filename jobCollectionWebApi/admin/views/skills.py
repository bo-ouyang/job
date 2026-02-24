from common.databases.models.skills import Skills
from .base import OperationsRestrictedView

class SkillsView(OperationsRestrictedView):
    fields = [Skills.id, Skills.name, Skills.category, Skills.created_at]
    search_builder = True
