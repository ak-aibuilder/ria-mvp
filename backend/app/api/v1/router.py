"""API v1 router aggregation (goals.md §13)."""
from fastapi import APIRouter

from app.api.v1.exports import router as exports_router
from app.api.v1.pipeline import router as pipeline_router
from app.api.v1.validate import router as validate_router

router = APIRouter(prefix="/api/v1")
router.include_router(pipeline_router)
router.include_router(validate_router)
router.include_router(exports_router)


@router.get("/")
async def root() -> dict:
    return {"service": "ria", "version": "v2"}
