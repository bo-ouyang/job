from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BeforeValidator, Field
from typing_extensions import Annotated

from .common import DataStatus, V2Model


SnowflakeId = Annotated[str, BeforeValidator(lambda value: str(value))]


class CareerOverviewQuery(V2Model):
    city: Optional[str] = None
    industry: Optional[str] = None
    direction: Optional[str] = None


class CareerProfileSummary(V2Model):
    name: str = ""
    completion: int = 0
    school: str = ""
    major: str = ""
    graduation: str = ""


class CareerDirection(V2Model):
    title: str
    match: Optional[float] = None
    reason: str = ""
    tags: List[str] = Field(default_factory=list)


class CareerCity(V2Model):
    city: str
    jobs: Optional[Any] = None
    salary: Optional[Any] = None
    growth: Optional[Any] = None
    competition: Optional[Any] = None


class CareerSkillGap(V2Model):
    name: str
    current: Optional[float] = None
    target: Optional[float] = None
    advice: Optional[str] = None


class CareerPlanItem(V2Model):
    period: str = ""
    title: str
    items: List[str] = Field(default_factory=list)


class CareerEvidence(V2Model):
    sample_size: Optional[Any] = None
    updated_at: Optional[str] = None


class CareerOverviewResponse(V2Model):
    profile: CareerProfileSummary
    directions: List[CareerDirection] = Field(default_factory=list)
    cities: List[CareerCity] = Field(default_factory=list)
    skills: List[CareerSkillGap] = Field(default_factory=list)
    plan: List[CareerPlanItem] = Field(default_factory=list)
    evidence: CareerEvidence = Field(default_factory=CareerEvidence)
    data_status: DataStatus


class CareerReportRequest(V2Model):
    filters: Dict[str, Any] = Field(default_factory=dict)


class CareerQuestionRequest(V2Model):
    question: str = Field(min_length=1, max_length=20000)
    filters: Dict[str, Any] = Field(default_factory=dict)


class CareerSubmissionResponse(V2Model):
    conversation_id: SnowflakeId
    run_id: SnowflakeId
    status: str
    answer: Optional[str] = None


class CareerLatestReportResponse(V2Model):
    status: str
    run_id: Optional[SnowflakeId] = None
    content: Optional[str] = None
    report: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None


class PricingItem(V2Model):
    amount: Optional[float] = None
    currency: str = "CNY"
    enabled: bool = True
    product_code: str
    description: str


class AIPricingResponse(V2Model):
    career_report: PricingItem
    career_question: PricingItem
    ai_conversation: PricingItem
    market_question: PricingItem
    resume_parse: PricingItem
