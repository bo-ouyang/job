from datetime import date
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
from common.databases.models.resume import Education, Resume, WorkExperience
from crud import agent as crud_agent
from schemas.agent_schema import CareerProfileUpdate
from schemas.v2.profile import (
    ProfileCourseInput,
    ProfileCourseResponse,
    ProfileResponse,
    ProfileSkillInput,
    ProfileSkillResponse,
    ProfileUpdate,
    ResumeCandidateApply,
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


def select_new_profile_items(existing: Iterable, candidates: Iterable[ProfileItem]) -> List[ProfileItem]:
    existing_names = {
        getattr(item, "normalized_name", None) or normalize_profile_item_name(item.name)
        for item in existing
    }
    return [
        item
        for item in deduplicate_profile_items(candidates)
        if normalize_profile_item_name(item.name) not in existing_names
    ]


def resume_education_profile_updates(education) -> dict:
    updates = {}
    for source, target in (
        ("school", "school"),
        ("major", "major"),
        ("degree", "education"),
    ):
        value = getattr(education, source, None)
        if value:
            updates[target] = value
    if getattr(education, "end_date", None):
        updates["graduation_year"] = str(education.end_date.year)
    return updates


def _resume_item_signature(item, fields: Sequence[str]) -> tuple:
    return tuple(
        str(getattr(item, field, None) or "").strip().casefold()
        for field in fields
    )


class ProfileService:
    async def _get_or_create_profile(self, db: AsyncSession, user_id: int) -> CareerProfile:
        profile = await crud_agent.get_profile(db, user_id=user_id)
        if profile is None:
            await crud_agent.upsert_profile(
                db,
                user_id=user_id,
                obj_in=CareerProfileUpdate(),
            )
            profile = await crud_agent.get_profile(db, user_id=user_id)
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

    async def apply_resume_candidates(
        self,
        db: AsyncSession,
        user,
        payload: ResumeCandidateApply,
    ) -> ProfileResponse:
        """Atomically merge user-confirmed resume candidates without replacing collections."""
        profile = await self._get_or_create_profile(db, user.id)
        basic = {
            key: value
            for key, value in payload.basic.model_dump(exclude_none=True).items()
            if value not in (None, "")
        }

        resume_result = await db.execute(
            select(Resume)
            .options(
                selectinload(Resume.educations),
                selectinload(Resume.work_experiences),
            )
            .where(Resume.user_id == user.id)
        )
        resume = resume_result.scalar_one_or_none()
        resume_fields = {
            "name",
            "gender",
            "age",
            "phone",
            "email",
            "desired_position",
            "summary",
        }
        if resume is None:
            resume_name = basic.get("name") or getattr(user, "nickname", None) or getattr(user, "username", None)
            if not resume_name:
                raise ValueError("a confirmed resume name is required")
            resume = Resume(
                user_id=user.id,
                name=resume_name,
                **{key: value for key, value in basic.items() if key in resume_fields and key != "name"},
            )
            db.add(resume)
            await db.flush()
            existing_educations = []
            existing_works = []
        else:
            for key, value in basic.items():
                if key in resume_fields:
                    setattr(resume, key, value)
            existing_educations = list(resume.educations or [])
            existing_works = list(resume.work_experiences or [])

        education_keys = {
            _resume_item_signature(item, ("school", "major", "start_date"))
            for item in existing_educations
        }
        created_educations = []
        for candidate in payload.educations:
            key = _resume_item_signature(candidate, ("school", "major", "start_date"))
            if key in education_keys:
                continue
            education_keys.add(key)
            row = Education(**candidate.model_dump(), resume_id=resume.id)
            db.add(row)
            created_educations.append(row)

        work_keys = {
            _resume_item_signature(item, ("company", "position", "start_date"))
            for item in existing_works
        }
        for candidate in payload.work_experiences:
            key = _resume_item_signature(candidate, ("company", "position", "start_date"))
            if key in work_keys:
                continue
            work_keys.add(key)
            db.add(WorkExperience(**candidate.model_dump(), resume_id=resume.id))

        user_fields = {"name": "nickname", "phone": "phone", "email": "email"}
        for source, target in user_fields.items():
            if basic.get(source):
                setattr(user, target, basic[source])

        education_snapshot = dict(profile.education or {})
        if payload.educations:
            primary_education = max(
                payload.educations,
                key=lambda item: (
                    item.end_date is not None,
                    item.end_date or item.start_date or date.min,
                ),
            )
            education_snapshot.update(resume_education_profile_updates(primary_education))

        new_courses = select_new_profile_items(profile.courses, payload.courses)
        for item in new_courses:
            values = item.model_dump()
            values.update(source="resume", confirmation_status="confirmed")
            db.add(
                CareerProfileCourse(
                    profile_id=profile.id,
                    normalized_name=normalize_profile_item_name(item.name),
                    **values,
                )
            )
        if new_courses:
            existing_courses = list(education_snapshot.get("courses") or [])
            education_snapshot["courses"] = existing_courses + [
                item.model_copy(update={"source": "resume", "confirmation_status": "confirmed"}).model_dump(
                    mode="json", by_alias=True
                )
                for item in new_courses
            ]

        new_skills = select_new_profile_items(profile.normalized_skills, payload.skills)
        for item in new_skills:
            values = item.model_dump()
            values.update(source="resume", confirmation_status="confirmed")
            db.add(
                CareerProfileSkill(
                    profile_id=profile.id,
                    normalized_name=normalize_profile_item_name(item.name),
                    **values,
                )
            )
        if new_skills:
            existing_skills = list(profile.skills or [])
            profile.skills = existing_skills + [
                item.model_copy(update={"source": "resume", "confirmation_status": "confirmed"}).model_dump(
                    mode="json", by_alias=True
                )
                for item in new_skills
            ]

        profile.education = education_snapshot
        db.add(
            CareerProfileChangeLog(
                profile_id=profile.id,
                entity_type="resume",
                change_type="apply_candidates",
                source="resume",
                after_data={
                    "basic_fields": sorted(basic),
                    "educations_added": len(created_educations),
                    "courses_added": len(new_courses),
                    "skills_added": len(new_skills),
                },
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
