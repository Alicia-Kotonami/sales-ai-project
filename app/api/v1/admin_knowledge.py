"""管理后台 — 知识库。"""

from fastapi import APIRouter, Body, Depends, File, Form, Path, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminActor, require_supervisor_or_admin
from app.core.response import ok
from app.db.session import get_db
from app.schemas.phase2 import (
    BlindSpotUpdateRequest,
    KnowledgeCreateTextRequest,
    KnowledgePublishRequest,
    KnowledgeSearchTrialRequest,
)
from app.services import knowledge_service

router = APIRouter(prefix="/admin/knowledge", tags=["admin-knowledge"])


@router.get("/documents")
async def list_documents(
    category: str | None = Query(default=None),
    status: int | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_supervisor_or_admin),
):
    _ = actor
    data = await knowledge_service.list_documents(
        db,
        category=category,
        status=status,
        keyword=keyword,
        page=page,
        page_size=pageSize,
    )
    return ok(data)


@router.post("/documents")
async def create_document_text(
    body: KnowledgeCreateTextRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_supervisor_or_admin),
):
    """JSON 文本创建（便于联调）；文件上传见 /documents/upload。"""
    data = await knowledge_service.create_document_from_text(
        db,
        operator_id=actor.user.id,
        category=body.category,
        title=body.title,
        content_text=body.contentText,
        doc_key=body.docKey,
        effective_from=body.effectiveFrom,
        effective_to=body.effectiveTo,
    )
    return ok(data)


@router.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    category: str = Form(...),
    title: str = Form(...),
    docKey: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_supervisor_or_admin),
):
    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("gbk", errors="ignore")
    data = await knowledge_service.create_document_from_text(
        db,
        operator_id=actor.user.id,
        category=category,
        title=title,
        content_text=text,
        doc_key=docKey,
        file_name=file.filename,
        mime_type=file.content_type,
    )
    return ok(data)


@router.get("/documents/{documentId}")
async def get_document(
    documentId: int = Path(..., gt=0),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_supervisor_or_admin),
):
    _ = actor
    data = await knowledge_service.get_document(db, documentId)
    return ok(data)


@router.post("/documents/{documentId}/publish")
async def publish_document(
    documentId: int = Path(..., gt=0),
    body: KnowledgePublishRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_supervisor_or_admin),
):
    data = await knowledge_service.publish_document(
        db,
        document_id=documentId,
        operator_id=actor.user.id,
        confirm_price_risk=body.confirmPriceRisk,
        remark=body.remark,
    )
    return ok(data)


@router.post("/search/trial")
async def search_trial(
    body: KnowledgeSearchTrialRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_supervisor_or_admin),
):
    _ = actor
    items = await knowledge_service.search_published(
        db, query=body.query, category=body.category, top_k=body.topK
    )
    return ok({"items": items})


@router.get("/blind-spots")
async def list_blind_spots(
    status: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_supervisor_or_admin),
):
    _ = actor
    data = await knowledge_service.list_blind_spots(
        db, status=status, page=page, page_size=pageSize
    )
    return ok(data)


@router.patch("/blind-spots/{spotId}")
async def update_blind_spot(
    spotId: int = Path(..., gt=0),
    body: BlindSpotUpdateRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_supervisor_or_admin),
):
    _ = actor
    data = await knowledge_service.update_blind_spot_status(
        db, spot_id=spotId, status=body.status
    )
    return ok(data)
