from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime


class AiTaskCreate(BaseModel):
    """创建 AI 任务时的内部参数"""
    user_id: int
    celery_task_id: str
    feature_key: str
    request_params: Optional[Dict[str, Any]] = None
    analysis_input: Optional[Dict[str, Any]] = None


class AiTaskInDB(BaseModel):
    """AI 任务详情（返回给前端）"""
    id: int
    user_id: int
    celery_task_id: str
    feature_key: str
    status: str
    request_params: Optional[Dict[str, Any]] = None
    analysis_input: Optional[Dict[str, Any]] = None
    result_data: Optional[str] = None
    error_message: Optional[str] = None
    execution_time: Optional[float] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AiTaskBrief(BaseModel):
    """AI 任务摘要（历史列表用）"""
    celery_task_id: str
    feature_key: str
    status: str
    result_data: Optional[str] = None
    analysis_input: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    execution_time: Optional[float] = None
    request_params: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class AiTaskList(BaseModel):
    """分页历史列表"""
    items: List[AiTaskBrief]
    total: int
    page: int
    size: int
