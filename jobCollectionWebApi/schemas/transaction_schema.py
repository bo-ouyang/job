from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class TransactionSchema(BaseModel):
    id: int
    amount: float
    balance_after: float
    transaction_type: str
    description: Optional[str] = None
    created_at: datetime
    related_order_no: Optional[str] = None

    class Config:
        from_attributes = True


class TransactionPage(BaseModel):
    items: List[TransactionSchema]
    total: int
    page: int
    size: int
