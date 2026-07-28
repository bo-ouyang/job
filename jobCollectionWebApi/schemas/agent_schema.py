from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from typing_extensions import Annotated


ConversationStatus = Literal["active", "archived"]
RunStatus = Literal["queued", "running", "waiting_user", "completed", "failed", "cancelled"]
MessageRole = Literal["user", "assistant", "tool", "system"]
SnowflakeId = Annotated[str, BeforeValidator(lambda value: str(value))]


class AgentConversationCreate(BaseModel):
    title: str = Field(default="新的职业规划", min_length=1, max_length=200)
    context: Optional[Dict[str, Any]] = None


class AgentConversationUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    status: Optional[ConversationStatus] = None
    summary: Optional[str] = None


class AgentConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId
    user_id: SnowflakeId
    title: str
    status: ConversationStatus
    summary: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AgentMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    message_type: str = Field(default="text", min_length=1, max_length=30)
    context: Optional[Dict[str, Any]] = None


class AgentMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId
    conversation_id: SnowflakeId
    user_id: SnowflakeId
    role: MessageRole
    message_type: str
    content: str
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        validation_alias="metadata_json",
        serialization_alias="metadata",
    )
    created_at: Optional[datetime] = None


class AgentRunCreate(BaseModel):
    goal: Optional[str] = Field(default=None, max_length=20000)


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId
    conversation_id: SnowflakeId
    user_id: SnowflakeId
    input_message_id: Optional[SnowflakeId] = None
    status: RunStatus
    goal: Optional[str] = None
    current_node: Optional[str] = None
    step_count: int
    tool_call_count: int
    state_snapshot: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    status_updated_at: Optional[datetime] = None


class CareerProfileUpdate(BaseModel):
    education: Optional[Dict[str, Any]] = None
    skills: Optional[List[Dict[str, Any]]] = None
    experience: Optional[List[Dict[str, Any]]] = None
    preferences: Optional[Dict[str, Any]] = None
    constraints: Optional[Dict[str, Any]] = None
    goals: Optional[Dict[str, Any]] = None
    confidence: Optional[Dict[str, Any]] = None


class CareerProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId
    user_id: SnowflakeId
    education: Optional[Dict[str, Any]] = None
    skills: Optional[List[Dict[str, Any]]] = None
    experience: Optional[List[Dict[str, Any]]] = None
    preferences: Optional[Dict[str, Any]] = None
    constraints: Optional[Dict[str, Any]] = None
    goals: Optional[Dict[str, Any]] = None
    confidence: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AgentConversationListResponse(BaseModel):
    items: List[AgentConversationResponse]
    total: int
    page: int = 1
    page_size: int = 20


class AgentConversationDetailResponse(BaseModel):
    conversation: AgentConversationResponse
    messages: List[AgentMessageResponse]
    latest_run: Optional[AgentRunResponse] = None


class AgentMessageSubmissionResponse(BaseModel):
    message: AgentMessageResponse
    run: AgentRunResponse
