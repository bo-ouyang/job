from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_current_user, get_db
from schemas.v2.profile import (
    ProfileCourseInput,
    ProfileCourseResponse,
    ResumeCandidateApply,
    ProfileResponse,
    ProfileSkillInput,
    ProfileSkillResponse,
    ProfileUpdate,
)
from services.v2.profile_service import profile_service


router = APIRouter()


@router.get("", response_model=ProfileResponse)
async def get_profile(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await profile_service.get_profile(db, current_user)


@router.patch("", response_model=ProfileResponse)
async def update_profile(
    payload: ProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await profile_service.update_profile(db, current_user, payload)


@router.post("/resume-candidates", response_model=ProfileResponse)
async def apply_resume_candidates(
    payload: ResumeCandidateApply,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await profile_service.apply_resume_candidates(db, current_user, payload)


@router.get("/courses", response_model=List[ProfileCourseResponse])
async def list_courses(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await profile_service.list_courses(db, current_user.id)


@router.put("/courses", response_model=List[ProfileCourseResponse])
async def replace_courses(
    payload: List[ProfileCourseInput],
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await profile_service.replace_courses(db, current_user.id, payload)


@router.get("/skills", response_model=List[ProfileSkillResponse])
async def list_skills(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await profile_service.list_skills(db, current_user.id)


@router.put("/skills", response_model=List[ProfileSkillResponse])
async def replace_skills(
    payload: List[ProfileSkillInput],
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await profile_service.replace_skills(db, current_user.id, payload)
