from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from .base_schema import TimestampSchema

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
    engine: str = Field(
        default="auto",
        description="AI engine selection: auto | classic | langgraph"
    )
    analysis_params: Optional[Dict[str, Any]] = None
    analysis_result: Optional[Dict[str, Any]] = None

class CareerCompassRequest(BaseModel):
    major_name: str
    target_industry: Optional[int] = None
    target_industry_2: Optional[int] = None
    target_industry_name: Optional[str] = None
    target_industry_2_name: Optional[str] = None
    skill_cloud_data: Optional[List[Dict[str, Any]]] = None

class APILogInDB(APILogBase, TimestampSchema):
    id: int

    class Config:
        from_attributes = True

class MajorAnalysisRequest(BaseModel):
    keywords: List[str]
    major_name: Optional[str] = None
    location: Optional[str] = None

class TaskLogBase(BaseModel):
    task_id: str = Field(..., description="Celery 任务 ID")
    task_name: str = Field(..., description="任务名称")
    #job_id: Optional[int] = Field(None, description="关联职位 ID")
    status: str = Field(..., description="任务状态")
    args: Optional[Union[Dict[str, Any], List[Any]]] = None
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


class CompareBucketItem(BaseModel):
    name: str
    value: float | int


class CompareTrendItem(BaseModel):
    date: str
    value: int


class CompareOverview(BaseModel):
    sample_size: int = 0
    salary_avg: float = 0
    salary_median: float = 0
    salary_p25: float = 0
    salary_p75: float = 0
    high_salary_ratio: float = 0
    job_count_30d: int = 0


class CompareSideResult(BaseModel):
    id: int
    name: str
    overview: CompareOverview
    salary_distribution: List[CompareBucketItem] = []
    trend: List[CompareTrendItem] = []
    education_distribution: List[CompareBucketItem] = []
    experience_distribution: List[CompareBucketItem] = []
    top_skills: List[CompareBucketItem] = []


class CompareSummary(BaseModel):
    winner_dimension: Optional[str] = None
    salary_gap: float = 0
    sample_gap: int = 0
    insight: str = ""


class CompareAnalysisResponse(BaseModel):
    dimension: str
    left: CompareSideResult
    right: CompareSideResult
    summary: CompareSummary
