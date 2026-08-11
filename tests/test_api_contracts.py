import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from api.v1.api import api_router
from schemas.company_schema import CompanySimple
from schemas.job_schema import JobInDB, JobSimple


def route_pairs():
    return {
        (method, f"/api/v1{route.path}")
        for route in api_router.routes
        for method in (getattr(route, "methods", None) or set())
    }


def test_active_frontend_routes_are_exposed_by_backend():
    routes = route_pairs()
    assert ("GET", "/api/v1/industries/level/{level}") in routes
    assert ("GET", "/api/v1/industries/parent/{parent_id}") in routes
    assert ("GET", "/api/v1/industries/tree/") in routes


def test_industry_routes_do_not_repeat_the_resource_prefix():
    assert not any(
        "/industries/industries/" in path
        for _, path in route_pairs()
    )


def test_job_list_items_keep_the_job_identifier():
    item = JobSimple.model_validate(
        {
            "id": 9223372036854775000,
            "title": "Python 工程师",
        }
    )
    assert item.model_dump(mode="json")["id"] == "9223372036854775000"


def test_detail_and_company_ids_are_safe_for_javascript():
    job = JobInDB.model_validate(
        {"id": 9223372036854775000, "title": "Python 工程师"}
    )
    company = CompanySimple.model_validate(
        {"id": 9223372036854775001, "name": "示例公司"}
    )
    assert job.model_dump(mode="json")["id"] == "9223372036854775000"
    assert company.model_dump(mode="json")["id"] == "9223372036854775001"
