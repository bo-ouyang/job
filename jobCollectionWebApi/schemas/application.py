from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from common.databases.models.application import ApplicationStatus
from schemas.job import JobSimple as Job

class ApplicationBase(BaseModel):
    job_id: int
    resume_id: Optional[int] = None
    note: Optional[str] = None

class ApplicationCreate(ApplicationBase):
    pass

class ApplicationUpdate(BaseModel):
    status: Optional[ApplicationStatus] = None
    note: Optional[str] = None

class ApplicationInDBBase(ApplicationBase):
    id: int
    user_id: int
    status: ApplicationStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class Application(ApplicationInDBBase):
    # Expanded return model
    job: Optional[dict] = None # Using dict to avoid circular imports or complex nesting for now? 
    # Actually we can use Job schemas if imports allow. 
    # Let's import Job simple schemas.
    pass

class ApplicationWithJob(ApplicationInDBBase):
    job: Job
    
    class Config:
        from_attributes = True
