from datetime import datetime
from typing import List

from pydantic import BaseModel, ConfigDict, Field


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class V2Model(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class DataStatus(V2Model):
    source: str
    degraded: bool = False
    updated_at: datetime
    available_dimensions: List[str] = Field(default_factory=list)
    missing_dimensions: List[str] = Field(default_factory=list)
    synthetic_dimensions: List[str] = Field(default_factory=list)
