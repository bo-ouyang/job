"""把模型给出的城市/行业名称解析为数据库中的规范维度编码。"""

from dataclasses import dataclass
from typing import List

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.databases.models.city import City
from common.databases.models.industry import Industry


class ToolResolutionError(ValueError):
    """维度为空、未知或存在歧义时抛出的可预期错误。"""


@dataclass(frozen=True)
class ResolvedDimension:
    """解析后的维度标识；code 用于查询，name/level 用于记录查询口径。"""

    code: int
    name: str
    level: int


async def resolve_city(db: AsyncSession, value: str) -> ResolvedDimension:
    """按编码、中文名或拼音解析唯一城市。

    直辖市可能同时存在省级和市级同名记录，岗位表使用 level=1 的城市编码，因此
    这种情况下优先返回唯一的市级记录；其余多结果仍视为歧义。
    """

    normalized = str(value or "").strip()
    if not normalized:
        raise ToolResolutionError("city is required")
    if normalized.isdigit():
        condition = City.code == int(normalized)
    else:
        condition = or_(
            func.lower(City.name) == normalized.lower(),
            func.lower(City.pinyin) == normalized.lower(),
        )
    result = await db.execute(select(City).where(condition).limit(2))
    matches = list(result.scalars().all())
    if not matches:
        raise ToolResolutionError(f"unknown or ambiguous city: {normalized}")

    if len(matches) == 1:
        city = matches[0]
    else:
        # Municipalities such as 上海/北京 legitimately have both a
        # province-level row and a city-level row with the same name. Jobs
        # use the level-1 city code, so prefer that unique record.
        city_level_matches = [item for item in matches if int(item.level or 0) == 1]
        if len(city_level_matches) != 1:
            raise ToolResolutionError(f"unknown or ambiguous city: {normalized}")
        city = city_level_matches[0]
    return ResolvedDimension(code=int(city.code), name=city.name, level=int(city.level or 0))


async def resolve_industry(db: AsyncSession, value: str) -> ResolvedDimension:
    """按编码、中文名或拼音解析唯一行业，歧义时拒绝猜测。"""

    normalized = str(value or "").strip()
    if not normalized:
        raise ToolResolutionError("industry is required")
    if normalized.isdigit():
        condition = Industry.code == int(normalized)
    else:
        condition = or_(
            func.lower(Industry.name) == normalized.lower(),
            func.lower(Industry.pinyin) == normalized.lower(),
        )
    result = await db.execute(select(Industry).where(condition).limit(2))
    matches = list(result.scalars().all())
    if len(matches) != 1:
        raise ToolResolutionError(f"unknown or ambiguous industry: {normalized}")
    industry = matches[0]
    return ResolvedDimension(
        code=int(industry.code),
        name=industry.name,
        level=int(industry.level or 0),
    )


async def resolve_industry_codes(db: AsyncSession, industry_code: int) -> List[int]:
    """展开一个行业及其所有直接或路径后代编码，用于覆盖完整行业树。"""

    path_fragment = f"%/{int(industry_code)}/%"
    result = await db.execute(
        select(Industry.code).where(
            or_(
                Industry.code == int(industry_code),
                Industry.parent_id == int(industry_code),
                Industry.path.like(path_fragment),
            )
        )
    )
    return sorted({int(code) for code in result.scalars().all()})
