from typing import List, Optional
from pydantic import BaseModel, Field

class AISearchQuery(BaseModel):
    """
    Structured JSON Schema for AI Intent Recognition
    This schema defines what the LLM should output after parsing the user's natural language query.
    """
    locations: Optional[List[str]] = Field(
        default=[],
        description="List of target cities or locations mentioned by the user. Example: ['北京', '杭州']."
    )
    keywords: Optional[List[str]] = Field(
        default=[],
        description="Broad search keywords for job titles or descriptions. Example: ['后端', '开发', '产品经理']."
    )
    skills_must_have: Optional[List[str]] = Field(
        default=[],
        description="Specific technical skills or tools the user explicitly mentions they want or have. Example: ['Python', 'Go', 'Figma']."
    )
    salary_min: Optional[int] = Field(
        default=None,
        description="The minimum acceptable monthly salary in RMB. If user says '高于两万', it's 20000."
    )
    salary_max: Optional[int] = Field(
        default=None,
        description="The maximum monthly salary in RMB. If user says '两到三万', this is 30000."
    )
    exclude_keywords: Optional[List[str]] = Field(
        default=[],
        description="Keywords the user explicitly wants to avoid. If they say '不要外包', add '外包' here."
    )
    benefits_desired: Optional[List[str]] = Field(
        default=[],
        description="Company benefits the user is looking for. Example: ['双休', '五险一金', '不加班']."
    )
    education: Optional[str] = Field(
        default=None,
        description="Required education level mentioned. Example: '本科', '大专', '硕士'."
    )
    experience: Optional[str] = Field(
        default=None,
        description="Required experience level mentioned. Example: '3-5年', '应届生', '不限', '5-10年'."
    )
    industry: Optional[str] = Field(
        default=None,
        description="Target industry mentioned by the user. Example: '互联网', '游戏', '人工智能'."
    )
