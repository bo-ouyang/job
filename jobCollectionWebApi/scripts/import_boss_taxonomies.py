"""Fetch and idempotently import Boss industries and position types."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from common.databases.models.industry import Industry
from common.databases.models.position_type import PositionType
from common.utils.snowflake import generate_id


POSITION_SOURCE_URL = "https://www.zhipin.com/wapi/zpCommon/data/getCityShowPosition"
INDUSTRY_SOURCE_URL = "https://www.zhipin.com/wapi/zpCommon/data/industryFilterExemption"
REQUEST_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.zhipin.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36"
    ),
}
IMPORT_LOCK_KEY = 1785933793


class TaxonomyImportError(RuntimeError):
    """Raised when Boss returns an unusable taxonomy response."""


def build_source_url(base_url: str, *, now_ms: int | None = None) -> str:
    """Add or replace Boss's cache-busting `_` query parameter."""
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["_"] = str(now_ms if now_ms is not None else int(time.time() * 1000))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _validate_envelope(payload: Any) -> Any:
    if not isinstance(payload, dict):
        raise TaxonomyImportError("Boss response must be a JSON object")
    if payload.get("code") != 0:
        raise TaxonomyImportError(
            f"Boss response failed: code={payload.get('code')}, message={payload.get('message')}"
        )
    return payload.get("zpData")


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    normalized = str(value).strip()
    return normalized or None


def _validate_node(node: Any, *, path: str) -> tuple[int, str, list[dict[str, Any]]]:
    if not isinstance(node, dict):
        raise TaxonomyImportError(f"Taxonomy node at {path or '/'} must be an object")
    code = node.get("code")
    name = node.get("name")
    if isinstance(code, bool) or not isinstance(code, int) or not str(name or "").strip():
        raise TaxonomyImportError(f"Taxonomy node at {path or '/'} has invalid code/name")
    children = node.get("subLevelModelList")
    if children is None:
        children = []
    if not isinstance(children, list):
        raise TaxonomyImportError(f"Taxonomy children at {path or '/'} must be a list or null")
    return code, str(name).strip(), children


def _common_fields(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "tip": _string(node.get("tip")),
        "first_char": _string(node.get("firstChar")),
        "pinyin": _string(node.get("pinyin")),
        "mark": _integer(node.get("mark")),
        "city_type": _integer(node.get("cityType")),
        "capital": _integer(node.get("capital")),
        "color": _string(node.get("color")),
        "recruitment_type": _string(node.get("recruitmentType")),
        "city_code": _string(node.get("cityCode")),
        "region_code": _integer(node.get("regionCode")),
    }


def parse_industries(payload: Any) -> list[dict[str, Any]]:
    """Flatten Boss's two-level industry tree for the existing `industries` table."""
    roots = _validate_envelope(payload)
    if not isinstance(roots, list):
        raise TaxonomyImportError("Industry zpData must be an array")

    rows: list[dict[str, Any]] = []
    seen_codes: set[int] = set()

    def walk(nodes: Iterable[dict[str, Any]], parent_code: int | None, level: int, codes: tuple[int, ...]):
        for sort_order, node in enumerate(nodes):
            code, name, children = _validate_node(node, path="/" + "/".join(map(str, codes)))
            if code in seen_codes:
                raise TaxonomyImportError(f"Industry code {code} appears more than once")
            seen_codes.add(code)
            node_codes = (*codes, code)
            common = _common_fields(node)
            rows.append(
                {
                    "code": code,
                    "name": name,
                    "parent_id": parent_code,
                    "level": level,
                    "path": "/" + "/".join(map(str, node_codes)) + "/",
                    "rank": sort_order,
                    "position_type": _integer(node.get("positionType")),
                    "center_geo": _string(node.get("centerGeo")),
                    "value": _string(node.get("value")),
                    **common,
                }
            )
            walk(children, code, level + 1, node_codes)

    walk(roots, None, 0, ())
    return rows


def parse_position_types(payload: Any) -> list[dict[str, Any]]:
    """Flatten Boss's position tree while retaining duplicate codes by full path."""
    data = _validate_envelope(payload)
    if not isinstance(data, dict) or not isinstance(data.get("position"), list):
        raise TaxonomyImportError("Position zpData.position must be an array")

    rows: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    def walk(
        nodes: Iterable[dict[str, Any]],
        parent_code: int | None,
        parent_path: str | None,
        level: int,
        codes: tuple[int, ...],
    ):
        for sort_order, node in enumerate(nodes):
            code, name, children = _validate_node(node, path=parent_path or "/")
            node_codes = (*codes, code)
            path = "/" + "/".join(map(str, node_codes)) + "/"
            if path in seen_paths:
                raise TaxonomyImportError(f"Position path {path} appears more than once")
            seen_paths.add(path)
            source_payload = {
                key: value for key, value in node.items() if key != "subLevelModelList"
            }
            rows.append(
                {
                    "code": code,
                    "name": name,
                    "parent_code": parent_code,
                    "parent_path": parent_path,
                    "level": level,
                    "path": path,
                    "sort_order": sort_order,
                    "is_leaf": not children,
                    "rank": _integer(node.get("rank")),
                    "source_position_type": _integer(node.get("positionType")),
                    "center_geo": node.get("centerGeo"),
                    "value": node.get("value"),
                    "source_payload": source_payload,
                    **_common_fields(node),
                }
            )
            walk(children, code, path, level + 1, node_codes)

    walk(data["position"], None, None, 0, ())
    return rows


def prepare_position_records(
    rows: Iterable[dict[str, Any]],
    *,
    existing_ids: dict[str, int],
    id_factory: Callable[[], int] = generate_id,
) -> list[dict[str, Any]]:
    """Assign stable IDs and resolve exact parent IDs from path identity."""
    path_ids = dict(existing_ids)
    records: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        path = row["path"]
        if path not in path_ids:
            path_ids[path] = id_factory()
        row["id"] = path_ids[path]
        parent_path = row.pop("parent_path")
        if parent_path is None:
            row["parent_id"] = None
        elif parent_path in path_ids:
            row["parent_id"] = path_ids[parent_path]
        else:
            raise TaxonomyImportError(f"Position parent path {parent_path} was not imported first")
        records.append(row)
    return records


def build_industry_upsert(rows: Iterable[dict[str, Any]]):
    now = datetime.utcnow()
    records = [{**row, "created_at": now, "updated_at": now} for row in rows]
    if not records:
        raise TaxonomyImportError("Industry response contains no rows")
    statement = insert(Industry).values(records)
    excluded = statement.excluded
    update_columns = {
        column.name: excluded[column.name]
        for column in Industry.__table__.columns
        if column.name not in {"id", "code", "created_at"}
    }
    return statement.on_conflict_do_update(index_elements=[Industry.code], set_=update_columns)


def build_position_upsert(rows: Iterable[dict[str, Any]]):
    records = list(rows)
    if not records:
        raise TaxonomyImportError("Position response contains no rows")
    statement = insert(PositionType).values(records)
    excluded = statement.excluded
    update_columns = {
        column.name: excluded[column.name]
        for column in PositionType.__table__.columns
        if column.name not in {"id", "path", "created_at"}
    }
    update_columns["updated_at"] = datetime.utcnow()
    return statement.on_conflict_do_update(index_elements=[PositionType.path], set_=update_columns)


async def fetch_json(client: httpx.AsyncClient, source_url: str) -> dict[str, Any]:
    response = await client.get(build_source_url(source_url), headers=REQUEST_HEADERS)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise TaxonomyImportError(f"Boss returned invalid JSON from {source_url}") from exc


async def ensure_taxonomy_tables(engine) -> None:
    """Create only the two taxonomy tables when they do not yet exist."""
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Industry.__table__.create(
                sync_connection, checkfirst=True
            )
        )
        await connection.run_sync(
            lambda sync_connection: PositionType.__table__.create(
                sync_connection, checkfirst=True
            )
        )


async def write_taxonomies(
    session,
    *,
    industry_rows: list[dict[str, Any]],
    position_rows: list[dict[str, Any]],
    id_factory: Callable[[], int] = generate_id,
) -> None:
    """Write one snapshot while serializing concurrent import processes."""
    await session.execute(text(f"SELECT pg_advisory_xact_lock({IMPORT_LOCK_KEY})"))
    await session.execute(build_industry_upsert(industry_rows))
    existing_result = await session.execute(select(PositionType.path, PositionType.id))
    existing_ids = dict(existing_result.all())
    position_records = prepare_position_records(
        position_rows,
        existing_ids=existing_ids,
        id_factory=id_factory,
    )
    await session.execute(build_position_upsert(position_records))


async def import_taxonomies(
    *,
    position_url: str = POSITION_SOURCE_URL,
    industry_url: str = INDUSTRY_SOURCE_URL,
    timeout_seconds: float = 30.0,
) -> dict[str, int]:
    """Fetch both sources, create missing tables, and upsert all nodes atomically."""
    from common.databases.PostgresManager import db_manager

    timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10.0))
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        position_payload, industry_payload = await asyncio.gather(
            fetch_json(client, position_url),
            fetch_json(client, industry_url),
        )

    position_rows = parse_position_types(position_payload)
    industry_rows = parse_industries(industry_payload)

    await db_manager.initialize()
    await ensure_taxonomy_tables(db_manager.engine)
    try:
        async with db_manager.async_session() as session:
            async with session.begin():
                await write_taxonomies(
                    session,
                    industry_rows=industry_rows,
                    position_rows=position_rows,
                )
    finally:
        await db_manager.close()

    return {
        "industries": len(industry_rows),
        "positionTypes": len(position_rows),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import Boss industry and position taxonomies into PostgreSQL"
    )
    parser.add_argument("--position-url", default=POSITION_SOURCE_URL)
    parser.add_argument("--industry-url", default=INDUSTRY_SOURCE_URL)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    result = await import_taxonomies(
        position_url=args.position_url,
        industry_url=args.industry_url,
        timeout_seconds=args.timeout,
    )
    print(
        "Boss taxonomy import completed: "
        f"industries={result['industries']}, position_types={result['positionTypes']}"
    )


if __name__ == "__main__":
    asyncio.run(_main())
