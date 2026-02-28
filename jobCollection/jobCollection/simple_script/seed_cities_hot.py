"""
seed_cities_hot.py
从 BOSS 直聘 cityGroup API 拉取热门城市列表，写入 cities_hot 表。

用法:
    cd d:\\Code\\job
    python jobCollection/jobCollection/simple_script/seed_cities_hot.py
"""

import asyncio
import logging
import os
import sys

import httpx

# ── 路径设置 ──────────────────────────────────────────────────────────────────
current_dir = os.path.dirname(os.path.abspath(__file__))
# simple_script -> jobCollection -> jobCollection -> d:/Code/job
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
sys.path.insert(0, project_root)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

from common.databases.PostgresManager import db_manager
# 导入所有模型确保 SQLAlchemy 注册表完整
from common.databases.models import *  # noqa: F401, F403
from common.databases.models.city_hot import CityHot  # cities_hot 表
from sqlalchemy import select

CITY_GROUP_API = "https://www.zhipin.com/wapi/zpCommon/data/cityGroup.json"


async def fetch_city_group() -> dict:
    """从 BOSS 直聘 API 获取城市分组数据"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.zhipin.com/",
    }
    async with httpx.AsyncClient(headers=headers, timeout=15) as client:
        resp = await client.get(CITY_GROUP_API)
        resp.raise_for_status()
        return resp.json()


def extract_hot_cities(data: dict) -> list[dict]:
    """
    从 API 响应中提取热门城市列表。
    API 结构: zpData.cityList[].hotCityList[]
    每个城市字段: code, name, pinyin, firstChar, rank, cityType, etc.
    """
    hot_cities = []
    zp_data = data.get("zpData") or data.get("data") or data
    #city_list = zp_data.get("cityList", [])

    
        # 热门城市列表
    for city in zp_data.get("hotCityList", []):
        hot_cities.append(city)

    # 去重（按 code）
    seen = set()
    unique = []
    for c in hot_cities:
        code = c.get("code")
        if code and code not in seen:
            seen.add(code)
            unique.append(c)

    logger.info(f"共提取热门城市 {len(unique)} 个")
    return unique


async def seed_cities_hot():
    await db_manager.initialize()

    # 拉取 API 数据
    logger.info(f"请求城市数据: {CITY_GROUP_API}")
    try:
        raw = await fetch_city_group()
    except Exception as e:
        logger.error(f"请求失败: {e}")
        return
    print(raw)
    if raw.get("code") != 0:
        logger.error(f"API 返回错误: {raw}")
        return

    hot_cities = extract_hot_cities(raw)
    if not hot_cities:
        logger.error("未提取到任何热门城市，请检查 API 响应结构")
        return

    added = 0
    updated = 0

    async with (await db_manager.get_session()) as session:
        for c in hot_cities:
            code = c.get("code")
            if not code:
                continue

            # 检查是否已存在
            existing = (await session.execute(
                select(CityHot).where(CityHot.code == code)
            )).scalar_one_or_none()

            if existing:
                # 更新字段
                existing.name         = c.get("name", existing.name)
                existing.pinyin       = c.get("pinyin", existing.pinyin)
                existing.first_char   = c.get("firstChar", existing.first_char)
                existing.rank         = c.get("rank", existing.rank)
                existing.city_type    = c.get("cityType", existing.city_type)
                existing.position_type= c.get("positionType", existing.position_type)
                existing.tip          = c.get("tip", existing.tip)
                existing.mark         = c.get("mark", existing.mark)
                existing.capital      = c.get("capital", existing.capital)
                existing.color        = c.get("color", existing.color)
                existing.recruitment_type = c.get("recruitmentType", existing.recruitment_type)
                existing.city_code    = str(c.get("cityCode", existing.city_code) or "")
                existing.region_code  = c.get("regionCode", existing.region_code)
                existing.center_geo   = c.get("centerGeo", existing.center_geo)
                existing.value        = c.get("value", existing.value)
                updated += 1
            else:
                city = CityHot(
                    code           = code,
                    name           = c.get("name", ""),
                    pinyin         = c.get("pinyin"),
                    first_char     = c.get("firstChar"),
                    rank           = c.get("rank", 0),
                    city_type      = c.get("cityType"),
                    position_type  = c.get("positionType", 0),
                    level          = 1,   # 热门城市均为市级
                    tip            = c.get("tip"),
                    mark           = c.get("mark", 0),
                    capital        = c.get("capital", 0),
                    color          = c.get("color"),
                    recruitment_type = c.get("recruitmentType"),
                    city_code      = str(c.get("cityCode") or ""),
                    region_code    = c.get("regionCode"),
                    center_geo     = c.get("centerGeo"),
                    value          = c.get("value"),
                )
                session.add(city)
                added += 1

        await session.commit()

    logger.info(f"完成！新增 {added} 个，更新 {updated} 个热门城市")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(seed_cities_hot())
