import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from api.v2.api import api_router
from config import settings


def test_v2_router_exposes_page_aggregation_routes():
    paths = {route.path for route in api_router.routes}

    assert "/meta/data-gaps" in paths
    assert "/market/dashboard" in paths


def test_v1_and_v2_prefixes_are_distinct():
    assert settings.API_V1_STR == "/api/v1"
    assert settings.API_V2_STR == "/api/v2"
    assert settings.API_V1_STR != settings.API_V2_STR
