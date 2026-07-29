from typing import Iterable, List, Sequence, TypeVar

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from common.databases.models.career_profile import (
    CareerProfile,
    CareerProfileChangeLog,
    CareerProfileCourse,
    CareerProfileSkill,
)
from common.databases.models.resume import Resume
from crud import agent as crud_agent
from schemas.agent_schema import CareerProfileUpdate
from schemas.v2.profile import (
    ProfileCourseInput,
    ProfileCourseResponse,
    ProfileResponse,
    ProfileSkillInput,
    ProfileSkillResponse,
    ProfileUpdate,
)


ProfileItem = TypeVar("ProfileItem", ProfileCourseInput, ProfileSkillInput)


def normalize_profile_item_name(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def deduplicate_profile_items(items: Iterable[ProfileItem]) -> List[ProfileItem]:
    order: List[str] = []
    by_name = {}
    for item in items:
        normalized_name = normalize_profile_item_name(item.name)
        if normalized_name not in by_name:
            order.append(normalized_name)
        by_name[normalized_name] = item.model_copy(update={"name": item.name.strip()})
    return [by_name[name] for name in order]


class ProfileService:
    async def _get_or_create_profile(self, db: AsyncSession, user_id: int) -> CareerProfile:
        profile = await crud_agent.get_profile(db, user_id=user_id)
        if profile is None:
            profile = await crud_agent.upsert_profile(
                db,
                user_id=user_id,
                obj_in=CareerProfileUpdate(),
            )
        return profile

    async def get_profile(self, db: AsyncSession, user) -> ProfileResponse:
        profile = await self._get_or_create_profile(db, user.id)
        resume_result = await db.execute(
            select(Resume)
            .options(selectinload(Resume.educations))
            .where(Resume.user_id == user.id)
        )
        resume = resume_result.scalar_one_or_none()
        education_data = profile.education if isinstance(profile.education, dict) else {}
        preferences = profile.preferences if isinstance(profile.preferences, dict) else {}
        resume_education = None
        if resume and resume.educations:
            resume_education = sorted(
                resume.educations,
                key=lambda item: (item.end_date is not None, item.end_date),
                reverse=True,
            )[0]

        values = {
            "name": (getattr(user, "nickname", None) or getattr(user, "username", None) or (resume.name if resume else None) or ""),
            "phone": getattr(user, "phone", None) or (resume.phone if resume else None) or "",
            "email": getattr(user, "email", None) or (resume.email if resume else None) or "",
            "city": getattr(user, "location", None) or "",
            "school": education_data.get("school") or (resume_education.school if resume_education else ""),
            "school_level": education_data.get("school_level") or "",
            "education": education_data.get("education") or (resume_education.degree if resume_education else ""),
            "major": education_data.get("major") or (resume_education.major if resume_education else ""),
            "graduation_year": education_data.get("graduation_year") or (
                str(resume_education.end_date.year)
                if resume_education and resume_education.end_date
                else ""
            ),
            "gpa": education_data.get("gpa") or "",
            "target_cities": list(preferences.get("target_cities") or []),
            "target_roles": list(preferences.get("target_roles") or []),
            "target_industries": list(preferences.get("target_industries") or []),
            "expected_salary": preferences.get("expected_salary") or "",
        }
        completion_fields = (
            "name",
            "city",
            "school",
            "education",
            "major",
            "graduation_year",
            "target_cities",
            "target_roles",
            "target_industries",
            "expected_salary",
        )
        completed = sum(bool(values[field]) for field in completion_fields)
        values["completion"] = round(completed / len(completion_fields) * 100)
        return ProfileResponse(**values)

    async def update_profile(
        self,
        db: AsyncSession,
        user,
        payload: ProfileUpdate,
    ) -> ProfileResponse:
        profile = await self._get_or_create_profile(db, user.id)
        changes = payload.model_dump(exclude_unset=True)
        before_data = {
            "education": profile.education,
            "preferences": profile.preferences,
        }

        user_fields = {"name": "nickname", "phone": "phone", "email": "email", "city": "location"}
        for input_field, model_field in user_fields.items():
            if input_field in changes:
                setattr(user, model_field, changes[input_field] or "")

        education = dict(profile.education or {})
        for field in ("school", "school_level", "education", "major", "graduation_year", "gpa"):
            if field in changes:
                education[field] = changes[field]
        preferences = dict(profile.preferences or {})
        for field in ("target_cities", "target_roles", "target_industries", "expected_salary"):
            if field in changes:
                preferences[field] = changes[field]

        profile.education = education
        profile.preferences = preferences
        db.add(user)
        db.add(profile)
        db.add(
            CareerProfileChangeLog(
                profile_id=profile.id,
                entity_type="profile",
                entity_id=profile.id,
                change_type="update",
                source="manual",
                before_data=before_data,
                after_data={"education": education, "preferences": preferences, "fields": changes},
                review_status="accepted",
            )
        )
        await db.flush()
        return await self.get_profile(db, user)

    async def list_courses(self, db: AsyncSession, user_id: int) -> List[ProfileCourseResponse]:
        profile = await self._get_or_create_profile(db, user_id)
        result = await db.execute(
            select(CareerProfileCourse)
            .where(CareerProfileCourse.profile_id == profile.id)
            .order_by(CareerProfileCourse.created_at, CareerProfileCourse.id)
        )
        return [ProfileCourseResponse.model_validate(item) for item in result.scalars().all()]

    async def replace_courses(
        self,
        db: AsyncSession,
        user_id: int,
        items: Sequence[ProfileCourseInput],
    ) -> List[ProfileCourseResponse]:
        profile = await self._get_or_create_profile(db, user_id)
        before = await self.list_courses(db, user_id)
        normalized_items = deduplicate_profile_items(items)
        await db.execute(delete(CareerProfileCourse).where(CareerProfileCourse.profile_id == profile.id))
        created = []
        for item in normalized_items:
            row = CareerProfileCourse(
                profile_id=profile.id,
                normalized_name=normalize_profile_item_name(item.name),
                **item.model_dump(),
            )
            db.add(row)
            created.append(row)
        await db.flush()
        education = dict(profile.education or {})
        education["courses"] = [item.model_dump(mode="json", by_alias=True) for item in normalized_items]
        profile.education = education
        db.add(profile)
        db.add(
            CareerProfileChangeLog(
                profile_id=profile.id,
                entity_type="course",
                change_type="replace_collection",
                source="manual",
                before_data={"items": [item.model_dump(mode="json") for item in before]},
                after_data={"items": [item.model_dump(mode="json", by_alias=True) for item in normalized_items]},
                review_status="accepted",
            )
        )
        await db.flush()
        return [ProfileCourseResponse.model_validate(item) for item in created]

    async def list_skills(self, db: AsyncSession, user_id: int) -> List[ProfileSkillResponse]:
        profile = await self._get_or_create_profile(db, user_id)
        result = await db.execute(
            select(CareerProfileSkill)
            .where(CareerProfileSkill.profile_id == profile.id)
            .order_by(CareerProfileSkill.created_at, CareerProfileSkill.id)
        )
        return [ProfileSkillResponse.model_validate(item) for item in result.scalars().all()]

    async def replace_skills(
        self,
        db: AsyncSession,
        user_id: int,
        items: Sequence[ProfileSkillInput],
    ) -> List[ProfileSkillResponse]:
        profile = await self._get_or_create_profile(db, user_id)
        before = await self.list_skills(db, user_id)
        normalized_items = deduplicate_profile_items(items)
        await db.execute(delete(CareerProfileSkill).where(CareerProfileSkill.profile_id == profile.id))
        created = []
        for item in normalized_items:
            row = CareerProfileSkill(
                profile_id=profile.id,
                normalized_name=normalize_profile_item_name(item.name),
                **item.model_dump(),
            )
            db.add(row)
            created.append(row)
        await db.flush()
        profile.skills = [item.model_dump(mode="json", by_alias=True) for item in normalized_items]
        db.add(profile)
        db.add(
            CareerProfileChangeLog(
                profile_id=profile.id,
                entity_type="skill",
                change_type="replace_collection",
                source="manual",
                before_data={"items": [item.model_dump(mode="json") for item in before]},
                after_data={"items": profile.skills},
                review_status="accepted",
            )
        )
        await db.flush()
        return [ProfileSkillResponse.model_validate(item) for item in created]


profile_service = ProfileService()
