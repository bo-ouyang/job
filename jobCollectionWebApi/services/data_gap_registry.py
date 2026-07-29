from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class DataGap:
    key: str
    module: str
    description: str
    required_fields: List[str]
    source_fields: List[str]
    refresh_frequency: str
    priority: str
    owner: str = "crawler"
    status: str = "missing"
    test_data_fields: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


_GAPS = (
    DataGap(
        key="market.monthly_job_trend",
        module="market",
        description="按自然月、城市和行业统计有效岗位发布量及同比/环比。",
        required_fields=["snapshot_month", "city_code", "industry_code", "active_job_count"],
        source_fields=["jobs.publish_date", "jobs.city_code", "jobs.industry_code", "jobs.is_active"],
        refresh_frequency="daily",
        priority="P0",
        test_data_fields=["heroSignals", "trend", "signals"],
    ),
    DataGap(
        key="market.salary_percentiles",
        module="market",
        description="按城市、行业、学历和经验沉淀薪资 P25/P50/P75 历史快照。",
        required_fields=["snapshot_date", "dimension_key", "p25", "p50", "p75", "sample_size"],
        source_fields=["jobs.salary_min", "jobs.salary_max", "jobs.salary_unit"],
        refresh_frequency="daily",
        priority="P0",
        test_data_fields=["citySalaries", "salarySummary"],
    ),
    DataGap(
        key="market.normalized_skill_frequency",
        module="market",
        description="标准化技能别名并记录招聘文本中的需求频率与趋势。",
        required_fields=["skill_code", "canonical_name", "alias", "job_count", "snapshot_date"],
        source_fields=["jobs.tags", "jobs.ai_skills", "jobs.description", "jobs.requirements"],
        refresh_frequency="daily",
        priority="P0",
        test_data_fields=["skills"],
    ),
    DataGap(
        key="market.city_competition",
        module="market",
        description="城市岗位供给与候选人才数量形成的竞争度。",
        required_fields=["city_code", "job_count", "candidate_count", "competition_ratio"],
        source_fields=["jobs.city_code", "external_candidate_supply"],
        refresh_frequency="weekly",
        priority="P1",
        test_data_fields=["cityMatrix"],
    ),
    DataGap(
        key="market.talent_shortage_index",
        module="market",
        description="行业人才缺口和机会指数所需的供需指标。",
        required_fields=["industry_code", "demand_count", "supply_count", "shortage_index"],
        source_fields=["jobs.industry_code", "external_candidate_supply"],
        refresh_frequency="weekly",
        priority="P1",
        test_data_fields=["rankings"],
    ),
    DataGap(
        key="market.talent_structure",
        module="market",
        description="学历要求和工作经验要求的标准化占比。",
        required_fields=["dimension_type", "label", "job_count", "ratio", "snapshot_date"],
        source_fields=["jobs.education", "jobs.experience"],
        refresh_frequency="daily",
        priority="P1",
        test_data_fields=["talentStructure"],
    ),
    DataGap(
        key="market.filter_taxonomy",
        module="market",
        description="前端筛选所需的城市、行业稳定编码和展示名称。",
        required_fields=["dimension_type", "code", "name", "is_active"],
        source_fields=["cities", "industries", "jobs.city_code", "jobs.industry_code"],
        refresh_frequency="daily",
        priority="P1",
        test_data_fields=["filters.cities", "filters.industries"],
    ),
    DataGap(
        key="career.agent_report",
        module="career",
        description="基于已确认用户资料和市场证据生成的职业方向报告。",
        required_fields=["user_id", "run_id", "directions", "evidence", "created_at"],
        source_fields=["career_profiles", "career_profile_courses", "career_profile_skills", "agent_messages"],
        refresh_frequency="on_demand",
        priority="P0",
        owner="agent",
        test_data_fields=["directions", "evidence"],
    ),
    DataGap(
        key="career.city_comparison",
        module="career",
        description="目标职业在不同城市的岗位量、薪资、增长和竞争度。",
        required_fields=["direction_code", "city_code", "job_count", "salary_p50", "growth", "competition_ratio"],
        source_fields=["market salary snapshots", "market city competition"],
        refresh_frequency="daily",
        priority="P1",
        test_data_fields=["cities"],
    ),
    DataGap(
        key="career.skill_gap",
        module="career",
        description="用户当前技能与目标岗位技能要求之间的差距。",
        required_fields=["user_id", "direction_code", "skill_code", "current_level", "target_level"],
        source_fields=["career_profile_skills", "market normalized skills"],
        refresh_frequency="on_demand",
        priority="P0",
        owner="agent",
        test_data_fields=["skills"],
    ),
    DataGap(
        key="career.action_plan",
        module="career",
        description="结合技能差距生成的分阶段职业行动计划。",
        required_fields=["user_id", "run_id", "period", "title", "items"],
        source_fields=["career skill gap", "agent report"],
        refresh_frequency="on_demand",
        priority="P1",
        owner="agent",
        test_data_fields=["plan"],
    ),
    DataGap(
        key="market.source_coverage",
        module="quality",
        description="各招聘来源的采集覆盖率、失败率和数据新鲜度。",
        required_fields=["source_site", "expected_count", "collected_count", "latest_crawled_at"],
        source_fields=["jobs.source_site", "fetch_failures", "crawler_run_log"],
        refresh_frequency="hourly",
        priority="P1",
    ),
)

_BY_KEY: Dict[str, DataGap] = {gap.key: gap for gap in _GAPS}


def list_data_gaps(status: Optional[str] = None) -> List[DataGap]:
    if status is None:
        return list(_GAPS)
    return [gap for gap in _GAPS if gap.status == status]


def get_gap(key: str) -> DataGap:
    try:
        return _BY_KEY[key]
    except KeyError as exc:
        raise KeyError(f"Unknown data gap: {key}") from exc
