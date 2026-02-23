from pydantic import BaseModel, Field, EmailStr, field_validator, model_validator
from typing import Optional, List
from datetime import date, datetime
from .base import TimestampSchema
from pydantic import field_serializer
from common.utils.masking import mask_email, mask_phone, mask_name, mask_wechat

# --- Education ---
class EducationBase(BaseModel):
    school: str
    major: Optional[str] = None
    degree: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    description: Optional[str] = None
    
    @model_validator(mode='after')
    def check_dates(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError('结束时间不能早于开始时间')
        return self

class EducationCreate(EducationBase):
    pass

class EducationUpdate(EducationBase):
    school: Optional[str] = None

class EducationInDB(EducationBase, TimestampSchema):
    id: int
    resume_id: int
    class Config:
        from_attributes = True

# --- Work ---
class WorkExperienceBase(BaseModel):
    company: str
    position: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    department: Optional[str] = None
    content: Optional[str] = None
    achievement: Optional[str] = None

    @model_validator(mode='after')
    def check_dates(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError('结束时间不能早于开始时间')
        return self

class WorkExperienceCreate(WorkExperienceBase):
    pass

class WorkExperienceInDB(WorkExperienceBase, TimestampSchema):
    id: int
    resume_id: int
    class Config:
        from_attributes = True

# --- Project ---
class ProjectExperienceBase(BaseModel):
    name: str
    role: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    description: Optional[str] = None

    @model_validator(mode='after')
    def check_dates(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError('结束时间不能早于开始时间')
        return self
    performance: Optional[str] = None

class ProjectExperienceCreate(ProjectExperienceBase):
    pass

class ProjectExperienceInDB(ProjectExperienceBase, TimestampSchema):
    id: int
    resume_id: int
    class Config:
        from_attributes = True

# --- Resume ---
class ResumeBase(BaseModel):
    name: str
    gender: Optional[str] = None
    age: Optional[int] = None
    avatar: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    wechat: Optional[str] = None
    
    desired_position: Optional[str] = None
    desired_salary: Optional[str] = None
    desired_city: Optional[str] = None
    current_status: Optional[str] = None
    
    summary: Optional[str] = None
    attachment_url: Optional[str] = None

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        import re
        if v and not re.match(r'^1[3-9]\d{9}$', v):
            raise ValueError('请输入有效的手机号码')
        return v
    
    @field_validator('gender')
    @classmethod
    def validate_gender(cls, v):
        if v and v not in ["男", "女"]:
            raise ValueError('性别必须是 男 或 女')
        return v

    @field_validator('age')
    @classmethod
    def validate_age(cls, v):
        if v and (v < 16 or v > 100):
            raise ValueError('年龄必须在 16-100 岁之间')
        return v

class ResumeCreate(ResumeBase):
    # Support creating with nested data
    educations: List[EducationCreate] = []
    work_experiences: List[WorkExperienceCreate] = []
    projects: List[ProjectExperienceCreate] = []

class ResumeUpdate(BaseModel):
    name: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[int] = None
    avatar: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    wechat: Optional[str] = None
    
    desired_position: Optional[str] = None
    desired_salary: Optional[str] = None
    desired_city: Optional[str] = None
    current_status: Optional[str] = None
    summary: Optional[str] = None
    attachment_url: Optional[str] = None

class ResumeDetail(ResumeBase, TimestampSchema):
    id: int
    user_id: int
    
    educations: List[EducationInDB] = []
    work_experiences: List[WorkExperienceInDB] = []
    projects: List[ProjectExperienceInDB] = []
    
    
    class Config:
        from_attributes = True

    @field_serializer('email')
    def serialize_email(self, email: Optional[str], _info):
        return mask_email(email)

    @field_serializer('phone')
    def serialize_phone(self, phone: Optional[str], _info):
        return mask_phone(phone)
        
    @field_serializer('name')
    def serialize_name(self, name: str, _info):
        return mask_name(name)
        
    @field_serializer('wechat')
    def serialize_wechat(self, wechat: Optional[str], _info):
        return mask_wechat(wechat)
