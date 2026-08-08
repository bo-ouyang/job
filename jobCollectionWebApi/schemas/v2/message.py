from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import field_serializer

from common.databases.models.message import MessageType
from schemas.v2.common import V2Model


class MessageView(V2Model):
    id: int
    title: Optional[str] = None
    content: str
    type: MessageType
    is_read: bool
    category: Optional[str] = None
    status: Optional[str] = None
    action_type: Optional[str] = None
    action_data: Optional[Dict[str, Any]] = None
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    created_at: datetime

    @field_serializer("id")
    def serialize_id(self, value: int) -> str:
        return str(value)


class MessagePageResponse(V2Model):
    items: List[MessageView]
    total: int
    skip: int
    limit: int
