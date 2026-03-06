from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime, BigInteger, Index
from sqlalchemy.sql import func
from common.databases.models.base import Base
from common.utils.snowflake import generate_id

class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        Index("idx_products_category_active", "category", "is_active"),
        Index("idx_products_active_created", "is_active", "created_at"),
    )

    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    name = Column(String(100), nullable=False, index=True, comment="商品名称")
    code = Column(String(50), unique=True, index=True, nullable=False, comment="商品编码 (e.g. wufu_1)")
    description = Column(Text, nullable=True, comment="商品描述")
    
    price = Column(Float, nullable=False, comment="现价")
    original_price = Column(Float, nullable=True, comment="原价")
    
    image_url = Column(String(255), nullable=True, comment="商品图片")
    is_active = Column(Boolean, default=True, comment="是否上架")
    
    category = Column(String(50), index=True, comment="分类: wufu, resume, etc.")
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
