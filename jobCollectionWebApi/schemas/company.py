from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from .base import TimestampSchema

class CompanyBase(BaseModel):
    name: str
    industry: Optional[str] = None
    scale: Optional[str] = None
    stage: Optional[str] = None
    location: Optional[str] = None
    logo: Optional[str] = None
    website: Optional[str] = None
    description: Optional[str] = None
    introduction: Optional[str] = None

class CompanyCreate(CompanyBase):
    pass

class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    industry: Optional[str] = None
    scale: Optional[str] = None
    stage: Optional[str] = None
    location: Optional[str] = None
    logo: Optional[str] = None
    website: Optional[str] = None
    description: Optional[str] = None
    introduction: Optional[str] = None

class CompanyInDB(CompanyBase, TimestampSchema):
    id: int

    class Config:
        from_attributes = True

class CompanyWithJobs(CompanyInDB):
    jobs: List["JobInDB"] = []

class CompanySimple(BaseModel):
    id: int
    name: str
    industry: Optional[str] = None
    scale: Optional[str] = None
    stage: Optional[str] = None
    location: Optional[str] = None
    logo: Optional[str] = None
    description: Optional[str] = None
    
    class Config:
        from_attributes = True

class CompanyList(BaseModel):
    items: List[CompanySimple]
    total: int
    page: int
    size: int
    pages: int
