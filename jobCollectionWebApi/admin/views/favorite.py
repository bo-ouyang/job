from common.databases.models.favorite import FavoriteJob
from .base import OperationsRestrictedView

class FavoriteJobView(OperationsRestrictedView):
    fields = [FavoriteJob.id, FavoriteJob.user, FavoriteJob.job, FavoriteJob.created_at]
    exclude_fields_from_create = [FavoriteJob.created_at]
