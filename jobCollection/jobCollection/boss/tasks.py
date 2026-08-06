"""BOSS major catalog parsing and deterministic crawl-task generation."""

import hashlib
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, Iterator, List, Optional, Protocol, Sequence, Set, Tuple
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from sqlalchemy import case, delete, exists, func, literal_column as sa_literal_column, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased

from common.databases.models.boss_crawl_task import BossCrawlTask
from common.databases.models.boss_stu_crawl_url import (
    BossStuCrawlUrl,
    BossStuUrlPosition,
)
from common.databases.models.city import City
from common.databases.models.industry import Industry
from common.databases.models.major import Major
from common.databases.models.position_type import PositionType
from common.utils.snowflake import generate_id
from .urls import canonicalize_boss_task_url


BOSS_ORIGIN = "https://www.zhipin.com"
BOSS_TASK_SPIDER = "boss_task_drission"
MAJOR_TASK_PRIORITY = 100
CITY_INDUSTRY_TASK_PRIORITY = 10
TASK_UPSERT_BATCH_SIZE = 500
LEGACY_IDENTITY_PENDING = "legacy identity pending Phase2 canonicalization"


def _batched(items: Iterable[Any], size: int) -> Iterator[List[Any]]:
    """Yield bounded lists without materializing the source iterable."""

    iterator = iter(items)
    while True:
        batch = []
        try:
            for _ in range(size):
                batch.append(next(iterator))
        except StopIteration:
            pass
        if not batch:
            return
        yield batch
        if len(batch) < size:
            return


@dataclass(frozen=True)
class MajorUrlCandidate:
    major_name: str
    major_code: Optional[str]
    raw_url: str
    canonical_url: str
    url_hash: str
    position_codes: Tuple[str, ...]
    experience_code: Optional[str]


@dataclass(frozen=True)
class TaskDraft:
    task_type: str
    source_key: str
    url: str
    url_hash: str
    priority: int
    spider_name: str
    spider_args: Dict[str, Any]
    major_url_id: Optional[int] = None
    major_id: Optional[int] = None
    city_code: Optional[str] = None
    industry_code: Optional[str] = None


@dataclass(frozen=True)
class TaskGenerationStats:
    expected: int
    created: int
    existing: int
    disabled: int


@dataclass(frozen=True)
class MajorCatalogDraft:
    candidate: MajorUrlCandidate
    major_id: Optional[int]
    position_type_ids: Tuple[int, ...]
    parse_error: Optional[str]


@dataclass(frozen=True)
class MajorCatalogStats:
    expected: int
    created: int
    existing: int
    parse_errors: int


@dataclass(frozen=True)
class LegacyReconciliationPlan:
    survivor_updates: Dict[int, Tuple[str, str]]
    duplicate_to_survivor: Dict[int, int]
    duplicate_urls: Dict[int, str]
    duplicate_hashes: Dict[int, str]


class TaskRepository(Protocol):
    async def list_major_urls(self) -> Sequence[Any]:
        ...

    async def list_city_level_codes(self) -> Sequence[str]:
        ...

    async def list_boss_industry_leaf_codes(self) -> Sequence[str]:
        ...

    async def upsert_task_drafts(self, drafts: Iterable[TaskDraft]) -> int:
        ...


class MajorCatalogRepository(Protocol):
    async def list_majors(self) -> Sequence[Any]:
        ...

    async def list_position_types(self, codes: Sequence[str]) -> Sequence[Any]:
        ...

    async def upsert_major_catalog(
        self,
        drafts: Sequence[MajorCatalogDraft],
        source_version: Optional[str],
    ) -> int:
        ...


def _clean_text(value: str) -> str:
    return " ".join((value or "").split())


def _major_name_from_ka(raw_url: str) -> str:
    values = parse_qs(urlsplit(raw_url).query).get("ka", [])
    for value in values:
        match = re.match(r"^major_filter_(.+)_click$", unquote(value))
        if match:
            return _clean_text(match.group(1))
    return ""


def parse_major_candidate(
    href: str,
    display_text: str,
    major_code: Optional[str] = None,
    base_url: str = BOSS_ORIGIN,
) -> MajorUrlCandidate:
    """Normalize one school-page anchor into a stable major URL candidate."""

    raw_url = urljoin(base_url, (href or "").strip())
    parsed = urlsplit(raw_url)
    host = (parsed.hostname or "").lower()
    if not (host == "zhipin.com" or host.endswith(".zhipin.com")) or parsed.path != "/web/geek/jobs":
        raise ValueError("major candidate must be a BOSS jobs URL")
    query = parse_qs(parsed.query)
    position_codes = tuple(
        sorted(
            {
                code.strip()
                for value in query.get("position", [])
                for code in value.split(",")
                if code.strip()
            }
        )
    )
    if not position_codes:
        raise ValueError("major URL must contain at least one position code")

    major_name = _clean_text(display_text) or _major_name_from_ka(raw_url)
    if not major_name:
        raise ValueError("major URL must have a major name")

    canonical_url = canonicalize_boss_task_url(raw_url)
    experience_values = query.get("experience", [])
    normalized_code = _clean_text(major_code or "") or None
    return MajorUrlCandidate(
        major_name=major_name,
        major_code=normalized_code,
        raw_url=raw_url,
        canonical_url=canonical_url,
        url_hash=hashlib.sha256(canonical_url.encode("utf-8")).hexdigest(),
        position_codes=position_codes,
        experience_code=experience_values[0].strip() if experience_values else None,
    )


class _MajorAnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.nodes: List[Dict[str, str]] = []
        self._anchor: Optional[Dict[str, str]] = None
        self._text: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "a":
            return
        self._anchor = {key: value or "" for key, value in attrs}
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._anchor is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._anchor is None:
            return
        node = dict(self._anchor)
        node["text"] = "".join(self._text)
        self.nodes.append(node)
        self._anchor = None
        self._text = []


def extract_major_candidates(nodes: Iterable[Dict[str, str]]) -> List[MajorUrlCandidate]:
    """Pure DOM-node adapter; invalid/non-major anchors are ignored."""

    candidates: List[MajorUrlCandidate] = []
    identities: Set[str] = set()
    for node in nodes:
        try:
            candidate = parse_major_candidate(
                node.get("href", ""),
                node.get("text", ""),
                node.get("data-major-code") or None,
            )
        except ValueError:
            continue
        if candidate.url_hash not in identities:
            identities.add(candidate.url_hash)
            candidates.append(candidate)
    return candidates


def extract_major_candidates_from_html(html: str) -> List[MajorUrlCandidate]:
    parser = _MajorAnchorParser()
    parser.feed(html)
    return extract_major_candidates(parser.nodes)


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _legacy_url_tombstone(row_id: int, raw_url: str) -> str:
    """Return a short, auditable identity that cannot collide across row IDs."""

    return f"urn:boss-major-url:superseded:{row_id}:{_url_hash(raw_url)[:16]}"


def plan_legacy_reconciliation(
    rows: Sequence[Any], candidates: Sequence[MajorUrlCandidate]
) -> LegacyReconciliationPlan:
    """Plan collision-safe reconciliation for legacy identities seen now."""

    targets = {candidate.url_hash: candidate.canonical_url for candidate in candidates}
    legacy_groups: Dict[str, List[Any]] = {}
    current_by_hash: Dict[str, List[Any]] = {}
    for row in rows:
        error = getattr(row, "parse_error", None) or ""
        if LEGACY_IDENTITY_PENDING not in error:
            if getattr(row, "url_hash", None) in targets:
                current_by_hash.setdefault(row.url_hash, []).append(row)
            continue
        try:
            canonical_url = canonicalize_boss_task_url(row.raw_url)
        except (TypeError, ValueError):
            continue
        canonical_hash = _url_hash(canonical_url)
        if canonical_hash in targets:
            legacy_groups.setdefault(canonical_hash, []).append(row)

    survivor_updates: Dict[int, Tuple[str, str]] = {}
    duplicate_to_survivor: Dict[int, int] = {}
    duplicate_urls: Dict[int, str] = {}
    duplicate_hashes: Dict[int, str] = {}
    for canonical_hash, legacy_rows in legacy_groups.items():
        current_rows = current_by_hash.get(canonical_hash, [])
        if current_rows:
            survivor_id = min(int(row.id) for row in current_rows)
            duplicates = legacy_rows
        else:
            survivor = min(legacy_rows, key=lambda row: int(row.id))
            survivor_id = int(survivor.id)
            survivor_updates[survivor_id] = (
                targets[canonical_hash],
                canonical_hash,
            )
            duplicates = [row for row in legacy_rows if int(row.id) != survivor_id]
        for duplicate in duplicates:
            duplicate_id = int(duplicate.id)
            duplicate_to_survivor[duplicate_id] = survivor_id
            duplicate_urls[duplicate_id] = _legacy_url_tombstone(
                duplicate_id, duplicate.raw_url
            )
            duplicate_hashes[duplicate_id] = _url_hash(
                f"legacy-superseded:{duplicate_id}:{duplicate.raw_url}"
            )
    return LegacyReconciliationPlan(
        survivor_updates=survivor_updates,
        duplicate_to_survivor=duplicate_to_survivor,
        duplicate_urls=duplicate_urls,
        duplicate_hashes=duplicate_hashes,
    )


def build_major_task_draft(major_url: Any) -> TaskDraft:
    url = canonicalize_boss_task_url(major_url.canonical_url)
    major_url_id = int(major_url.id)
    major_id = int(major_url.major_id) if major_url.major_id is not None else None
    return TaskDraft(
        task_type="major",
        source_key=f"major:{major_url_id}",
        url=url,
        url_hash=_url_hash(url),
        priority=MAJOR_TASK_PRIORITY,
        spider_name=BOSS_TASK_SPIDER,
        spider_args={
            "task_type": "major",
            "major_url_id": major_url_id,
            "major_id": major_id,
            "task_url": url,
        },
        major_url_id=major_url_id,
        major_id=major_id,
    )


def build_city_industry_task_draft(city_code: str, industry_code: str) -> TaskDraft:
    city = str(city_code)
    industry = str(industry_code)
    url = canonicalize_boss_task_url(
        f"{BOSS_ORIGIN}/web/geek/jobs?city={city}&industry={industry}"
    )
    return TaskDraft(
        task_type="city_industry",
        source_key=f"city_industry:{city}:{industry}",
        url=url,
        url_hash=_url_hash(url),
        priority=CITY_INDUSTRY_TASK_PRIORITY,
        spider_name=BOSS_TASK_SPIDER,
        spider_args={
            "task_type": "city_industry",
            "city_code": city,
            "industry_code": industry,
            "task_url": url,
        },
        city_code=city,
        industry_code=industry,
    )


def is_boss_industry_leaf(industry: Any, child_parent_codes: Set[int]) -> bool:
    return int(industry.level) == 1 and int(industry.code) not in child_parent_codes


def resolve_major_catalog_candidate(
    candidate: MajorUrlCandidate,
    majors: Sequence[Any],
    position_types: Sequence[Any],
) -> MajorCatalogDraft:
    """Resolve a candidate only against existing normalized taxonomies."""

    major = None
    errors = []
    if candidate.major_code:
        code_matches = [
            item
            for item in majors
            if str(item.code or "").strip() == candidate.major_code
        ]
        if len(code_matches) == 1:
            major = code_matches[0]
        elif len(code_matches) > 1:
            errors.append(f"ambiguous major code: {candidate.major_code}")
        else:
            errors.append(
                f"unmatched major code/name: {candidate.major_code}/{candidate.major_name}"
            )
    else:
        name_matches = [
            item
            for item in majors
            if _clean_text(str(item.name or "")) == candidate.major_name
        ]
        if len(name_matches) == 1:
            major = name_matches[0]
        elif len(name_matches) > 1:
            errors.append(f"ambiguous major name: {candidate.major_name}")
        else:
            errors.append(f"unmatched major name: {candidate.major_name}")

    position_ids_by_code: Dict[str, Set[int]] = {}
    for item in position_types:
        if bool(getattr(item, "is_leaf", False)):
            position_ids_by_code.setdefault(str(item.code), set()).add(int(item.id))
    position_ids = tuple(
        sorted(
            {
                position_type_id
                for code in candidate.position_codes
                for position_type_id in position_ids_by_code.get(code, set())
            }
        )
    )
    missing_positions = [
        code for code in candidate.position_codes if code not in position_ids_by_code
    ]

    if missing_positions:
        errors.append(f"unmatched position_type codes: {','.join(missing_positions)}")

    return MajorCatalogDraft(
        candidate=candidate,
        major_id=int(major.id) if major is not None else None,
        position_type_ids=position_ids,
        parse_error="; ".join(errors) or None,
    )


async def persist_major_catalog(
    repository: MajorCatalogRepository,
    candidates: Sequence[MajorUrlCandidate],
    source_version: Optional[str] = None,
) -> MajorCatalogStats:
    majors = list(await repository.list_majors())
    position_codes = sorted(
        {code for candidate in candidates for code in candidate.position_codes}
    )
    position_types = list(await repository.list_position_types(position_codes))
    drafts = [
        resolve_major_catalog_candidate(candidate, majors, position_types)
        for candidate in candidates
    ]
    created = await repository.upsert_major_catalog(drafts, source_version)
    return MajorCatalogStats(
        expected=len(drafts),
        created=created,
        existing=len(drafts) - created,
        parse_errors=sum(1 for draft in drafts if draft.parse_error),
    )


async def generate_major_tasks(repository: TaskRepository) -> TaskGenerationStats:
    major_urls = list(await repository.list_major_urls())
    enabled = [
        item
        for item in major_urls
        if bool(item.is_active)
        and LEGACY_IDENTITY_PENDING not in (getattr(item, "parse_error", None) or "")
    ]
    expected = len(enabled)
    drafts = (build_major_task_draft(item) for item in enabled)
    created = await repository.upsert_task_drafts(drafts)
    return TaskGenerationStats(
        expected=expected,
        created=created,
        existing=expected - created,
        disabled=len(major_urls) - len(enabled),
    )


async def generate_city_industry_tasks(repository: TaskRepository) -> TaskGenerationStats:
    city_codes = sorted(set(await repository.list_city_level_codes()))
    industry_codes = sorted(set(await repository.list_boss_industry_leaf_codes()))
    expected = len(city_codes) * len(industry_codes)
    drafts = (
        build_city_industry_task_draft(city_code, industry_code)
        for city_code in city_codes
        for industry_code in industry_codes
    )
    created = await repository.upsert_task_drafts(drafts)
    return TaskGenerationStats(
        expected=expected,
        created=created,
        existing=expected - created,
        disabled=0,
    )


class SqlAlchemyTaskRepository:
    """Small AsyncSession adapter used by spiders and explicit service calls."""

    def __init__(self, session: Any) -> None:
        self.session = session

    async def list_major_urls(self) -> Sequence[BossStuCrawlUrl]:
        result = await self.session.execute(
            select(BossStuCrawlUrl).order_by(BossStuCrawlUrl.id.asc())
        )
        return list(result.scalars().all())

    async def list_city_level_codes(self) -> Sequence[str]:
        result = await self.session.execute(
            select(City.code).where(City.level == 1).order_by(City.code.asc())
        )
        return [str(code) for code in result.scalars().all()]

    async def list_boss_industry_leaf_codes(self) -> Sequence[str]:
        child = aliased(Industry)
        result = await self.session.execute(
            select(Industry.code)
            .where(
                Industry.level == 1,
                ~exists(select(1).where(child.parent_id == Industry.code)),
            )
            .order_by(Industry.code.asc())
        )
        return [str(code) for code in result.scalars().all()]

    async def upsert_task_drafts(self, drafts: Iterable[TaskDraft]) -> int:
        created = 0
        for batch in _batched(drafts, TASK_UPSERT_BATCH_SIZE):
            rows = [
                {
                    "id": generate_id(),
                    "task_type": draft.task_type,
                    "source_key": draft.source_key,
                    "url": draft.url,
                    "url_hash": draft.url_hash,
                    "major_url_id": draft.major_url_id,
                    "major_id": draft.major_id,
                    "city_code": draft.city_code,
                    "industry_code": draft.industry_code,
                    "status": "pending",
                    "priority": draft.priority,
                    "max_retries": 3,
                    "spider_name": draft.spider_name,
                    "spider_args": draft.spider_args,
                    "desired_status": "stopped",
                }
                for draft in batch
            ]
            statement = pg_insert(BossCrawlTask).values(rows)
            statement = statement.on_conflict_do_update(
                index_elements=[BossCrawlTask.source_key],
                set_={
                    "task_type": statement.excluded.task_type,
                    "url": statement.excluded.url,
                    "url_hash": statement.excluded.url_hash,
                    "major_url_id": statement.excluded.major_url_id,
                    "major_id": statement.excluded.major_id,
                    "city_code": statement.excluded.city_code,
                    "industry_code": statement.excluded.industry_code,
                    "priority": statement.excluded.priority,
                    "max_retries": statement.excluded.max_retries,
                    "spider_name": statement.excluded.spider_name,
                    "spider_args": statement.excluded.spider_args,
                    "updated_at": func.now(),
                },
            ).returning(sa_literal_column("(xmax = 0)").label("was_inserted"))
            result = await self.session.execute(statement)
            created += sum(bool(value) for value in result.scalars().all())
        return created

    async def list_majors(self) -> Sequence[Major]:
        result = await self.session.execute(select(Major).order_by(Major.id.asc()))
        return list(result.scalars().all())

    async def list_position_types(self, codes: Sequence[str]) -> Sequence[PositionType]:
        numeric_codes = [int(code) for code in codes if str(code).isdigit()]
        if not numeric_codes:
            return []
        result = await self.session.execute(
            select(PositionType).where(
                PositionType.code.in_(numeric_codes),
                PositionType.is_leaf.is_(True),
            )
        )
        return list(result.scalars().all())

    async def upsert_major_catalog(
        self,
        drafts: Sequence[MajorCatalogDraft],
        source_version: Optional[str],
    ) -> int:
        if not drafts:
            return 0

        await self._reconcile_legacy_major_urls(
            [draft.candidate for draft in drafts]
        )

        rows = []
        drafts_by_hash = {}
        for draft in drafts:
            candidate = draft.candidate
            drafts_by_hash[candidate.url_hash] = draft
            ka_values = parse_qs(urlsplit(candidate.raw_url).query).get("ka", [])
            rows.append({
                "id": generate_id(),
                "major_id": draft.major_id,
                "major_code": candidate.major_code,
                "major_name": candidate.major_name,
                "url": candidate.raw_url,
                "ka": ka_values[0] if ka_values else None,
                "raw_url": candidate.raw_url,
                "canonical_url": candidate.canonical_url,
                "url_hash": candidate.url_hash,
                "position_codes": list(candidate.position_codes),
                "experience_code": candidate.experience_code,
                "is_active": True,
                "source_version": source_version,
                "parse_error": draft.parse_error,
            })

        statement = pg_insert(BossStuCrawlUrl).values(rows)
        statement = statement.on_conflict_do_update(
            index_elements=[BossStuCrawlUrl.url_hash],
            set_={
                "major_id": statement.excluded.major_id,
                "major_code": statement.excluded.major_code,
                "major_name": statement.excluded.major_name,
                "url": statement.excluded.url,
                "ka": statement.excluded.ka,
                "raw_url": statement.excluded.raw_url,
                "canonical_url": statement.excluded.canonical_url,
                "position_codes": statement.excluded.position_codes,
                "experience_code": statement.excluded.experience_code,
                "is_active": True,
                "last_seen_at": func.now(),
                "source_version": statement.excluded.source_version,
                "parse_error": statement.excluded.parse_error,
            },
        ).returning(
            BossStuCrawlUrl.id,
            BossStuCrawlUrl.url_hash,
            sa_literal_column("(xmax = 0)").label("was_inserted"),
        )
        returned_rows = list((await self.session.execute(statement)).all())

        major_url_ids = [int(row[0]) for row in returned_rows]
        if major_url_ids:
            await self.session.execute(
                delete(BossStuUrlPosition).where(
                    BossStuUrlPosition.major_url_id.in_(major_url_ids)
                )
            )
        relation_rows = [
            {
                "major_url_id": int(major_url_id),
                "position_type_id": position_type_id,
            }
            for major_url_id, url_hash, _ in returned_rows
            for position_type_id in drafts_by_hash[str(url_hash)].position_type_ids
        ]
        if relation_rows:
            await self.session.execute(
                pg_insert(BossStuUrlPosition)
                .values(relation_rows)
                .on_conflict_do_nothing()
            )

        return sum(bool(row[2]) for row in returned_rows)

    async def _reconcile_legacy_major_urls(
        self, candidates: Sequence[MajorUrlCandidate]
    ) -> None:
        """Reconcile only legacy rows represented in this discovery batch."""

        target_hashes = [candidate.url_hash for candidate in candidates]
        if not target_hashes:
            return
        legacy_result = await self.session.execute(
            select(BossStuCrawlUrl).where(
                BossStuCrawlUrl.parse_error.contains(LEGACY_IDENTITY_PENDING)
            )
        )
        current_result = await self.session.execute(
            select(BossStuCrawlUrl).where(
                BossStuCrawlUrl.url_hash.in_(target_hashes)
            )
        )
        rows_by_id = {
            int(row.id): row
            for row in [
                *legacy_result.scalars().all(),
                *current_result.scalars().all(),
            ]
        }
        plan = plan_legacy_reconciliation(list(rows_by_id.values()), candidates)

        duplicate_ids = list(plan.duplicate_to_survivor)
        if duplicate_ids:
            relation_source = select(
                case(
                    plan.duplicate_to_survivor,
                    value=BossStuUrlPosition.major_url_id,
                ),
                BossStuUrlPosition.position_type_id,
            ).where(BossStuUrlPosition.major_url_id.in_(duplicate_ids))
            await self.session.execute(
                pg_insert(BossStuUrlPosition)
                .from_select(
                    ["major_url_id", "position_type_id"], relation_source
                )
                .on_conflict_do_nothing()
            )
            # Vacate both retained legacy unique identities first so the
            # survivor can claim the discovered raw and canonical identity
            # without a transient collision.
            await self.session.execute(
                update(BossStuCrawlUrl)
                .where(BossStuCrawlUrl.id.in_(duplicate_ids))
                .values(
                    url=case(
                        plan.duplicate_urls,
                        value=BossStuCrawlUrl.id,
                    ),
                    url_hash=case(
                        plan.duplicate_hashes,
                        value=BossStuCrawlUrl.id,
                    ),
                    is_active=False,
                    parse_error=func.concat_ws(
                        "; ",
                        func.nullif(
                            func.replace(
                                BossStuCrawlUrl.parse_error,
                                LEGACY_IDENTITY_PENDING,
                                "",
                            ),
                            "",
                        ),
                        "superseded by canonical discovery",
                    ),
                )
            )

        survivor_ids = list(plan.survivor_updates)
        if survivor_ids:
            canonical_urls = {
                row_id: values[0]
                for row_id, values in plan.survivor_updates.items()
            }
            canonical_hashes = {
                row_id: values[1]
                for row_id, values in plan.survivor_updates.items()
            }
            await self.session.execute(
                update(BossStuCrawlUrl)
                .where(BossStuCrawlUrl.id.in_(survivor_ids))
                .values(
                    canonical_url=case(canonical_urls, value=BossStuCrawlUrl.id),
                    url_hash=case(canonical_hashes, value=BossStuCrawlUrl.id),
                    is_active=True,
                    parse_error=func.replace(
                        BossStuCrawlUrl.parse_error,
                        LEGACY_IDENTITY_PENDING,
                        "",
                    ),
                )
            )
