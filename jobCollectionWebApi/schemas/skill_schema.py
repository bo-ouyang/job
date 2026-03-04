from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from .base_schema import TimestampSchema

class SkillBase(BaseModel):
    name: str
    category: Optional[str] = None
    description: Optional[str] = None

class SkillCreate(SkillBase):
    pass

class SkillUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None

class SkillInDB(SkillBase, TimestampSchema):
    id: int

    class Config:
        from_attributes = True

class SkillWithJobs(SkillInDB):
    jobs: List["JobInDB"] = []

class SkillFrequency(BaseModel):
    name: str
    category: Optional[str]
    frequency: int

class SkillFrequencyList(BaseModel):
    skills: List[SkillFrequency]
    total: int

class SkillList(BaseModel):
    items: List[SkillInDB]
    total: int
    page: int
    size: int
    pages: int
