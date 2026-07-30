from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import Field

from .common import DataStatus, V2Model


class MarketDashboardQuery(V2Model):
    range: str = "12m"
    city: Optional[str] = None
    industry: Optional[str] = None
    education: Optional[str] = None
    experience: Optional[str] = None


class FilterOption(V2Model):
    label: str
    value: Union[str, int]


class MarketFilters(V2Model):
    ranges: List[FilterOption] = Field(default_factory=list)
    cities: List[FilterOption] = Field(default_factory=list)
    industries: List[FilterOption] = Field(default_factory=list)
    educations: List[FilterOption] = Field(default_factory=list)
    experiences: List[FilterOption] = Field(default_factory=list)


class KpiItem(V2Model):
    label: str
    value: Optional[Union[str, int, float]] = None
    note: str = ""
    delta: Optional[str] = None
    icon: str = ""
    tone: str = "blue"


class DistributionItem(V2Model):
    label: str
    value: float
    featured: bool = False


class NamedValue(V2Model):
    name: str
    value: float


class TrendSeries(V2Model):
    name: str
    values: List[float] = Field(default_factory=list)
    color: Optional[str] = None


class TrendData(V2Model):
    years: List[str] = Field(default_factory=list)
    series: List[TrendSeries] = Field(default_factory=list)


class TalentStructure(V2Model):
    education: List[DistributionItem] = Field(default_factory=list)
    experience: List[DistributionItem] = Field(default_factory=list)


class SalarySummary(V2Model):
    median: Optional[float] = None
    p75: Optional[float] = None


class MarketDashboardResponse(V2Model):
    updated_at: str
    data_status: DataStatus
    filters: MarketFilters
    hero_signals: List[dict] = Field(default_factory=list)
    kpis: List[KpiItem] = Field(default_factory=list)
    trend: TrendData = Field(default_factory=TrendData)
    city_salaries: List[NamedValue] = Field(default_factory=list)
    skills: List[NamedValue] = Field(default_factory=list)
    salary_distribution: List[DistributionItem] = Field(default_factory=list)
    salary_summary: SalarySummary = Field(default_factory=SalarySummary)
    talent_structure: TalentStructure = Field(default_factory=TalentStructure)
    city_matrix: List[dict] = Field(default_factory=list)
    signals: List[dict] = Field(default_factory=list)
    rankings: List[dict] = Field(default_factory=list)


class MarketQuestionRequest(V2Model):
    question: str = Field(min_length=1, max_length=20000)
    context: Dict[str, Any] = Field(default_factory=dict)


class MarketHistoryMessage(V2Model):
    id: str
    conversation_id: str
    role: str
    message_type: str
    content: str
    created_at: Optional[datetime] = None


class MarketHistoryItem(V2Model):
    conversation_id: str
    title: str
    latest_run_id: Optional[str] = None
    latest_run_status: Optional[str] = None
    messages: List[MarketHistoryMessage] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MarketHistoryResponse(V2Model):
    items: List[MarketHistoryItem] = Field(default_factory=list)
    total: int = 0
