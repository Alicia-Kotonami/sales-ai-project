"""管理后台 — 标签接口。"""

from datetime import date

from fastapi import APIRouter, Body, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminActor, require_supervisor_or_admin
from app.core.response import ok
from app.db.session import get_db
from app.schemas.tag import AdminTagCreateRequest, AdminTagSopRequest, AdminTagUpdateRequest
from app.services import admin_tag_service

router = APIRouter(prefix="/admin/tags", tags=["admin-tag"])


@router.post("")
async def admin_create_tag(
    body: AdminTagCreateRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_supervisor_or_admin),
):
    """T4：新建固定关键标签。"""
    data = await admin_tag_service.create_tag(db, actor=actor, body=body)
    return ok(data)


@router.put("/{tagId}")
async def admin_update_tag(
    tagId: int = Path(..., gt=0),
    body: AdminTagUpdateRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_supervisor_or_admin),
):
    """T5：修改标签元数据（不含 SOP 步骤）。"""
    data = await admin_tag_service.update_tag(db, actor=actor, tag_id=tagId, body=body)
    return ok(data)


@router.put("/{tagId}/sop")
async def admin_update_tag_sop(
    tagId: int = Path(..., gt=0),
    body: AdminTagSopRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_supervisor_or_admin),
):
    """T6：绑定 / 更新 SOP（sop_version 自增）。"""
    data = await admin_tag_service.update_tag_sop(
        db, actor=actor, tag_id=tagId, body=body
    )
    return ok(data)


@router.get("/{tagId}/stats")
async def admin_tag_stats(
    tagId: int = Path(..., gt=0),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_supervisor_or_admin),
):
    """T7：标签覆盖 / 来源 / AI 推荐采纳率。"""
    data = await admin_tag_service.tag_stats(
        db, actor=actor, tag_id=tagId, from_date=from_date, to_date=to_date
    )
    return ok(data)
