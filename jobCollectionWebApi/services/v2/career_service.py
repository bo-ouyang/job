import json
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.databases.models.agent_message import AgentMessage
from crud import agent as crud_agent
from schemas.agent_schema import AgentConversationCreate, AgentMessageCreate
from schemas.v2.career import (
    CareerEvidence,
    CareerOverviewQuery,
    CareerOverviewResponse,
    CareerProfileSummary,
    CareerSubmissionResponse,
)
from schemas.v2.common import DataStatus
from services.v2.career_test_data import CAREER_TEST_DATA
from services.v2.profile_service import profile_service


class CareerService:
    @staticmethod
    def _number(value) -> Optional[float]:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip().removesuffix("%"))
            except ValueError:
                return None
        return None

    @classmethod
    def _directions(cls, items) -> list[dict]:
        result = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            title = item.get("title") or item.get("name")
            if not title:
                continue
            tags = item.get("tags") if isinstance(item.get("tags"), list) else []
            result.append(
                {
                    "title": str(title),
                    "match": cls._number(item.get("match")),
                    "reason": str(item.get("reason") or item.get("summary") or ""),
                    "tags": [str(tag) for tag in tags],
                }
            )
        return result

    @classmethod
    def _skill_gaps(cls, items) -> list[dict]:
        result = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("skill") or item.get("title")
            if not name:
                continue
            result.append(
                {
                    "name": str(name),
                    "current": cls._number(item.get("current")),
                    "target": cls._number(item.get("target")),
                    "advice": str(item.get("advice") or item.get("gap") or "") or None,
                }
            )
        return result

    @staticmethod
    def _cities(items) -> list[dict]:
        result = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            city = item.get("city") or item.get("name")
            if not city:
                continue
            result.append(
                {
                    "city": str(city),
                    "jobs": item.get("jobs"),
                    "salary": item.get("salary"),
                    "growth": item.get("growth"),
                    "competition": item.get("competition"),
                }
            )
        return result

    @staticmethod
    def _plan(items) -> list[dict]:
        result = []
        for index, action in enumerate(items if isinstance(items, list) else []):
            if not isinstance(action, dict):
                continue
            title = action.get("title") or action.get("action") or "下一步行动"
            values = action.get("items") if isinstance(action.get("items"), list) else []
            if not values and action.get("description"):
                values = [str(action["description"])]
            result.append(
                {
                    "period": action.get("period") or f"阶段 {index + 1}",
                    "title": str(title),
                    "items": [str(item) for item in values if item],
                }
            )
        return result

    @staticmethod
    def _prioritize(items: list[dict], key: str, selected: Optional[str]) -> list[dict]:
        if not selected:
            return list(items)
        return sorted(items, key=lambda item: 0 if item.get(key) == selected else 1)

    @staticmethod
    def _is_missing(value) -> bool:
        return value is None or value == "" or value == []

    @classmethod
    def _backfill_rows(
        cls,
        rows: list[dict],
        fallback_rows: list[dict],
        *,
        identity: str,
        required: tuple[str, ...],
        minimum: int,
    ) -> tuple[list[dict], bool]:
        """Fill incomplete Agent rows without replacing fields it actually produced."""

        fallback = [deepcopy(item) for item in fallback_rows]
        fallback_by_name = {item.get(identity): item for item in fallback}
        result = []
        changed = False
        used = set()

        for index, original in enumerate(rows):
            row = deepcopy(original)
            name = row.get(identity)
            template = fallback_by_name.get(name)
            if template is None and fallback:
                template = fallback[min(index, len(fallback) - 1)]
            for field in required:
                if cls._is_missing(row.get(field)) and template is not None:
                    row[field] = deepcopy(template.get(field))
                    changed = True
            result.append(row)
            used.add(name)

        for template in fallback:
            if len(result) >= minimum:
                break
            if template.get(identity) in used:
                continue
            result.append(deepcopy(template))
            used.add(template.get(identity))
            changed = True

        return result, changed

    async def _latest_answer(self, db: AsyncSession, user_id: int) -> Optional[AgentMessage]:
        result = await db.execute(
            select(AgentMessage)
            .where(
                AgentMessage.user_id == user_id,
                AgentMessage.role == "assistant",
                AgentMessage.message_type == "analysis_result",
            )
            .order_by(desc(AgentMessage.created_at), desc(AgentMessage.id))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_overview(
        self,
        db: AsyncSession,
        user,
        query: CareerOverviewQuery,
    ) -> CareerOverviewResponse:
        profile = await profile_service.get_profile(db, user)
        message = await self._latest_answer(db, user.id)
        metadata = message.metadata_json if message and isinstance(message.metadata_json, dict) else {}
        report = metadata.get("result") if isinstance(metadata.get("result"), dict) else {}
        evidence_rows = metadata.get("evidence") if isinstance(metadata.get("evidence"), list) else []

        directions = self._directions(report.get("directions"))
        skill_gaps = self._skill_gaps(report.get("skill_gaps"))
        cities = self._cities(report.get("cities"))
        next_actions = report.get("next_actions") if isinstance(report.get("next_actions"), list) else []
        plan = self._plan(next_actions)

        fallback_directions = self._prioritize(
            self._directions(CAREER_TEST_DATA["directions"]),
            "title",
            query.direction,
        )
        fallback_cities = self._prioritize(
            self._cities(CAREER_TEST_DATA["cities"]),
            "city",
            query.city,
        )
        directions, directions_changed = self._backfill_rows(
            directions,
            fallback_directions,
            identity="title",
            required=("match", "reason", "tags"),
            minimum=3,
        )
        cities, cities_changed = self._backfill_rows(
            cities,
            fallback_cities,
            identity="city",
            required=("jobs", "salary", "growth", "competition"),
            minimum=3,
        )
        skill_gaps, skills_changed = self._backfill_rows(
            skill_gaps,
            self._skill_gaps(CAREER_TEST_DATA["skills"]),
            identity="name",
            required=("current", "target"),
            minimum=6,
        )
        plan, plan_changed = self._backfill_rows(
            plan,
            self._plan(CAREER_TEST_DATA["plan"]),
            identity="title",
            required=("period", "items"),
            minimum=3,
        )
        directions = self._prioritize(directions, "title", query.direction)
        cities = self._prioritize(cities, "city", query.city)

        sample_size = sum(
            int(self._number(row.get("sample_size")) or 0)
            for row in evidence_rows
            if isinstance(row, dict)
        )
        has_report = bool(message and report)
        missing = []
        synthetic = []
        if not has_report:
            missing.append("career.agent_report")
        if directions_changed:
            missing.append("career.agent_report")
            synthetic.append("career.agent_report")
        if cities_changed:
            missing.append("career.city_comparison")
            synthetic.append("career.city_comparison")
        if skills_changed:
            missing.append("career.skill_gap")
            synthetic.append("career.skill_gap")
        if plan_changed:
            missing.append("career.action_plan")
            synthetic.append("career.action_plan")

        missing = list(dict.fromkeys(missing))
        synthetic = list(dict.fromkeys(synthetic))
        available = ["career.profile"]
        if has_report:
            available.append("career.agent_report")

        return CareerOverviewResponse(
            profile=CareerProfileSummary(
                name=profile.name,
                completion=profile.completion,
                school=profile.school,
                major=profile.major,
                graduation=(f"{profile.graduation_year} {profile.education}".strip()),
            ),
            directions=directions,
            cities=cities,
            skills=skill_gaps,
            plan=plan,
            evidence=CareerEvidence(
                sample_size=sample_size or CAREER_TEST_DATA["evidence"]["sample_size"],
                updated_at=(message.created_at.isoformat() if message and message.created_at else CAREER_TEST_DATA["evidence"]["updated_at"]),
            ),
            data_status=DataStatus(
                source="mixed" if synthetic else ("agent" if has_report else "profile"),
                degraded=bool(missing or synthetic),
                updated_at=(message.created_at if message and message.created_at else datetime.utcnow()),
                available_dimensions=available,
                missing_dimensions=missing,
                synthetic_dimensions=synthetic,
            ),
        )

    async def get_latest_report(self, db: AsyncSession, user_id: int) -> Dict[str, Any]:
        message = await self._latest_answer(db, user_id)
        if message is None:
            return {"status": "not_found", "report": None}
        metadata = message.metadata_json if isinstance(message.metadata_json, dict) else {}
        return {
            "status": "completed",
            "run_id": metadata.get("run_id"),
            "content": message.content,
            "report": metadata.get("result"),
            "created_at": message.created_at,
        }

    async def submit_agent_request(
        self,
        db: AsyncSession,
        user,
        *,
        content: str,
        filters: Dict[str, Any],
        idempotency_key: str,
        title: str,
        message_type: str,
    ) -> CareerSubmissionResponse:
        await crud_agent.acquire_user_admission_lock(db, user_id=user.id)
        existing_run = await crud_agent.get_run_by_user_idempotency_key(
            db,
            user_id=user.id,
            idempotency_key=idempotency_key,
        )
        if existing_run is not None:
            return CareerSubmissionResponse(
                conversation_id=existing_run.conversation_id,
                run_id=existing_run.id,
                status=existing_run.status,
            )

        conversation = await crud_agent.create_conversation(
            db,
            user_id=user.id,
            obj_in=AgentConversationCreate(title=title, context={"filters": filters}),
        )
        from api.v1.endpoints.agent_controller import submit_message

        submission = await submit_message(
            conversation_id=conversation.id,
            obj_in=AgentMessageCreate(
                content=content,
                message_type=message_type,
                context={"filters": filters, "source": "api_v2"},
            ),
            idempotency_key=idempotency_key,
            db=db,
            current_user=user,
        )
        return CareerSubmissionResponse(
            conversation_id=submission["run"].conversation_id,
            run_id=submission["run"].id,
            status=submission["run"].status,
        )

    @staticmethod
    def report_prompt(filters: Dict[str, Any]) -> str:
        return (
            "请根据我的已确认职业资料和真实市场数据，生成完整的职业分析报告，"
            "包括职业方向、城市选择、技能差距和分阶段行动计划。筛选条件："
            + json.dumps(filters, ensure_ascii=False, default=str)
        )


career_service = CareerService()
