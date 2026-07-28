from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from .job_schema import JobSimple
from .company_schema import CompanySimple
from .types import SnowflakeId

class FavoriteJobCreate(BaseModel):
    job_id: int

class FavoriteJobSchema(BaseModel):
    id: SnowflakeId
    user_id: SnowflakeId
    job_id: SnowflakeId
    created_at: datetime
    # We might want to return job details
    job: Optional[JobSimple] = None
    
    class Config:
        from_attributes = True

class FollowCompanyCreate(BaseModel):
    company_id: int

class FollowCompanySchema(BaseModel):
    id: SnowflakeId
    user_id: SnowflakeId
    company_id: SnowflakeId
    created_at: datetime
    company: Optional[CompanySimple] = None
    
    class Config:
        from_attributes = True
