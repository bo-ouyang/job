from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


ToolSource = Literal["elasticsearch", "postgresql", "mixed", "mock", "unavailable"]


class ToolResult(BaseModel):
    ok: bool
    data: Optional[Any] = None
    sample_size: int = Field(default=0, ge=0)
    filters: Dict[str, Any] = Field(default_factory=dict)
    data_as_of: Optional[datetime] = None
    source: ToolSource = "unavailable"
    warnings: List[str] = Field(default_factory=list)
    error_code: Optional[str] = None

    @classmethod
    def success(
        cls,
        *,
        data: Any,
        sample_size: int,
        filters: Dict[str, Any],
        source: ToolSource,
        data_as_of: Optional[datetime] = None,
        warnings: Optional[List[str]] = None,
    ) -> "ToolResult":
        return cls(
            ok=True,
            data=data,
            sample_size=sample_size,
            filters=filters,
            data_as_of=data_as_of,
            source=source,
            warnings=warnings or [],
        )

    @classmethod
    def failure(
        cls,
        *,
        error_code: str,
        warning: str,
        filters: Optional[Dict[str, Any]] = None,
    ) -> "ToolResult":
        return cls(
            ok=False,
            data=None,
            source="unavailable",
            warnings=[warning],
            error_code=error_code,
            filters=filters or {},
        )


class SearchJobsInput(BaseModel):
    keyword: Optional[str] = Field(default=None, max_length=100)
    cities: List[str] = Field(default_factory=list, max_length=3)
    industries: List[str] = Field(default_factory=list, max_length=3)
    skills: List[str] = Field(default_factory=list, max_length=10)
    experience: Optional[str] = Field(default=None, max_length=50)
    education: Optional[str] = Field(default=None, max_length=50)
    salary_min_yuan: Optional[int] = Field(default=None, ge=0, le=1000000)
    salary_max_yuan: Optional[int] = Field(default=None, ge=0, le=1000000)
    limit: int = Field(default=20, ge=1, le=50)

    @model_validator(mode="after")
    def validate_salary_range(self):
        if (
            self.salary_min_yuan is not None
            and self.salary_max_yuan is not None
            and self.salary_min_yuan > self.salary_max_yuan
        ):
            raise ValueError("salary_min_yuan cannot exceed salary_max_yuan")
        return self


class MarketOverviewInput(BaseModel):
    keyword: Optional[str] = Field(default=None, max_length=100)
    cities: List[str] = Field(default_factory=list, max_length=3)
    industries: List[str] = Field(default_factory=list, max_length=3)
    experience: Optional[str] = Field(default=None, max_length=50)
    education: Optional[str] = Field(default=None, max_length=50)
    salary_min_yuan: Optional[int] = Field(default=None, ge=0, le=1000000)
    salary_max_yuan: Optional[int] = Field(default=None, ge=0, le=1000000)


class SkillDemandInput(BaseModel):
    keyword: str = Field(min_length=1, max_length=100)
    cities: List[str] = Field(default_factory=list, max_length=3)
    industries: List[str] = Field(default_factory=list, max_length=3)
    limit: int = Field(default=20, ge=1, le=50)


class MajorDirectionsInput(BaseModel):
    major_name: str = Field(min_length=1, max_length=100)
    cities: List[str] = Field(default_factory=list, max_length=3)
    limit: int = Field(default=10, ge=1, le=20)


class CompareCitiesInput(BaseModel):
    cities: List[str] = Field(min_length=2, max_length=2)
    keyword: Optional[str] = Field(default=None, max_length=100)
    industry: Optional[str] = Field(default=None, max_length=100)
    experience: Optional[str] = Field(default=None, max_length=50)
    education: Optional[str] = Field(default=None, max_length=50)
    days: int = Field(default=30, ge=1, le=365)

    @model_validator(mode="after")
    def cities_must_be_distinct(self):
        if len({item.strip().lower() for item in self.cities}) != 2:
            raise ValueError("cities must contain two distinct values")
        return self


class CompareIndustriesInput(BaseModel):
    industries: List[str] = Field(min_length=2, max_length=2)
    keyword: Optional[str] = Field(default=None, max_length=100)
    city: Optional[str] = Field(default=None, max_length=100)
    experience: Optional[str] = Field(default=None, max_length=50)
    education: Optional[str] = Field(default=None, max_length=50)
    days: int = Field(default=30, ge=1, le=365)

    @model_validator(mode="after")
    def industries_must_be_distinct(self):
        if len({item.strip().lower() for item in self.industries}) != 2:
            raise ValueError("industries must contain two distinct values")
        return self
