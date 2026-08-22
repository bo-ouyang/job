"""Runtime-configured Market skill noise policy."""

from __future__ import annotations

import json
import re
from typing import Any, List, Tuple

from sqlalchemy import select

from common.databases.PostgresManager import db_manager
from common.databases.RedisManager import redis_manager
from common.databases.models.system_config import SystemConfig
from core.logger import sys_logger as logger
from services.market.skill_buckets import normalize_skill_tag


CONFIG_KEY_SKILL_NOISE_EXACT = "analysis_skill_noise_exact"
CONFIG_KEY_SKILL_NOISE_CONTAINS = "analysis_skill_noise_contains"
SKILL_NOISE_CACHE_KEY = "analysis:config:skill_noise:v1"
SKILL_NOISE_CACHE_EXPIRE_SECONDS = 300
DEFAULT_SKILL_NOISE_EXACT = {
    "其他", "其它", "不限", "无", "暂无", "n/a", "na", "none", "null", "unknown", "others", "other",
}
DEFAULT_SKILL_NOISE_CONTAINS = (
    "不接受居家办公", "居家办公", "远程办公", "双休", "五险", "社保", "公积金", "包吃", "包住", "年终奖", "经验不限", "学历不限", "接受小白",
)


def _parse_noise_tokens(raw_value: Any) -> List[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, list):
        return [normalize_skill_tag(item) for item in raw_value if normalize_skill_tag(item)]

    raw_text = str(raw_value).strip()
    if not raw_text:
        return []
    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, list):
            return [normalize_skill_tag(item) for item in parsed if normalize_skill_tag(item)]
    except json.JSONDecodeError:
        pass

    parts = re.split(r"[\r\n,;，；]+", raw_text)
    return [normalize_skill_tag(item) for item in parts if normalize_skill_tag(item)]


async def get_skill_noise_rules() -> Tuple[set[str], Tuple[str, ...]]:
    """Return cached Market noise rules, enriching defaults from SystemConfig."""
    default_exact = {token.lower() for token in DEFAULT_SKILL_NOISE_EXACT}
    default_contains = tuple(DEFAULT_SKILL_NOISE_CONTAINS)

    cached_rules = await redis_manager.get_cache(SKILL_NOISE_CACHE_KEY)
    if isinstance(cached_rules, dict):
        exact_values = cached_rules.get("exact", [])
        contains_values = cached_rules.get("contains", [])
        exact_set = {normalize_skill_tag(value).lower() for value in exact_values if normalize_skill_tag(value)}
        contains_tuple = tuple(normalize_skill_tag(value) for value in contains_values if normalize_skill_tag(value))
        if exact_set or contains_tuple:
            return exact_set or default_exact, contains_tuple or default_contains

    try:
        async with db_manager.async_session() as session:
            stmt = select(SystemConfig.key, SystemConfig.value).where(
                SystemConfig.is_active == True,
                SystemConfig.key.in_([CONFIG_KEY_SKILL_NOISE_EXACT, CONFIG_KEY_SKILL_NOISE_CONTAINS]),
            )
            rows = await session.execute(stmt)
            row_map = {row.key: row.value for row in rows}
    except Exception as exc:
        logger.warning(f"从数据库加载技能噪声配置失败: {exc}")
        return default_exact, default_contains

    exact_tokens = set(default_exact)
    exact_tokens.update(_parse_noise_tokens(row_map.get(CONFIG_KEY_SKILL_NOISE_EXACT)))
    contains_tokens = list(default_contains)
    contains_tokens.extend(_parse_noise_tokens(row_map.get(CONFIG_KEY_SKILL_NOISE_CONTAINS)))
    normalized_exact = {normalize_skill_tag(token).lower() for token in exact_tokens if normalize_skill_tag(token)}
    normalized_contains = tuple(normalize_skill_tag(token) for token in contains_tokens if normalize_skill_tag(token))

    await redis_manager.set_cache(
        SKILL_NOISE_CACHE_KEY,
        {"exact": sorted(normalized_exact), "contains": list(normalized_contains)},
        expire=SKILL_NOISE_CACHE_EXPIRE_SECONDS,
        jitter=False,
    )
    return normalized_exact or default_exact, normalized_contains or default_contains
