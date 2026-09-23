"""管理后台 — 功能开关。"""

from fastapi import APIRouter, Body, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.core.response import ok
from app.db.session import get_db
from app.models import SysUser
from app.schemas.phase2 import FeatureFlagUpdateRequest
from app.services import feature_flag_service

router = APIRouter(prefix="/admin/feature-flags", tags=["admin-feature-flag"])


@router.get("")
async def list_feature_flags(
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(require_admin),
):
    _ = user
    items = await feature_flag_service.list_flags(db)
    return ok({"items": items})


@router.put("/{flagKey}")
async def update_feature_flag(
    flagKey: str = Path(..., min_length=1),
    body: FeatureFlagUpdateRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: SysUser = Depends(require_admin),
):
    data = await feature_flag_service.set_flag(
        db,
        flag_key=flagKey,
        enabled=body.enabled,
        operator_id=user.id,
        remark=body.remark,
    )
    return ok(data)
