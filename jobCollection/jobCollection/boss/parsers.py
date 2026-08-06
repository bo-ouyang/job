"""Pure parsing helpers shared by the retained BOSS spiders."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from parsel import Selector

from jobCollection.items.boss_job_item import BossJobItem


@dataclass(frozen=True)
class BossJobDetail:
    """Validated detail data received from BOSS' JSON endpoint."""

    encrypt_job_id: str
    description: str
    data: Dict[str, Any]


def extract_jobs_and_has_more(
    payload: Optional[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Optional[bool]]:
    """Normalize the supported BOSS list payload envelopes."""
    container, list_key = _job_list_container(payload)
    if container is None or list_key is None:
        return [], None

    jobs = container.get(list_key)
    if not isinstance(jobs, list):
        return [], None
    return jobs, _parse_optional_bool(container.get("hasMore"))


def is_job_list_payload(payload: Optional[Dict[str, Any]]) -> bool:
    """Return whether a payload explicitly contains a supported job-list field."""
    container, list_key = _job_list_container(payload)
    return bool(
        container is not None
        and list_key is not None
        and isinstance(container.get(list_key), list)
    )


def _job_list_container(
    payload: Optional[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not isinstance(payload, dict):
        return None, None
    for container in (payload.get("zpData"), payload.get("data"), payload):
        if not isinstance(container, dict):
            continue
        for key in ("jobList", "list"):
            if key in container:
                return container, key
    return None, None


def _parse_optional_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    return None


def parse_boss_job_detail(payload: Optional[Dict[str, Any]]) -> BossJobDetail:
    """Extract one validated job detail from the supported JSON envelopes."""
    if not isinstance(payload, dict):
        raise ValueError("detail payload must be an object")

    data: Any = payload
    for key in ("zpData", "data"):
        nested = data.get(key) if isinstance(data, dict) else None
        if isinstance(nested, dict):
            data = nested
            break
    if isinstance(data, dict) and isinstance(data.get("jobInfo"), dict):
        data = data["jobInfo"]
    if not isinstance(data, dict):
        raise ValueError("detail payload does not contain job data")

    encrypt_job_id = data.get("encryptJobId") or data.get("encrypt_job_id")
    if not isinstance(encrypt_job_id, str) or not encrypt_job_id.strip():
        raise ValueError("detail payload is missing encryptJobId")

    description = (
        data.get("postDescription")
        or data.get("jobDescription")
        or data.get("jobDesc")
        or data.get("description")
    )
    if not isinstance(description, str) or not description.strip():
        raise ValueError("detail payload is missing description")
    normalized_description = "\n".join(
        line.strip() for line in description.strip().splitlines() if line.strip()
    )
    return BossJobDetail(
        encrypt_job_id=encrypt_job_id.strip(),
        description=normalized_description,
        data=dict(data),
    )


def build_boss_job_item(
    job: Dict[str, Any], source_url: str, major_name: str = ""
) -> BossJobItem:
    """Map one BOSS list record plus URL context to a ``BossJobItem``."""
    query_params = parse_qs(urlparse(source_url).query)
    item = BossJobItem()
    item["job_name"] = job.get("jobName")
    item["salary_desc"] = job.get("salaryDesc")
    item["job_experience"] = job.get("jobExperience")
    item["job_degree"] = job.get("jobDegree")
    item["city_name"] = job.get("cityName")
    item["area_district"] = job.get("areaDistrict")
    item["business_district"] = job.get("businessDistrict")
    item["job_labels"] = job.get("jobLabels", [])
    item["skills"] = job.get("skills", [])
    item["welfare_list"] = job.get("welfareList", [])
    item["encrypt_job_id"] = job.get("encryptJobId")
    item["encrypt_brand_id"] = job.get("encryptBrandId")
    item["brand_name"] = job.get("brandName")
    item["brand_logo"] = job.get("brandLogo")
    item["brand_stage_name"] = job.get("brandStageName")
    item["brand_industry"] = job.get("brandIndustry")
    item["brand_scale_name"] = job.get("brandScaleName")

    gps = job.get("gps")
    item["longitude"] = gps.get("longitude") if isinstance(gps, dict) else None
    item["latitude"] = gps.get("latitude") if isinstance(gps, dict) else None
    item["boss_name"] = job.get("bossName")
    item["boss_title"] = job.get("bossTitle")
    item["boss_avatar"] = job.get("bossAvatar")
    item["major_name"] = major_name or None

    industry_code = query_params.get("industry", [None])[0] or job.get("industry")
    city_code = query_params.get("city", [None])[0]
    for field_name, value in (
        ("industry_code", industry_code),
        ("city_code", city_code),
    ):
        if value is not None:
            try:
                item[field_name] = int(value)
            except (TypeError, ValueError):
                pass

    return item


def parse_job_description(html: str) -> Optional[str]:
    """Extract and normalize a description from either retained BOSS DOM shape."""
    if not html:
        return None

    selector = Selector(text=html)
    for css_selector in (
        ".job-detail-section .job-sec-text",
        ".job-detail-body .desc",
    ):
        node = selector.css(css_selector)
        if not node:
            continue
        parts = node.xpath(".//text()").getall()
        text = "\n".join(part.strip() for part in parts if part.strip())
        if text:
            return text
    return None
