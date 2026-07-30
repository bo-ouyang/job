from datetime import date, datetime
from typing import Any, List, Literal, Optional

from pydantic import BeforeValidator, EmailStr, Field, field_validator
from typing_extensions import Annotated

from .common import V2Model


SnowflakeId = Annotated[str, BeforeValidator(lambda value: str(value))]
ProfileSource = Literal["manual", "resume", "system", "import"]
ConfirmationStatus = Literal["pending", "confirmed", "rejected", "conflict"]


class ProfileCourseInput(V2Model):
    name: str = Field(min_length=1, max_length=200)
    category: Optional[str] = Field(default=None, max_length=100)
    level: Optional[str] = Field(default=None, max_length=30)
    is_core: bool = False
    source: ProfileSource = "manual"
    source_reference: Optional[str] = Field(default=None, max_length=500)
    confirmation_status: ConfirmationStatus = "confirmed"
    evidence: Optional[Any] = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("course name cannot be empty")
        return value


class ProfileCourseResponse(ProfileCourseInput):
    id: SnowflakeId
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProfileSkillInput(V2Model):
    name: str = Field(min_length=1, max_length=200)
    category: Optional[str] = Field(default=None, max_length=100)
    proficiency_level: Optional[int] = Field(default=None, ge=1, le=5)
    years_experience: Optional[float] = Field(default=None, ge=0, le=80)
    source: ProfileSource = "manual"
    source_reference: Optional[str] = Field(default=None, max_length=500)
    confirmation_status: ConfirmationStatus = "confirmed"
    evidence: Optional[Any] = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("skill name cannot be empty")
        return value


class ProfileSkillResponse(ProfileSkillInput):
    id: SnowflakeId
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProfileUpdate(V2Model):
    name: Optional[str] = Field(default=None, max_length=50)
    phone: Optional[str] = Field(default=None, max_length=20)
    email: Optional[str] = Field(default=None, max_length=100)
    city: Optional[str] = Field(default=None, max_length=100)
    school: Optional[str] = Field(default=None, max_length=200)
    school_level: Optional[str] = Field(default=None, max_length=50)
    education: Optional[str] = Field(default=None, max_length=50)
    major: Optional[str] = Field(default=None, max_length=200)
    graduation_year: Optional[str] = Field(default=None, max_length=20)
    gpa: Optional[str] = Field(default=None, max_length=30)
    target_cities: Optional[List[str]] = None
    target_roles: Optional[List[str]] = None
    target_industries: Optional[List[str]] = None
    expected_salary: Optional[str] = Field(default=None, max_length=100)


class ProfileResponse(V2Model):
    name: str = ""
    phone: str = ""
    email: str = ""
    city: str = ""
    school: str = ""
    school_level: str = ""
    education: str = ""
    major: str = ""
    graduation_year: str = ""
    gpa: str = ""
    target_cities: List[str] = Field(default_factory=list)
    target_roles: List[str] = Field(default_factory=list)
    target_industries: List[str] = Field(default_factory=list)
    expected_salary: str = ""
    completion: int = Field(default=0, ge=0, le=100)


class ResumeCandidateBasic(V2Model):
    name: Optional[str] = Field(default=None, max_length=50)
    gender: Optional[str] = Field(default=None, max_length=10)
    age: Optional[int] = Field(default=None, ge=16, le=100)
    phone: Optional[str] = Field(default=None, max_length=20)
    email: Optional[EmailStr] = Field(default=None, max_length=100)
    desired_position: Optional[str] = Field(default=None, max_length=100)
    summary: Optional[str] = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: Optional[str]) -> Optional[str]:
        import re

        if value and not re.fullmatch(r"1[3-9]\d{9}", value):
            raise ValueError("invalid phone number")
        return value

    @field_validator("gender")
    @classmethod
    def validate_gender(cls, value: Optional[str]) -> Optional[str]:
        if value and value not in {"男", "女"}:
            raise ValueError("invalid gender")
        return value


class ResumeEducationCandidate(V2Model):
    school: str = Field(min_length=1, max_length=100)
    major: Optional[str] = Field(default=None, max_length=100)
    degree: Optional[str] = Field(default=None, max_length=50)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    description: Optional[str] = None


class ResumeWorkCandidate(V2Model):
    company: str = Field(min_length=1, max_length=100)
    position: str = Field(min_length=1, max_length=100)
    department: Optional[str] = Field(default=None, max_length=50)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    content: Optional[str] = None
    achievement: Optional[str] = None


class ResumeCandidateApply(V2Model):
    basic: ResumeCandidateBasic = Field(default_factory=ResumeCandidateBasic)
    educations: List[ResumeEducationCandidate] = Field(default_factory=list)
    work_experiences: List[ResumeWorkCandidate] = Field(default_factory=list)
    skills: List[ProfileSkillInput] = Field(default_factory=list)
    courses: List[ProfileCourseInput] = Field(default_factory=list)
