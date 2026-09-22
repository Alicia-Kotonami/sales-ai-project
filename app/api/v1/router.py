from fastapi import APIRouter

from app.api.v1 import auth, profiles, reply, schedule, tags

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(profiles.router)
api_router.include_router(reply.router)
api_router.include_router(tags.router)
api_router.include_router(schedule.router)

__all__ = ["api_router"]