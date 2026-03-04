from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum

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

class PaymentOrderCreate(BaseModel):
    product_id: Optional[int] = Field(None, description="商品ID (推荐)")
    # product_type: ProductTypeEnum = Field(..., description="产品类型 (Legacy)") # Make optional or derived
    payment_method: PaymentMethodEnum = Field(..., description="支付方式")
    # amount: float = Field(..., gt=0, description="金额 (Legacy)") # Make optional, backend will override if product_id is set
    
    # 兼容字段
    amount: Optional[float] = None 
    product_type: Optional[str] = None

class PaymentOrderResponse(BaseModel):
    order_no: str
    pay_url: Optional[str] = None # For Alipay
    qr_code_url: Optional[str] = None # For WeChat Native
    pay_params: Optional[Dict[str, Any]] = None # For WeChat JSAPI/App
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

    class Config:
        from_attributes = True

class PaymentNotifyResponse(BaseModel):
    status: str = "success"
    message: str = "OK"
