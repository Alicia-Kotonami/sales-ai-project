from fastapi import APIRouter

from app.api.v1 import profiles

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(profiles.router)

__all__ = ["api_router"]