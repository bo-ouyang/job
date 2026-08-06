"""Stable identities for BOSS crawl target URLs."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def canonicalize_boss_task_url(raw_url: str) -> str:
    """Return a stable URL identity without changing source filter semantics.

    Tracking-only ``ka`` parameters are removed. All ``position`` values are
    merged, split on commas, deduplicated, and sorted. Other query parameters,
    including the source URL's ``experience`` value, are preserved and sorted.
    """

    if not isinstance(raw_url, str) or not raw_url.strip():
        raise ValueError("BOSS task URL must be a non-empty absolute URL")

    parsed = urlsplit(raw_url.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("BOSS task URL must be an absolute HTTP(S) URL")

    query_items = []
    position_codes = set()
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key == "ka":
            continue
        if key == "position":
            position_codes.update(
                code.strip() for code in value.split(",") if code.strip()
            )
            continue
        query_items.append((key, value))

    if position_codes:
        query_items.append(("position", ",".join(sorted(position_codes))))

    query_items.sort(key=lambda item: (item[0], item[1]))
    canonical_query = urlencode(query_items, doseq=True, safe=",")
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            canonical_query,
            "",
        )
    )
