"""Compatibility task generation for the legacy admin filter screen.

Process control belongs exclusively to ``CrawlerControlService`` and the
cross-machine crawler agent.  This module only translates the old filter UI
into deterministic task drafts handled by the shared task repository.
"""

import hashlib
from typing import Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit

from sqlalchemy import select

from common.databases.PostgresManager import db_manager
from common.databases.models.boss_spider_filter import BossSpiderFilter
from jobCollection.jobCollection.boss.tasks import (
    BOSS_ORIGIN,
    BOSS_TASK_SPIDER,
    CITY_INDUSTRY_TASK_PRIORITY,
    SqlAlchemyTaskRepository,
    TaskDraft,
)
from jobCollection.jobCollection.boss.urls import canonicalize_boss_task_url
from core.logger import sys_logger as logger


class CrawlerService:
    """Legacy filter adapter; intentionally has no process-control methods."""

    @staticmethod
    def build_filter_task_draft(
        filters: Iterable[object], additional_params: Optional[str] = None
    ) -> TaskDraft:
        query_items = []
        for item in filters:
            key = str(getattr(item, "filter_name", "") or "").strip()
            value = str(getattr(item, "filter_value", "") or "").strip()
            if key and value:
                query_items.append((key, value))
        if additional_params:
            query_items.extend(parse_qsl(additional_params.lstrip("?&"), keep_blank_values=False))
        if not query_items:
            raise ValueError("at least one valid BOSS filter is required")

        raw_url = f"{BOSS_ORIGIN}/web/geek/jobs?{urlencode(query_items)}"
        url = canonicalize_boss_task_url(raw_url)
        url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
        query = dict(parse_qsl(urlsplit(url).query))
        return TaskDraft(
            task_type="city_industry",
            source_key=f"manual:{url_hash}",
            url=url,
            url_hash=url_hash,
            priority=CITY_INDUSTRY_TASK_PRIORITY,
            spider_name=BOSS_TASK_SPIDER,
            spider_args={"task_type": "city_industry", "task_url": url},
            city_code=query.get("city"),
            industry_code=query.get("industry"),
        )

    @staticmethod
    async def generate_tasks_from_filters(
        filter_ids: Optional[list] = None,
        additional_params: Optional[str] = None,
    ) -> int:
        async with db_manager.async_session() as session:
            statement = select(BossSpiderFilter).where(BossSpiderFilter.is_active == 1)
            if filter_ids:
                statement = statement.where(
                    BossSpiderFilter.id.in_([int(item) for item in filter_ids])
                )
            filters = list((await session.execute(statement)).scalars().all())
            try:
                draft = CrawlerService.build_filter_task_draft(
                    filters, additional_params
                )
            except ValueError:
                logger.warning("No valid params found to generate task")
                return 0
            created = await SqlAlchemyTaskRepository(session).upsert_task_drafts([draft])
            await session.commit()
            return created
