"""Agent 工具的输入参数和统一结果协议。"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


# 数据来源会进入证据、日志和指标，用来明确 ES 降级或测试数据状态。
ToolSource = Literal["elasticsearch", "postgresql", "mixed", "mock", "unavailable"]


class ToolResult(BaseModel):
    """所有工具向运行时返回的统一结果。

    ``sample_size`` 是证据可用性的核心判断，``filters`` 记录实际查询口径，``source``
    和 ``warnings`` 则让回答模型能够如实披露降级与统计限制。
    """

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
        """构造成功结果，并统一处理可选 warning 列表。"""

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
        """构造不携带业务数据的标准失败结果。"""

        return cls(
            ok=False,
            data=None,
            source="unavailable",
            warnings=[warning],
            error_code=error_code,
            filters=filters or {},
        )


class SearchJobsInput(BaseModel):
    """岗位样本搜索参数；数量和文本长度均受限，防止模型发起宽泛查询。"""

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
        """保证最低薪资不高于最高薪资。"""

        if (
            self.salary_min_yuan is not None
            and self.salary_max_yuan is not None
            and self.salary_min_yuan > self.salary_max_yuan
        ):
            raise ValueError("salary_min_yuan cannot exceed salary_max_yuan")
        return self


class MarketOverviewInput(BaseModel):
    """岗位量、薪资、技能和行业聚合统计的过滤参数。"""

    keyword: Optional[str] = Field(default=None, max_length=100)
    cities: List[str] = Field(default_factory=list, max_length=3)
    industries: List[str] = Field(default_factory=list, max_length=3)
    experience: Optional[str] = Field(default=None, max_length=50)
    education: Optional[str] = Field(default=None, max_length=50)
    salary_min_yuan: Optional[int] = Field(default=None, ge=0, le=1000000)
    salary_max_yuan: Optional[int] = Field(default=None, ge=0, le=1000000)


class SkillDemandInput(BaseModel):
    """高频技能统计参数；keyword 必填以限定岗位范围。"""

    keyword: str = Field(min_length=1, max_length=100)
    cities: List[str] = Field(default_factory=list, max_length=3)
    industries: List[str] = Field(default_factory=list, max_length=3)
    limit: int = Field(default=20, ge=1, le=50)


class MajorDirectionsInput(BaseModel):
    """专业到行业方向映射的查询参数。"""

    major_name: str = Field(min_length=1, max_length=100)
    cities: List[str] = Field(default_factory=list, max_length=3)
    limit: int = Field(default=10, ge=1, le=20)


class CompareCitiesInput(BaseModel):
    """两个城市在相同查询口径下的对比参数。"""

    cities: List[str] = Field(min_length=2, max_length=2)
    keyword: Optional[str] = Field(default=None, max_length=100)
    industry: Optional[str] = Field(default=None, max_length=100)
    experience: Optional[str] = Field(default=None, max_length=50)
    education: Optional[str] = Field(default=None, max_length=50)
    days: int = Field(default=30, ge=1, le=365)

    @model_validator(mode="after")
    def cities_must_be_distinct(self):
        """要求恰好比较两个不同城市，避免无意义的自比较。"""

        if len({item.strip().lower() for item in self.cities}) != 2:
            raise ValueError("cities must contain two distinct values")
        return self


class CompareIndustriesInput(BaseModel):
    """两个行业在相同查询口径下的对比参数。"""

    industries: List[str] = Field(min_length=2, max_length=2)
    keyword: Optional[str] = Field(default=None, max_length=100)
    city: Optional[str] = Field(default=None, max_length=100)
    experience: Optional[str] = Field(default=None, max_length=50)
    education: Optional[str] = Field(default=None, max_length=50)
    days: int = Field(default=30, ge=1, le=365)

    @model_validator(mode="after")
    def industries_must_be_distinct(self):
        """要求恰好比较两个不同行业。"""

        if len({item.strip().lower() for item in self.industries}) != 2:
            raise ValueError("industries must contain two distinct values")
        return self
