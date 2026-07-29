from typing import Optional

from fastapi import APIRouter, Query

from services.data_gap_registry import list_data_gaps

router = APIRouter()


@router.get("/data-gaps")
async def read_data_gaps(status: Optional[str] = Query(default=None)):
    return {"items": [gap.to_dict() for gap in list_data_gaps(status=status)]}
