"""API v1 router aggregation. Additional routers (validate, exports) mount in
later build steps (goals.md §13)."""
from fastapi import APIRouter

from app.api.v1.pipeline import router as pipeline_router

router = APIRouter(prefix="/api/v1")
router.include_router(pipeline_router)


@router.get("/")
async def root() -> dict:
    return {"service": "ria", "version": "v2"}
