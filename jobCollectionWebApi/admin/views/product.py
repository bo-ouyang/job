from common.databases.models.product import Product
from .base import AdminRestrictedView


class ProductView(AdminRestrictedView):
    fields = [
        Product.id,
        Product.name,
        Product.code,
        Product.category,
        Product.description,
        Product.price,
        Product.original_price,
        Product.is_active,
        Product.updated_at,
    ]
    exclude_fields_from_create = [Product.created_at, Product.updated_at]
    exclude_fields_from_edit = [Product.created_at, Product.updated_at]
    search_builder = True
