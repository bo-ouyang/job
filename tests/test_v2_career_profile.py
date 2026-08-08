import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.exc import InvalidRequestError


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from common.databases.models.career_profile import (  # noqa: E402
    CareerProfileChangeLog,
    CareerProfileCourse,
    CareerProfileSkill,
)
from common.databases.models.agent_run import AgentRun  # noqa: E402
from api.v2.api import api_router  # noqa: E402
from schemas.v2.profile import (  # noqa: E402
    ProfileCourseInput,
    ProfileSkillInput,
)
from schemas.v2.career import AIPricingResponse, CareerOverviewQuery  # noqa: E402
from services.v2.profile_service import (  # noqa: E402
    ProfileService,
    deduplicate_profile_items,
    normalize_profile_item_name,
)
from agent.runtime import AgentRuntime  # noqa: E402
from core.exceptions import AppException  # noqa: E402
from services.ai_access_service import AIAccessService  # noqa: E402
from services.v2.career_service import CareerService  # noqa: E402


def _column_names(model) -> set[str]:
    return set(model.__table__.columns.keys())


def test_course_model_supports_normalized_storage_and_resume_review():
    assert CareerProfileCourse.__tablename__ == "career_profile_courses"
    assert {
        "profile_id",
        "name",
        "normalized_name",
        "category",
        "level",
        "is_core",
        "source",
        "source_reference",
        "confirmation_status",
        "evidence",
        "created_at",
        "updated_at",
    } <= _column_names(CareerProfileCourse)

    unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in CareerProfileCourse.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("profile_id", "normalized_name") in unique_columns


def test_skill_model_records_proficiency_experience_and_evidence():
    assert CareerProfileSkill.__tablename__ == "career_profile_skills"
    assert {
        "profile_id",
        "name",
        "normalized_name",
        "category",
        "proficiency_level",
        "years_experience",
        "source",
        "source_reference",
        "confirmation_status",
        "evidence",
        "created_at",
        "updated_at",
    } <= _column_names(CareerProfileSkill)

    check_expressions = {
        str(constraint.sqltext)
        for constraint in CareerProfileSkill.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert any("proficiency_level" in expression for expression in check_expressions)


def test_change_log_keeps_before_after_conflict_and_review_state():
    assert CareerProfileChangeLog.__tablename__ == "career_profile_change_logs"
    assert {
        "profile_id",
        "entity_type",
        "entity_id",
        "change_type",
        "source",
        "source_reference",
        "before_data",
        "after_data",
        "conflict_data",
        "review_status",
        "reviewed_at",
        "created_at",
    } <= _column_names(CareerProfileChangeLog)


def test_agent_run_persists_locked_billing_price():
    assert {
        "billing_feature_key",
        "charge_amount",
        "charged_at",
    } <= _column_names(AgentRun)


def test_profile_collection_schemas_use_v2_camel_case_contract():
    course = ProfileCourseInput(
        name=" 数据库原理 ",
        category="专业核心",
        level="熟练",
        is_core=True,
        source="resume",
        source_reference="resume:1001",
        confirmation_status="pending",
        evidence={"section": "education"},
    )
    skill = ProfileSkillInput(
        name="Python",
        category="技术",
        proficiency_level=4,
        years_experience=2.5,
        source="manual",
        confirmation_status="confirmed",
        evidence="课程与项目",
    )

    assert course.model_dump(by_alias=True)["isCore"] is True
    assert course.model_dump(by_alias=True)["confirmationStatus"] == "pending"
    assert skill.model_dump(by_alias=True)["proficiencyLevel"] == 4
    assert skill.model_dump(by_alias=True)["yearsExperience"] == 2.5


def test_profile_item_normalization_deduplicates_case_and_whitespace():
    items = [
        ProfileSkillInput(name=" Python ", proficiency_level=3),
        ProfileSkillInput(name="python", proficiency_level=4),
        ProfileSkillInput(name="SQL", proficiency_level=3),
    ]

    deduplicated = deduplicate_profile_items(items)

    assert normalize_profile_item_name("  Python  ") == "python"
    assert [item.name for item in deduplicated] == ["python", "SQL"]
    assert deduplicated[0].proficiency_level == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("collection", "payload", "row_type"),
    [
        ("courses", [ProfileCourseInput(name="Database Systems")], CareerProfileCourse),
        ("skills", [ProfileSkillInput(name="Python", proficiency_level=4)], CareerProfileSkill),
    ],
)
async def test_replacing_profile_collection_does_not_readd_parent_with_deleted_children(
    monkeypatch,
    collection,
    payload,
    row_type,
):
    """Bulk-deleted relationship items must not be cascaded back through the parent."""

    profile = SimpleNamespace(
        id=901,
        education={},
        skills=[],
        courses=[CareerProfileCourse(id=11, profile_id=901, name="Old course")],
        normalized_skills=[CareerProfileSkill(id=12, profile_id=901, name="Old skill")],
    )

    class DeletedRelationshipSession:
        def __init__(self):
            self.next_id = 1000

        async def execute(self, statement):
            return None

        def add(self, instance):
            if instance is profile:
                raise InvalidRequestError(
                    "parent cascaded a relationship instance deleted by the bulk DELETE"
                )
            if isinstance(instance, row_type):
                instance.id = self.next_id
                self.next_id += 1

        async def flush(self):
            return None

    service = ProfileService()

    async def get_profile(db, user_id):
        return profile

    async def list_existing(db, user_id):
        return []

    monkeypatch.setattr(service, "_get_or_create_profile", get_profile)
    monkeypatch.setattr(service, f"list_{collection}", list_existing)

    result = await getattr(service, f"replace_{collection}")(
        DeletedRelationshipSession(),
        100,
        payload,
    )

    assert [item.name for item in result] == [payload[0].name]


def test_v2_router_exposes_profile_career_and_pricing_routes():
    paths = {route.path for route in api_router.routes}

    assert {
        "/profile",
        "/profile/courses",
        "/profile/skills",
        "/profile/resume-candidates",
        "/career-analysis/overview",
        "/career-analysis/reports/latest",
        "/career-analysis/reports",
        "/career-analysis/questions",
        "/ai/pricing",
        "/market/questions",
        "/market/history",
    } <= paths


def test_resume_candidate_profile_updates_ignore_empty_education_fields():
    from services.v2.profile_service import resume_education_profile_updates

    updates = resume_education_profile_updates(
        SimpleNamespace(
            school="New University",
            major=None,
            degree="",
            end_date=None,
        )
    )

    assert updates == {"school": "New University"}


def test_resume_candidate_merge_only_selects_new_normalized_names():
    from services.v2.profile_service import select_new_profile_items

    existing = [SimpleNamespace(id=11, normalized_name="python")]
    candidates = [
        ProfileSkillInput(name=" Python "),
        ProfileSkillInput(name="SQL"),
        ProfileSkillInput(name="sql"),
    ]

    selected = select_new_profile_items(existing, candidates)

    assert existing[0].id == 11
    assert [item.name for item in selected] == ["sql"]


@pytest.mark.parametrize(
    "basic",
    [
        {"email": "not-an-email"},
        {"phone": "12345"},
        {"gender": "unknown"},
    ],
)
def test_resume_candidate_schema_rejects_invalid_contact_fields(basic):
    from schemas.v2.profile import ResumeCandidateApply

    with pytest.raises(ValidationError):
        ResumeCandidateApply(basic=basic)


@pytest.mark.asyncio
async def test_get_or_create_profile_reloads_new_profile_relationships(monkeypatch):
    service = ProfileService()
    created = SimpleNamespace(id=901, user_id=100)
    loaded = SimpleNamespace(id=901, user_id=100, courses=[], normalized_skills=[])
    lookups = iter([None, loaded])

    async def get_profile(db, user_id):
        return next(lookups)

    async def upsert_profile(db, user_id, obj_in):
        return created

    monkeypatch.setattr("services.v2.profile_service.crud_agent.get_profile", get_profile)
    monkeypatch.setattr("services.v2.profile_service.crud_agent.upsert_profile", upsert_profile)

    result = await service._get_or_create_profile(object(), 100)

    assert result is loaded


def test_pricing_contract_includes_home_market_question_price():
    item = {
        "amount": 1.5,
        "currency": "CNY",
        "enabled": True,
        "productCode": "ai_career_advice",
        "description": "AI market question",
    }
    pricing = AIPricingResponse(
        careerReport=item,
        careerQuestion=item,
        aiConversation=item,
        marketQuestion=item,
        resumeParse=item,
    )

    assert pricing.model_dump(by_alias=True)["marketQuestion"]["amount"] == 1.5


def test_agent_context_includes_normalized_courses_and_skills():
    profile = SimpleNamespace(
        education={"major": "计算机科学与技术"},
        skills=[{"name": "legacy-snapshot"}],
        experience=None,
        preferences={"target_cities": ["杭州"]},
        constraints=None,
        goals=None,
        courses=[
            SimpleNamespace(
                name="数据结构",
                category="专业核心",
                level="熟练",
                confirmation_status="confirmed",
                evidence={"source": "course"},
            )
        ],
        normalized_skills=[
            SimpleNamespace(
                name="Python",
                category="技术",
                proficiency_level=4,
                years_experience=2.5,
                confirmation_status="confirmed",
                evidence="课程与项目",
            )
        ],
    )

    context = AgentRuntime._profile_data(profile)

    assert context["courses"][0]["name"] == "数据结构"
    assert context["skills"][0]["name"] == "Python"
    assert context["skills"][0]["proficiency_level"] == 4
    assert "legacy-snapshot" not in str(context["skills"])


@pytest.mark.asyncio
async def test_career_submission_reuses_run_for_same_user_idempotency_key(monkeypatch):
    existing_run = SimpleNamespace(
        id=301,
        conversation_id=201,
        status="queued",
    )

    call_order = []

    async def acquire_lock(*args, **kwargs):
        call_order.append("lock")

    async def get_existing(*args, **kwargs):
        call_order.append(("lookup", kwargs["message_type"]))
        return existing_run

    async def should_not_create(*args, **kwargs):
        raise AssertionError("a retry must not create a second conversation")

    monkeypatch.setattr("services.v2.career_service.crud_agent.acquire_user_admission_lock", acquire_lock)
    monkeypatch.setattr("services.v2.career_service.crud_agent.get_run_by_user_idempotency_key", get_existing)
    monkeypatch.setattr("services.v2.career_service.crud_agent.create_conversation", should_not_create)

    result = await CareerService().submit_agent_request(
        db=object(),
        user=SimpleNamespace(id=100),
        content="分析我的职业方向",
        filters={"city": "杭州"},
        idempotency_key="career-request-001",
        title="职业分析报告",
        message_type="career_report_request",
    )

    assert result.conversation_id == "201"
    assert result.run_id == "301"
    assert result.status == "queued"
    assert call_order == ["lock", ("lookup", "career_report_request")]


@pytest.mark.asyncio
async def test_career_submission_returns_stable_active_run_conflict(monkeypatch):
    active_run = SimpleNamespace(
        id=901,
        conversation_id=801,
        status="running",
    )

    async def acquire_lock(*args, **kwargs):
        return None

    async def no_idempotent_match(*args, **kwargs):
        return None

    async def get_active(*args, **kwargs):
        if kwargs.get("message_type") == "career_report_request":
            return active_run, "career_report_request"
        return None

    async def should_not_create(*args, **kwargs):
        raise AssertionError("an active run conflict must not create a conversation")

    monkeypatch.setattr("services.v2.career_service.crud_agent.acquire_user_admission_lock", acquire_lock)
    monkeypatch.setattr("services.v2.career_service.crud_agent.get_run_by_user_idempotency_key", no_idempotent_match)
    monkeypatch.setattr(
        "services.v2.career_service.crud_agent.get_latest_active_run",
        get_active,
        raising=False,
    )
    monkeypatch.setattr("services.v2.career_service.crud_agent.create_conversation", should_not_create)

    with pytest.raises(AppException) as exc_info:
        await CareerService().submit_agent_request(
            db=object(),
            user=SimpleNamespace(id=100),
            content="分析我的职业方向",
            filters={"city": "杭州"},
            idempotency_key="career-request-002",
            title="职业分析报告",
            message_type="career_report_request",
        )

    error = exc_info.value
    assert error.status_code == 409
    assert error.code == "AGENT_ACTIVE_RUN_EXISTS"
    assert error.data == {
        "runId": "901",
        "conversationId": "801",
        "status": "running",
        "messageType": "career_report_request",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("active_message_type", "requested_message_type"),
    [
        ("market_question", "career_report_request"),
        ("career_report_request", "career_question"),
    ],
)
async def test_career_submission_does_not_recover_another_feature_run(
    monkeypatch,
    active_message_type,
    requested_message_type,
):
    active_run = SimpleNamespace(id=902, conversation_id=802, status="running")

    async def acquire_lock(*args, **kwargs):
        return None

    async def no_idempotent_match(*args, **kwargs):
        assert kwargs["message_type"] == requested_message_type
        return None

    async def get_active(*args, **kwargs):
        if kwargs.get("message_type") == requested_message_type:
            return None
        if kwargs.get("exclude_message_type") == requested_message_type:
            return active_run, active_message_type
        return None

    async def should_not_create(*args, **kwargs):
        raise AssertionError("another active Agent feature must block before conversation creation")

    monkeypatch.setattr("services.v2.career_service.crud_agent.acquire_user_admission_lock", acquire_lock)
    monkeypatch.setattr("services.v2.career_service.crud_agent.get_run_by_user_idempotency_key", no_idempotent_match)
    monkeypatch.setattr("services.v2.career_service.crud_agent.get_latest_active_run", get_active)
    monkeypatch.setattr("services.v2.career_service.crud_agent.create_conversation", should_not_create)

    with pytest.raises(AppException) as exc_info:
        await CareerService().submit_agent_request(
            db=object(),
            user=SimpleNamespace(id=100),
            content="分析我的职业方向",
            filters={"city": "杭州"},
            idempotency_key="career-request-cross-feature",
            title="职业分析",
            message_type=requested_message_type,
        )

    error = exc_info.value
    assert error.status_code == 409
    assert error.code == "AGENT_OTHER_RUN_ACTIVE"
    assert error.data == {
        "runId": "902",
        "conversationId": "802",
        "status": "running",
        "messageType": active_message_type,
    }


@pytest.mark.asyncio
async def test_public_pricing_uses_active_backend_products(monkeypatch):
    prices = {
        "ai_career_compass": 12.5,
        "ai_career_advice": 1.5,
    }

    async def get_product(db, code):
        return SimpleNamespace(is_active=True, price=prices[code])

    monkeypatch.setattr("services.ai_access_service.crud_product.product.get_by_code", get_product)
    monkeypatch.setattr("services.ai_access_service.settings.AI_BILLING_ENABLED", True)

    pricing = await AIAccessService().get_public_pricing(
        object(),
        ["career_compass", "career_advice"],
    )

    assert pricing["career_compass"]["amount"] == 12.5
    assert pricing["career_advice"]["amount"] == 1.5
    assert pricing["career_compass"]["product_code"] == "ai_career_compass"


@pytest.mark.asyncio
async def test_career_overview_adapts_agent_dictionary_variants(monkeypatch):
    service = CareerService()
    message = SimpleNamespace(
        metadata_json={
            "result": {
                "directions": [
                    {
                        "name": "数据分析师",
                        "match": "高",
                        "summary": "专业与技能基础匹配",
                    }
                ],
                "skill_gaps": [
                    {
                        "skill": "SQL",
                        "gap": "需要补充复杂查询实践",
                    }
                ],
                "next_actions": [{"action": "完成 SQL 项目"}],
            },
            "evidence": [{"sample_size": 20}],
        },
        created_at=datetime(2026, 7, 28, tzinfo=timezone.utc),
    )

    async def latest_answer(db, user_id):
        return message

    async def profile_view(db, user):
        return SimpleNamespace(
            name="测试用户",
            completion=80,
            school="测试大学",
            major="计算机科学",
            graduation_year="2027",
            education="本科",
        )

    monkeypatch.setattr(service, "_latest_answer", latest_answer)
    monkeypatch.setattr("services.v2.career_service.profile_service.get_profile", profile_view)

    overview = await service.get_overview(
        object(),
        SimpleNamespace(id=100),
        CareerOverviewQuery(city="杭州"),
    )

    assert overview.directions[0].title == "数据分析师"
    assert overview.directions[0].match is not None
    assert overview.directions[0].reason == "专业与技能基础匹配"
    assert overview.directions[0].tags
    assert len(overview.directions) >= 3
    assert overview.skills[0].name == "SQL"
    assert overview.skills[0].advice == "需要补充复杂查询实践"
    assert overview.skills[0].current is not None
    assert overview.skills[0].target is not None
    assert len(overview.skills) >= 6
    assert len(overview.cities) >= 3
    assert overview.cities[0].city == "杭州"
    assert all(
        city.jobs and city.salary and city.growth and city.competition
        for city in overview.cities
    )
    assert len(overview.plan) >= 3
    assert overview.plan[0].title == "完成 SQL 项目"
    assert all(item.items for item in overview.plan)
    assert {
        "career.agent_report",
        "career.city_comparison",
        "career.skill_gap",
        "career.action_plan",
    } <= set(overview.data_status.synthetic_dimensions)


@pytest.mark.asyncio
async def test_career_overview_fills_missing_report_sections_with_test_data(monkeypatch):
    service = CareerService()

    async def no_latest_answer(db, user_id):
        return None

    async def profile_view(db, user):
        return SimpleNamespace(
            name="真实用户",
            completion=35,
            school="真实大学",
            major="软件工程",
            graduation_year="2027",
            education="本科",
        )

    monkeypatch.setattr(service, "_latest_answer", no_latest_answer)
    monkeypatch.setattr("services.v2.career_service.profile_service.get_profile", profile_view)

    overview = await service.get_overview(
        object(),
        SimpleNamespace(id=100),
        CareerOverviewQuery(city="杭州"),
    )

    assert overview.profile.name == "真实用户"
    assert overview.profile.school == "真实大学"
    assert overview.directions
    assert overview.cities
    assert overview.skills
    assert overview.plan
    assert overview.data_status.source == "mixed"
    assert "career.agent_report" in overview.data_status.missing_dimensions
    assert "career.agent_report" in overview.data_status.synthetic_dimensions


@pytest.mark.asyncio
async def test_career_overview_prioritizes_selected_city_and_direction(monkeypatch):
    service = CareerService()

    message = SimpleNamespace(
        metadata_json={
            "result": {
                "directions": [
                    {"title": "Java 后端", "match": 88, "reason": "市场需求稳定", "tags": ["真实报告"]},
                    {"title": "Python 后端", "match": 86, "reason": "技能基础匹配", "tags": ["真实报告"]},
                    {"title": "全栈开发", "match": 80, "reason": "能力可迁移", "tags": ["真实报告"]},
                ],
                "cities": [
                    {"city": "杭州", "jobs": "100", "salary": "18K", "growth": "+10%", "competition": "中"},
                    {"city": "上海", "jobs": "120", "salary": "20K", "growth": "+8%", "competition": "高"},
                    {"city": "深圳", "jobs": "110", "salary": "19K", "growth": "+9%", "competition": "中高"},
                ],
            }
        },
        created_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
    )

    async def latest_answer(db, user_id):
        return message

    async def profile_view(db, user):
        return SimpleNamespace(
            name="筛选用户",
            completion=70,
            school="测试大学",
            major="软件工程",
            graduation_year="2027",
            education="本科",
        )

    monkeypatch.setattr(service, "_latest_answer", latest_answer)
    monkeypatch.setattr("services.v2.career_service.profile_service.get_profile", profile_view)

    overview = await service.get_overview(
        object(),
        SimpleNamespace(id=100),
        CareerOverviewQuery(city="北京", direction="商业分析师"),
    )

    assert overview.cities[0].city == "北京"
    assert overview.directions[0].title == "商业分析师"
    assert all(direction.match is not None for direction in overview.directions)
    assert all(direction.reason and direction.tags for direction in overview.directions)
