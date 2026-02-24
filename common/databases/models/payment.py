from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum, JSON, BigInteger
from sqlalchemy.orm import relationship
from datetime import datetime
from common.databases.models.base import Base
import enum
from common.utils.snowflake import generate_id
from sqlalchemy.dialects.postgresql import JSONB

class PaymentMethod(str, enum.Enum):
    ALIPAY = "alipay"
    WECHAT = "wechat"
    WALLET = "wallet"

class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    EXPIRED = "expired"
    REFUNDED = "refunded"

class ProductType(str, enum.Enum):
    RESUME_ANALYSIS = "resume_analysis"

class PaymentOrder(Base):
    __tablename__ = "payment_orders"

    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    order_no = Column(String(64), unique=True, index=True, nullable=False, comment="系统订单号")
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    product_id = Column(BigInteger, ForeignKey("products.id"), nullable=True)
    product_snapshot = Column(JSONB, nullable=True, comment="购买时商品信息快照")
    
    amount = Column(Float, nullable=False, comment="支付金额")
    payment_method = Column(String(20), nullable=False, comment="支付方式: alipay, wechat")
    status = Column(String(20), default=PaymentStatus.PENDING, index=True, comment="状态: pending, paid, failed")
    product_type = Column(String(50), default=ProductType.RESUME_ANALYSIS, comment="产品类型")
    
    # 存储额外数据，如关联的简历ID或分析任务ID
    extra_data = Column(JSONB, nullable=True)
    
    # 第三方交易号 (trade_no)
    transaction_id = Column(String(128), nullable=True, comment="第三方支付流水号")
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    paid_at = Column(DateTime, nullable=True, comment="支付成功时间")

    # Relationships
    user = relationship("User", back_populates="payment_orders")
