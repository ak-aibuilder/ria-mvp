"""MongoDB access (Motor async client).

Ported from v1 (goals.md §6 spirit — production-grade infra reuse). Only change:
v2 config exposes MONGODB_DB_NAME, not v1's MONGODB_DB.
"""
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import get_settings

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncIOMotorClient(settings.MONGODB_URI, serverSelectionTimeoutMS=5000)
    return _client


def get_db() -> AsyncIOMotorDatabase:
    return get_client()[get_settings().MONGODB_DB_NAME]


async def ping() -> bool:
    try:
        await get_client().admin.command("ping")
        return True
    except Exception:
        return False


async def close() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
