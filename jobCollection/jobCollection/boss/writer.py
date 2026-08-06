"""The single PostgreSQL writer for BOSS list and detail items.

The Scrapy pipeline and the browser workflow progress adapter both use this
service.  Session-level methods deliberately do not commit so callers can
atomically update their own checkpoint rows in the same transaction.
"""

import os
import re
import sys
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence

from sqlalchemy import and_, case, select, update
from sqlalchemy.dialects.postgresql import insert

from common.databases.PostgresManager import db_manager
from common.databases.models.company import Company
from common.databases.models.industry import Industry
from common.databases.models.job import Job
from jobCollection.items.boss_job_item import BossJobDetailItem


class BossJobWriter:
    """Persist BOSS items and dispatch ES synchronization after commit."""

    def __init__(self, session_provider=None) -> None:
        self._session_provider = session_provider or db_manager.get_session

    async def write_batch(
        self,
        batch: Sequence[Any],
        *,
        detail_writer=None,
        jobs_writer=None,
        dispatch: Optional[Callable[[int], None]] = None,
    ) -> list[int]:
        items = [item for item in batch if item is not None]
        if not items:
            return []

        detail_items = [
            item for item in items if isinstance(item, BossJobDetailItem)
        ]
        list_items = [
            item for item in items if not isinstance(item, BossJobDetailItem)
        ]
        detail_writer = detail_writer or self.write_detail_updates
        jobs_writer = jobs_writer or self.write_jobs
        synced_ids: list[int] = []
        session = await self._session_provider()
        async with session:
            async with session.begin():
                if detail_items:
                    synced_ids.extend(await detail_writer(session, detail_items))
                if list_items:
                    synced_ids.extend(await jobs_writer(session, list_items))

        dispatcher = dispatch or self.dispatch_es_sync
        for job_id in dict.fromkeys(synced_ids):
            dispatcher(job_id)
        return synced_ids

    async def write_jobs(self, session, items: Sequence[Any]) -> list[int]:
        mapping = await self.upsert_jobs(session, items)
        return list(mapping.values())

    async def upsert_jobs(
        self, session, items: Sequence[Any]
    ) -> Dict[str, int]:
        items = [item for item in items if item is not None]
        if not items:
            return {}

        industry_codes = {
            item.get("industry_code")
            for item in items
            if item.get("industry_code") is not None
        }
        industry_map: Dict[Any, int] = {}
        if industry_codes:
            result = await session.execute(
                select(Industry).where(Industry.code.in_(industry_codes))
            )
            industry_map = {
                industry.code: industry.id for industry in result.scalars()
            }

        brand_ids = {
            item.get("encrypt_brand_id")
            for item in items
            if item.get("encrypt_brand_id")
        }
        brand_map: Dict[str, int] = {}
        if brand_ids:
            result = await session.execute(
                select(Company).where(Company.source_id.in_(brand_ids))
            )
            brand_map = {
                company.source_id: company.id for company in result.scalars()
            }
            missing = {
                brand_id: next(
                    item
                    for item in items
                    if item.get("encrypt_brand_id") == brand_id
                )
                for brand_id in brand_ids
                if brand_id not in brand_map
            }
            if missing:
                now = datetime.now()
                rows = [
                    {
                        "source_id": brand_id,
                        "name": item.get("brand_name") or "",
                        "logo": item.get("brand_logo"),
                        "scale": item.get("brand_scale_name"),
                        "stage": item.get("brand_stage_name"),
                        "industry": item.get("brand_industry"),
                        "created_at": now,
                        "updated_at": now,
                    }
                    for brand_id, item in missing.items()
                ]
                statement = insert(Company).values(rows)
                statement = statement.on_conflict_do_update(
                    index_elements=["source_id"],
                    set_={
                        "name": statement.excluded.name,
                        "logo": statement.excluded.logo,
                        "scale": statement.excluded.scale,
                        "stage": statement.excluded.stage,
                        "industry": statement.excluded.industry,
                        "updated_at": now,
                    },
                )
                await session.execute(statement)
                result = await session.execute(
                    select(Company).where(Company.source_id.in_(missing))
                )
                brand_map.update(
                    {
                        company.source_id: company.id
                        for company in result.scalars()
                    }
                )

        now = datetime.now()
        rows = []
        for item in items:
            encrypt_job_id = str(item.get("encrypt_job_id") or "").strip()
            if not encrypt_job_id:
                continue
            salary_desc = item.get("salary_desc") or ""
            salary_min, salary_max = self._salary_range(salary_desc)
            rows.append(
                {
                    "title": item.get("job_name") or "",
                    "salary_min": salary_min,
                    "salary_max": salary_max,
                    "salary_desc": salary_desc,
                    "location": "".join(
                        str(item.get(field) or "")
                        for field in (
                            "city_name",
                            "area_district",
                            "business_district",
                        )
                    ),
                    "area_district": item.get("area_district") or "",
                    "business_district": item.get("business_district") or "",
                    "experience": item.get("job_experience") or "",
                    "education": item.get("job_degree") or "",
                    "tags": item.get("skills") or [],
                    "job_labels": item.get("job_labels") or [],
                    "welfare": item.get("welfare_list") or [],
                    "source_site": "BossZhipin",
                    "source_url": (
                        "https://www.zhipin.com/job_detail/"
                        f"{encrypt_job_id}.html"
                    ),
                    "encrypt_job_id": encrypt_job_id,
                    "company_id": brand_map.get(item.get("encrypt_brand_id")),
                    "industry_id": industry_map.get(item.get("industry_code")),
                    "industry_code": item.get("industry_code"),
                    "city_code": item.get("city_code"),
                    "major_name": item.get("major_name"),
                    "longitude": float(item.get("longitude") or 0),
                    "latitude": float(item.get("latitude") or 0),
                    "boss_name": item.get("boss_name") or "",
                    "boss_title": item.get("boss_title") or "",
                    "boss_avatar": item.get("boss_avatar") or "",
                    "publish_date": now,
                    "created_at": now,
                    "updated_at": now,
                    "is_crawl": 0,
                }
            )
        if not rows:
            return {}

        statement = insert(Job).values(rows)
        statement = statement.on_conflict_do_update(
            index_elements=["encrypt_job_id"],
            set_=self._list_conflict_updates(statement, now),
        ).returning(Job.encrypt_job_id, Job.id)
        result = await session.execute(statement)
        return {str(job_id): int(database_id) for job_id, database_id in result.all()}

    @staticmethod
    def _list_conflict_updates(statement, now) -> Dict[str, Any]:
        excluded = statement.excluded

        def non_empty(name: str):
            incoming = getattr(excluded, name)
            return case(
                (and_(incoming.is_not(None), incoming != ""), incoming),
                else_=getattr(Job, name),
            )

        def non_zero(name: str):
            incoming = getattr(excluded, name)
            return case(
                (and_(incoming.is_not(None), incoming != 0), incoming),
                else_=getattr(Job, name),
            )

        def non_empty_json(name: str):
            incoming = getattr(excluded, name)
            return case(
                (and_(incoming.is_not(None), incoming != []), incoming),
                else_=getattr(Job, name),
            )

        values = {
            name: non_empty(name)
            for name in (
                "title", "salary_desc", "location", "area_district",
                "business_district", "experience", "education", "source_site",
                "source_url", "major_name", "boss_name", "boss_title", "boss_avatar",
            )
        }
        values.update({
            name: non_zero(name)
            for name in (
                "salary_min", "salary_max", "company_id", "industry_id",
                "industry_code", "city_code", "longitude", "latitude",
            )
        })
        values.update({
            name: non_empty_json(name)
            for name in ("tags", "job_labels", "welfare")
        })
        values["updated_at"] = now
        return values

    async def write_detail_updates(
        self, session, items: Sequence[Any]
    ) -> list[int]:
        mapping = await self.update_details(session, items)
        return list(mapping.values())

    async def update_details(
        self, session, items: Sequence[Any]
    ) -> Dict[str, int]:
        updated: Dict[str, int] = {}
        for item in items:
            description = item.get("job_desc")
            encrypt_job_id = str(item.get("encrypt_job_id") or "").strip()
            if not description or not encrypt_job_id:
                continue
            now = datetime.now()
            values: Dict[str, Any] = {
                "description": description,
                "updated_at": now,
                "is_crawl": 1,
            }
            if item.get("longitude") is not None:
                values["longitude"] = float(item.get("longitude") or 0)
            if item.get("latitude") is not None:
                values["latitude"] = float(item.get("latitude") or 0)
            if item.get("skills"):
                values["tags"] = item.get("skills")

            statement = (
                update(Job)
                .where(Job.encrypt_job_id == encrypt_job_id)
                .values(**values)
                .returning(Job.id)
            )
            result = await session.execute(statement)
            database_id = result.scalar()
            if database_id is None:
                placeholder = {
                    "title": "",
                    "encrypt_job_id": encrypt_job_id,
                    "source_site": "BossZhipin",
                    "source_url": (
                        "https://www.zhipin.com/job_detail/"
                        f"{encrypt_job_id}.html"
                    ),
                    "description": description,
                    "is_crawl": 1,
                    "created_at": now,
                    "updated_at": now,
                }
                insert_statement = insert(Job).values(placeholder)
                insert_statement = insert_statement.on_conflict_do_update(
                    index_elements=["encrypt_job_id"],
                    set_={
                        "description": insert_statement.excluded.description,
                        "is_crawl": 1,
                        "updated_at": now,
                    },
                ).returning(Job.id)
                database_id = (await session.execute(insert_statement)).scalar()
            if database_id is not None:
                updated[encrypt_job_id] = int(database_id)
        return updated

    @staticmethod
    def _salary_range(value: str) -> tuple[int, int]:
        match = re.search(r"(\d+)-(\d+)K", value, re.IGNORECASE)
        if match is None:
            return 0, 0
        return int(match.group(1)) * 1000, int(match.group(2)) * 1000

    @staticmethod
    def dispatch_es_sync(job_id: int) -> None:
        try:
            webapi_dir = os.path.join(
                os.path.dirname(
                    os.path.dirname(
                        os.path.dirname(
                            os.path.dirname(os.path.abspath(__file__))
                        )
                    )
                ),
                "jobCollectionWebApi",
            )
            if webapi_dir not in sys.path:
                sys.path.append(webapi_dir)
            from tasks.es_sync import sync_job_to_es

            sync_job_to_es.delay(job_id)
        except Exception:
            # PostgreSQL is authoritative; ES delivery remains best effort.
            return
