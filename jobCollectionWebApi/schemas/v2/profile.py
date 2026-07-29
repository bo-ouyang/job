from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BeforeValidator, Field, field_validator
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
