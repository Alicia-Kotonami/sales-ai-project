from fastapi import APIRouter

from app.api.v1 import (
    admin_customers,
    admin_dashboard,
    admin_feature_flags,
    admin_knowledge,
    admin_orders,
    admin_tags,
    admin_users,
    auth,
    profiles,
    reply,
    schedule,
    tags,
    users,
    wecom,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(wecom.router)
api_router.include_router(profiles.router)
api_router.include_router(reply.router)
api_router.include_router(tags.router)
api_router.include_router(schedule.router)
api_router.include_router(users.router)
api_router.include_router(admin_dashboard.router)
api_router.include_router(admin_customers.router)
api_router.include_router(admin_users.router)
api_router.include_router(admin_orders.router)
api_router.include_router(admin_tags.router)
api_router.include_router(admin_feature_flags.router)
api_router.include_router(admin_knowledge.router)

__all__ = ["api_router"]
