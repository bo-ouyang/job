from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from .job_schema import JobSimple

class FavoriteJobCreate(BaseModel):
    job_id: int

class FavoriteJobSchema(BaseModel):
    id: int
    user_id: int
    job_id: int
    created_at: datetime
    # We might want to return job details
    job: Optional[JobSimple] = None
    
    class Config:
        from_attributes = True

class FollowCompanyCreate(BaseModel):
    company_id: int

class FollowCompanySchema(BaseModel):
    id: int
    user_id: int
    company_id: int
    created_at: datetime
    
    class Config:
        from_attributes = True
