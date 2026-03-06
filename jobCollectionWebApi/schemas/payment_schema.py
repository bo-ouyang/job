from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PaymentMethodEnum(str, Enum):
    ALIPAY = "alipay"
    WECHAT = "wechat"
    WALLET = "wallet"


class ProductTypeEnum(str, Enum):
    RESUME_ANALYSIS = "resume_analysis"


class PaymentStatusEnum(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    EXPIRED = "expired"
    REFUNDED = "refunded"


class PaymentOrderCreate(BaseModel):
    product_id: Optional[int] = Field(None, description="Product ID")
    payment_method: PaymentMethodEnum = Field(..., description="Payment method")
    amount: Optional[float] = None
    product_type: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None


class PaymentOrderResponse(BaseModel):
    order_no: str
    pay_url: Optional[str] = None
    qr_code_url: Optional[str] = None
    pay_params: Optional[Dict[str, Any]] = None
    amount: float
    status: PaymentStatusEnum


class PaymentOrderSchema(BaseModel):
    id: int
    order_no: str
    user_id: int
    amount: float
    payment_method: str
    status: str
    product_type: str
    created_at: datetime
    paid_at: Optional[datetime] = None
    transaction_id: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None
    failure_reason: Optional[str] = None

    class Config:
        from_attributes = True


class PaymentOrderPage(BaseModel):
    items: List[PaymentOrderSchema]
    total: int
    page: int
    size: int


class PaymentNotifyResponse(BaseModel):
    status: str = "success"
    message: str = "OK"
