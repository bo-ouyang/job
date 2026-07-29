import json
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
        plan = []
        for index, action in enumerate(next_actions):
            if not isinstance(action, dict):
                continue
            title = action.get("title") or action.get("action") or "下一步行动"
            items = action.get("items") if isinstance(action.get("items"), list) else []
            if not items and action.get("description"):
                items = [str(action["description"])]
            plan.append({"period": action.get("period") or f"阶段 {index + 1}", "title": title, "items": items})

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
        if not directions:
            directions = self._directions(CAREER_TEST_DATA["directions"])
            synthetic.append("career.agent_report")
        if not cities:
            missing.append("career.city_comparison")
            cities = self._cities(CAREER_TEST_DATA["cities"])
            synthetic.append("career.city_comparison")
        if not skill_gaps:
            missing.append("career.skill_gap")
            skill_gaps = self._skill_gaps(CAREER_TEST_DATA["skills"])
            synthetic.append("career.skill_gap")
        if not plan:
            missing.append("career.action_plan")
            plan = CAREER_TEST_DATA["plan"]
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
