"""
generate_boss_stu_urls.py
读取 cities_hot 和 major_industry_relations 表，
组合生成类似如下格式的 BOSS 直聘岗位搜索 URL：

  https://www.zhipin.com/web/geek/jobs?city=101030100
    &position=220204,220103,...
    &ka=major_filter_土木工程_click

生成的 URL 写入 spider_boss_crawl_url 表（去重，status=pending）。

用法:
    cd d:\\Code\\job
    python jobCollection/jobCollection/simple_script/generate_boss_stu_urls.py

可选参数（命令行）:
    --dry-run   仅打印生成的 URL，不写入数据库
    --limit N   只处理前 N 个专业（调试用）
"""

import asyncio
import logging
import os
import sys
import argparse
from urllib.parse import urlencode, quote

# ── 路径设置 ──────────────────────────────────────────────────────────────────
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
sys.path.insert(0, project_root)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

from sqlalchemy import select, text
from common.databases.PostgresManager import db_manager
from common.databases.models import *  # noqa: F401, F403
from common.databases.models.city_hot import CityHot          # cities_hot 表
from common.databases.models.major import MajorIndustryRelation
from common.databases.models.boss_stu_crawl_url import BossStuCrawlUrl

BASE_URL = "https://www.zhipin.com/web/geek/jobs"


def build_url(city_code: int, position_codes: list[str | int], major_name: str) -> tuple[str, str]:
    """
    构建岗位搜索 URL 和埋点 KA 字符串。

    示例:
      city_code=101030100, position_codes=[220204,220103], major_name="土木工程"
      →
      url: https://www.zhipin.com/web/geek/jobs?city=101030100&position=220204,220103&ka=major_filter_土木工程_click
      ka : major_filter_土木工程_click
    """
    position_str = ",".join(str(c) for c in position_codes)
    ka = f"major_filter_{major_name}_click"

    params = {
        "city": city_code,
        "position": position_str,
        "ka": ka,
    }
    # 保留中文不编码（与 BOSS 直聘实际 URL 格式一致）
    query = "&".join(
        f"{k}={quote(str(v), safe=',')}" for k, v in params.items()
    )
    url = f"{BASE_URL}?{query}"
    return url, ka


async def generate_urls(dry_run: bool = False, limit: int = 0):
    await db_manager.initialize()

    async with (await db_manager.get_session()) as session:
        # 1. 获取所有热门城市
        cities = (await session.execute(select(CityHot))).scalars().all()
        if not cities:
            logger.error("cities_hot 表为空，请先运行 seed_cities_hot.py")
            return
        logger.info(f"读取热门城市 {len(cities)} 个")

        # 2. 获取专业-行业关联
        stmt = select(MajorIndustryRelation).where(
            MajorIndustryRelation.industry_codes.isnot(None)
        )
        relations = (await session.execute(stmt)).scalars().all()
        if not relations:
            logger.error("major_industry_relations 表为空，请先录入专业行业数据")
            return
        logger.info(f"读取专业-行业关联 {len(relations)} 条")

        if limit:
            relations = relations[:limit]
            logger.info(f"调试模式：仅处理前 {limit} 条专业")

        added = 0
        skipped = 0
        total = len(cities) * len(relations)
        logger.info(f"预计生成 URL 数量：{total}（城市 {len(cities)} × 专业 {len(relations)}）")

        for rel in relations:
            major_name = rel.major_name or "未知专业"
            codes = rel.industry_codes  # JSONB, list[int|str]
            if not codes:
                logger.warning(f"专业 [{major_name}] 无行业编码，跳过")
                continue

            for city in cities:
                url, ka = build_url(city.code, codes, major_name)

                if dry_run:
                    logger.info(f"[DRY-RUN] {url}")
                    continue

                # 去重检查
                exists = (await session.execute(
                    select(BossStuCrawlUrl).where(BossStuCrawlUrl.url == url)
                )).scalar_one_or_none()

                if exists:
                    skipped += 1
                    continue

                session.add(BossStuCrawlUrl(
                    url=url,
                    ka=ka,
                    major_name=major_name,
                    status="pending",
                ))
                added += 1

            # 每个专业批量提交一次，减少内存压力
            if not dry_run:
                await session.commit()
                logger.info(
                    f"专业 [{major_name}] 完成：新增 {added} 条（累计），已跳过 {skipped} 条"
                )

    if dry_run:
        logger.info("DRY-RUN 完成，未写入数据库")
    else:
        logger.info(f"全部完成！共新增 {added} 条，跳过重复 {skipped} 条")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成 BOSS 直聘专业岗位爬取 URL")
    parser.add_argument("--dry-run", action="store_true", help="仅打印 URL，不写入数据库")
    parser.add_argument("--limit", type=int, default=0, help="限制处理的专业数量（0=不限）")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(generate_urls(dry_run=args.dry_run, limit=args.limit))
