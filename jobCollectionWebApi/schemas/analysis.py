from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from .base import TimestampSchema

class AnalysisResultBase(BaseModel):
    analysis_type: str
    parameters: Optional[Dict[str, Any]] = None
    result_data: Optional[Dict[str, Any]] = None

class AnalysisResultCreate(AnalysisResultBase):
    pass

class AnalysisResultUpdate(BaseModel):
    result_data: Optional[Dict[str, Any]] = None

class AnalysisResultInDB(AnalysisResultBase, TimestampSchema):
    id: int

    class Config:
        from_attributes = True

class AnalysisResultList(BaseModel):
    items: List[AnalysisResultInDB]
    total: int
    page: int
    size: int
    pages: int

class UserQueryBase(BaseModel):
    query_type: str
    parameters: Optional[Dict[str, Any]] = None
    result_count: Optional[int] = None
    user_id: Optional[int] = None
    user_ip: Optional[str] = None
    user_agent: Optional[str] = None

class UserQueryCreate(UserQueryBase):
    pass

class UserQueryInDB(UserQueryBase, TimestampSchema):
    id: int

    class Config:
        from_attributes = True

class APILogBase(BaseModel):
    path: str
    method: str
    status_code: int
    process_time: float
    user_id: Optional[int] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

class APILogCreate(APILogBase):
    pass


class MajorBase(BaseModel):
    name: str
    code: Optional[str] = None
    level: int = 0
    description: Optional[str] = None

class MajorInDB(MajorBase):
    id: int
    parent_id: Optional[int] = None

    class Config:
        from_attributes = True

class MajorPresetItem(BaseModel):
    major_name: str
    keywords: str
    hot_index: int = 0

class MajorCategory(BaseModel):
    name: str # The category name (e.g. "工学")
    majors: List[MajorPresetItem]

class AIAdviceRequest(BaseModel):
    major_name: str
    skills: List[str]

class APILogInDB(APILogBase, TimestampSchema):
    id: int

    class Config:
        from_attributes = True

class MajorAnalysisRequest(BaseModel):
    keywords: List[str]
    major_name: Optional[str] = None
    location: Optional[str] = None

class TaskLogBase(BaseModel):
    task_id: str
    task_name: str
    status: str
    args: Optional[Dict[str, Any] | List[Any]] = None
    kwargs: Optional[Dict[str, Any]] = None
    result: Optional[str] = None
    worker: Optional[str] = None
    execution_time: Optional[float] = None

class TaskLogCreate(TaskLogBase):
    pass

class TaskLogUpdate(BaseModel):
    status: Optional[str] = None
    result: Optional[str] = None
    execution_time: Optional[float] = None

class TaskLogInDB(TaskLogBase, TimestampSchema):
    id: int
    class Config:
        from_attributes = True
