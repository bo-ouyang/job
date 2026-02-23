from pydantic import BaseModel, Field, ConfigDict,field_validator
from typing import Optional, List, Any
from datetime import datetime
from .base import TimestampSchema
from enum import Enum
import re
class WorkType(str, Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    INTERNSHIP = "internship"
    REMOTE = "remote"

class EducationLevel(str, Enum):
    HIGH_SCHOOL = "high_school"
    ASSOCIATE = "associate"
    BACHELOR = "bachelor"
    MASTER = "master"
    PHD = "phd"
# 基础模式
class JobBase(BaseModel):
    title: str
    description: Optional[str] = None
    requirements: Optional[str] = None

    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_unit: Optional[str] = "月"
    salary_desc: Optional[str] = None
    # HR info
    boss_name: Optional[str] = None
    boss_title: Optional[str] = None
    boss_avatar: Optional[str] = None
    
    experience: Optional[str] = None
    education: Optional[str] = None
    location: Optional[str] = None
    area_district: Optional[str] = None
    business_district: Optional[str] = None
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    tags: Optional[Any] = None
    welfare: Optional[Any] = None
    work_type: Optional[str] = None
    source_site: Optional[str] = None
    source_url: Optional[str] = None
    publish_date: Optional[datetime] = None
    company_id: Optional[int] = None
    industry_id: Optional[int] = None
    job_labels: Optional[List[str]] = None

# 创建模式
class JobCreate(JobBase):
    """创建职位模式"""
    
    @field_validator('source_url')
    def validate_source_url(cls, v):
        if v and not re.match(r'^https?://', v):
            raise ValueError('来源URL必须以 http:// 或 https:// 开头')
        return v
    
    @field_validator('salary_unit')
    def validate_salary_unit(cls, v):
        allowed_units = ['月', '年', '小时', '天']
        if v not in allowed_units:
            raise ValueError(f'薪资单位必须是: {", ".join(allowed_units)}')
        return v
# 更新模式
class JobUpdate(BaseModel):
    """更新职位模式"""
    model_config = ConfigDict(from_attributes=True)
    
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    requirements: Optional[str] = None
    salary_min: Optional[float] = Field(None, ge=0)
    salary_max: Optional[float] = Field(None, ge=0)
    salary_min: Optional[float] = Field(None, ge=0)
    salary_max: Optional[float] = Field(None, ge=0)
    salary_unit: Optional[str] = None
    salary_desc: Optional[str] = None
    boss_name: Optional[str] = None
    boss_title: Optional[str] = None
    boss_avatar: Optional[str] = None
    experience: Optional[str] = None
    education: Optional[EducationLevel] = None
    location: Optional[str] = None
    area_district: Optional[str] = None
    business_district: Optional[str] = None
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    tags: Optional[Any] = None
    welfare: Optional[Any] = None
    work_type: Optional[WorkType] = None
    is_active: Optional[bool] = None

# 响应模式
class JobInDB(JobBase, TimestampSchema):
    id: int
    is_active: bool = True

    class Config:
        from_attributes = True

# 包含关系的响应模式
from .industry import Industry
try:
    from .company import CompanyInDB, CompanySimple
except ImportError:
     pass

class JobWithRelations(JobInDB):
    company: Optional["CompanyInDB"] = None
    skills: List["SkillInDB"] = []
    industry: Optional[Industry] = None

# 列表项模式（精简版）
class JobSimple(BaseModel):
    id: int
    title: str
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_unit: Optional[str] = "月"
    salary_desc: Optional[str] = None
    
    # HR info
    boss_name: Optional[str] = None
    boss_title: Optional[str] = None
    boss_avatar: Optional[str] = None
    
    experience: Optional[str] = None
    education: Optional[str] = None
    location: Optional[str] = None
    area_district: Optional[str] = None
    business_district: Optional[str] = None
    
    tags: Optional[Any] = None
    welfare: Optional[Any] = None
    work_type: Optional[str] = None
    publish_date: Optional[datetime] = None
    
    description: Optional[str] = None
    requirements: Optional[str] = None

    company: Optional["CompanySimple"] = None
    industry: Optional["Industry"] = None
    
    model_config = ConfigDict(from_attributes=True)
    
    @field_validator('industry', mode='before')
    @classmethod
    def validate_industry(cls, v):
        """处理无效的行业数据 (e.g. {'id': 0, 'name': ''})"""
        if isinstance(v, dict):
            if 'code' not in v:
                return None
        return v

# 列表响应模式
class JobList(BaseModel):
    items: List[JobSimple]
    total: int
    page: int
    size: int
    pages: int
