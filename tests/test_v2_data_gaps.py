import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from services.data_gap_registry import get_gap, list_data_gaps


def test_registry_contains_crawler_actionable_market_fields():
    gap = get_gap("market.monthly_job_trend")

    assert gap.owner == "crawler"
    assert gap.required_fields
    assert gap.source_fields
    assert gap.refresh_frequency == "daily"
    assert gap.priority == "P0"


def test_registry_keys_are_unique_and_machine_readable():
    gaps = list_data_gaps()
    keys = [gap.key for gap in gaps]

    assert len(keys) == len(set(keys))
    assert all("." in key and " " not in key for key in keys)


def test_registry_records_frontend_test_data_fields():
    trend_gap = get_gap("market.monthly_job_trend")
    talent_gap = get_gap("market.talent_structure")

    assert trend_gap.test_data_fields == ["heroSignals", "trend", "signals"]
    assert talent_gap.status == "missing"
    assert talent_gap.test_data_fields == ["talentStructure"]


def test_registry_records_missing_career_analysis_sections():
    report_gap = get_gap("career.agent_report")
    city_gap = get_gap("career.city_comparison")

    assert report_gap.owner == "agent"
    assert "directions" in report_gap.test_data_fields
    assert city_gap.test_data_fields == ["cities"]
