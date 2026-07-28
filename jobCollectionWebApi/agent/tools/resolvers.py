from dataclasses import dataclass
from typing import List

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.databases.models.city import City
from common.databases.models.industry import Industry


class ToolResolutionError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedDimension:
    code: int
    name: str
    level: int


async def resolve_city(db: AsyncSession, value: str) -> ResolvedDimension:
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
    if len(matches) != 1:
        raise ToolResolutionError(f"unknown or ambiguous city: {normalized}")
    city = matches[0]
    return ResolvedDimension(code=int(city.code), name=city.name, level=int(city.level or 0))


async def resolve_industry(db: AsyncSession, value: str) -> ResolvedDimension:
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
