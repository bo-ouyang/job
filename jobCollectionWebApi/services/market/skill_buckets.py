"""Framework-free skill bucket normalization owned by the Market domain."""

from collections import Counter
import re
from typing import Any, Dict, Iterable, List, Mapping


_SKILL_AGGREGATIONS = ("top_skills", "top_ai_skills")


def build_skill_aggregations(size: int) -> Dict[str, Any]:
    """Build the standard ES sources used to collect Market skill evidence."""
    return {
        "top_skills": {"terms": {"field": "skills", "size": int(size)}},
        "top_ai_skills": {"terms": {"field": "ai_skills", "size": int(size)}},
    }


def normalize_skill_tag(tag: Any) -> str:
    text = str(tag or "").strip()
    return re.sub(r"\s+", " ", text) if text else ""


def is_noise_skill_tag(
    tag: str,
    exact_noise: Iterable[str],
    contains_noise: Iterable[str],
) -> bool:
    normalized = normalize_skill_tag(tag)
    if not normalized:
        return True

    if normalized.lower() in {normalize_skill_tag(item).lower() for item in exact_noise}:
        return True

    if any(
        normalized_token in normalized
        for item in contains_noise
        if (normalized_token := normalize_skill_tag(item))
    ):
        return True

    return bool(re.fullmatch(r"[0-9\W_]+", normalized))


def merge_skill_buckets(
    aggregations: Mapping[str, Any],
    *,
    exact_noise: Iterable[str],
    contains_noise: Iterable[str],
    limit: int,
) -> List[Dict[str, Any]]:
    """Merge skills and AI skills, then apply the Market noise policy and top-N."""
    counter: Counter[str] = Counter()
    for aggregation_name in _SKILL_AGGREGATIONS:
        buckets = (aggregations.get(aggregation_name) or {}).get("buckets", [])
        for bucket in buckets:
            label = normalize_skill_tag(bucket.get("key"))
            if is_noise_skill_tag(label, exact_noise, contains_noise):
                continue
            counter[label] += int(bucket.get("doc_count", 0) or 0)
    return [
        {"name": name, "value": count}
        for name, count in counter.most_common(limit)
    ]
