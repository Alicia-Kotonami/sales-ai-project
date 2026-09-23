"""知识库：上传解析、切分、发布、向量+关键词混合检索。"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import BizError, ErrorCode
from app.models import (
    AdvisorNotification,
    KbBlindSpot,
    KbChunk,
    KbDocument,
    KbPublishLog,
    SysUser,
)
from app.services.audit_service import write_audit
from app.services.event_bus import publish_event
from app.services.vector_store import (
    EMBED_MODEL,
    embed_text,
    get_vector_store,
)

KB_CATEGORIES = ("group_overview", "course_plan", "honor", "faq")
KB_PUBLISHED_STREAM = "stream:kb:published"
STATUS_UPLOADING = 0
STATUS_PARSING = 1
STATUS_READY = 2
STATUS_PUBLISHED = 3
STATUS_ARCHIVED = 4
STATUS_FAILED = 5


def _chunk_text(text: str, *, max_chars: int = 500) -> list[str]:
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not parts:
        parts = [text.strip()] if text.strip() else []
    chunks: list[str] = []
    buf = ""
    for part in parts:
        if len(part) > max_chars:
            if buf:
                chunks.append(buf)
                buf = ""
            for i in range(0, len(part), max_chars):
                chunks.append(part[i : i + max_chars])
            continue
        if buf and len(buf) + 1 + len(part) > max_chars:
            chunks.append(buf)
            buf = part
        else:
            buf = f"{buf}\n{part}".strip() if buf else part
    if buf:
        chunks.append(buf)
    return chunks


def _token_overlap_score(query: str, content: str) -> float:
    q = (query or "").strip().lower()
    c = (content or "").strip().lower()
    if not q or not c:
        return 0.0
    if q in c:
        return 1.0
    q_tokens = set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]{2,}", q))
    if not q_tokens:
        return 0.0
    c_tokens = set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]{2,}", c))
    if not c_tokens:
        return 0.0
    hit = len(q_tokens & c_tokens)
    # 部分中文词互相包含也算命中（如「多少年」vs「八年」靠「年」不够，靠「成立」）
    partial = 0
    for qt in q_tokens:
        if any(qt in ct or ct in qt for ct in c_tokens):
            partial += 1
    score = max(hit, partial) / max(len(q_tokens), 1)
    return round(min(score, 1.0), 4)


async def list_documents(
    db: AsyncSession,
    *,
    category: str | None = None,
    status: int | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    stmt = select(KbDocument).where(KbDocument.is_deleted.is_(False))
    if category:
        stmt = stmt.where(KbDocument.category == category)
    if status is not None:
        stmt = stmt.where(KbDocument.status == status)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            (KbDocument.title.ilike(like)) | (KbDocument.doc_key.ilike(like))
        )

    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = (
        await db.execute(
            stmt.order_by(KbDocument.id.desc())
            .offset(max(page - 1, 0) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    uploader_ids = {r.uploaded_by for r in rows if r.uploaded_by}
    name_map: dict[int, str] = {}
    if uploader_ids:
        users = (
            await db.execute(select(SysUser).where(SysUser.id.in_(uploader_ids)))
        ).scalars().all()
        name_map = {u.id: (u.name or str(u.id)) for u in users}

    return {
        "total": total,
        "items": [
            {
                "id": r.id,
                "docKey": r.doc_key,
                "category": r.category,
                "title": r.title,
                "version": r.version,
                "status": r.status,
                "chunkCount": r.chunk_count,
                "publishedAt": r.published_at.isoformat() if r.published_at else None,
                "effectiveTo": r.effective_to.isoformat() if r.effective_to else None,
                "uploadedByName": name_map.get(r.uploaded_by) if r.uploaded_by else None,
            }
            for r in rows
        ],
    }


async def create_document_from_text(
    db: AsyncSession,
    *,
    operator_id: int,
    category: str,
    title: str,
    content_text: str,
    doc_key: str | None = None,
    file_name: str | None = None,
    mime_type: str | None = None,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
) -> dict:
    if category not in KB_CATEGORIES:
        raise BizError(ErrorCode.PARAM_INVALID, f"非法 category: {category}")
    text = (content_text or "").strip()
    if not text:
        raise BizError(ErrorCode.PARAM_INVALID, "文档内容为空")

    key = doc_key or f"{category}_{uuid.uuid4().hex[:10]}"
    prev = (
        await db.execute(
            select(KbDocument)
            .where(
                KbDocument.doc_key == key,
                KbDocument.is_deleted.is_(False),
            )
            .order_by(KbDocument.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    version = (prev.version + 1) if prev else 1

    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    upload_dir = Path(settings.KB_UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{key}_v{version}.txt"
    file_path = upload_dir / stored_name
    file_path.write_text(text, encoding="utf-8")

    doc = KbDocument(
        category=category,
        title=title,
        file_name=file_name or stored_name,
        file_url=str(file_path),
        file_sha256=sha,
        mime_type=mime_type or "text/plain",
        content_text=text,
        version=version,
        doc_key=key,
        status=STATUS_PARSING,
        uploaded_by=operator_id,
        effective_from=effective_from,
        effective_to=effective_to,
        embedding_model="keyword-v0",
    )
    db.add(doc)
    await db.flush()

    try:
        chunks = _chunk_text(text)
        store = get_vector_store()
        for idx, content in enumerate(chunks):
            chunk = KbChunk(
                document_id=doc.id,
                chunk_index=idx,
                content=content,
                token_count=len(content),
                category=category,
                doc_version=version,
                is_published=False,
                vector_id=None,
            )
            db.add(chunk)
            await db.flush()
            vector_id = f"c{chunk.id}"
            store.upsert(
                vector_id=vector_id,
                embedding=embed_text(content),
                chunk_id=chunk.id,
                document_id=doc.id,
                category=category,
            )
            chunk.vector_id = vector_id
        doc.chunk_count = len(chunks)
        doc.embedding_model = EMBED_MODEL
        doc.status = STATUS_READY
    except Exception as exc:  # noqa: BLE001
        doc.status = STATUS_FAILED
        doc.parse_error = str(exc)[:512]
        await db.commit()
        raise BizError(ErrorCode.KB_PARSE_FAILED, f"解析失败: {exc}") from exc

    await write_audit(
        db,
        actor_id=operator_id,
        action="kb_document.create",
        target_type="kb_document",
        target_id=doc.id,
        payload={"docKey": key, "version": version, "category": category},
    )
    await db.commit()
    await db.refresh(doc)
    return {
        "id": doc.id,
        "status": doc.status,
        "docKey": doc.doc_key,
        "version": doc.version,
        "chunkCount": doc.chunk_count,
        "message": "已解析完成，待发布",
    }


async def get_document(db: AsyncSession, document_id: int) -> dict:
    doc = (
        await db.execute(
            select(KbDocument).where(
                KbDocument.id == document_id,
                KbDocument.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        raise BizError(ErrorCode.NOT_FOUND, "文档不存在")

    chunks = (
        await db.execute(
            select(KbChunk)
            .where(
                KbChunk.document_id == document_id,
                KbChunk.is_deleted.is_(False),
            )
            .order_by(KbChunk.chunk_index.asc())
            .limit(20)
        )
    ).scalars().all()

    return {
        "id": doc.id,
        "docKey": doc.doc_key,
        "category": doc.category,
        "title": doc.title,
        "version": doc.version,
        "status": doc.status,
        "chunkCount": doc.chunk_count,
        "parseError": doc.parse_error,
        "publishedAt": doc.published_at.isoformat() if doc.published_at else None,
        "effectiveFrom": doc.effective_from.isoformat() if doc.effective_from else None,
        "effectiveTo": doc.effective_to.isoformat() if doc.effective_to else None,
        "chunkPreview": [
            {"chunkId": c.id, "chunkIndex": c.chunk_index, "content": c.content[:200]}
            for c in chunks
        ],
    }


async def publish_document(
    db: AsyncSession,
    *,
    document_id: int,
    operator_id: int,
    confirm_price_risk: bool = False,
    remark: str | None = None,
) -> dict:
    doc = (
        await db.execute(
            select(KbDocument).where(
                KbDocument.id == document_id,
                KbDocument.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        raise BizError(ErrorCode.NOT_FOUND, "文档不存在")
    if doc.status != STATUS_READY:
        raise BizError(ErrorCode.KB_NOT_READY, "仅待审核文档可发布")
    if doc.category == "course_plan" and not confirm_price_risk:
        raise BizError(ErrorCode.PARAM_INVALID, "开班计划发布须 confirmPriceRisk=true")

    now = datetime.now(timezone.utc)
    old = (
        await db.execute(
            select(KbDocument).where(
                KbDocument.doc_key == doc.doc_key,
                KbDocument.status == STATUS_PUBLISHED,
                KbDocument.is_deleted.is_(False),
                KbDocument.id != doc.id,
            )
        )
    ).scalar_one_or_none()
    archived_id = None
    if old:
        old.status = STATUS_ARCHIVED
        archived_id = old.id
        await db.execute(
            update(KbChunk)
            .where(KbChunk.document_id == old.id)
            .values(is_published=False)
        )
        get_vector_store().delete_by_document(old.id)

    doc.status = STATUS_PUBLISHED
    doc.published_by = operator_id
    doc.published_at = now
    doc.reviewed_by = operator_id
    await db.execute(
        update(KbChunk)
        .where(KbChunk.document_id == doc.id, KbChunk.is_deleted.is_(False))
        .values(is_published=True)
    )

    db.add(
        KbPublishLog(
            document_id=doc.id,
            doc_key=doc.doc_key,
            from_document_id=archived_id,
            action="publish",
            operator_id=operator_id,
            remark=remark,
            payload_json={"confirmPriceRisk": confirm_price_risk},
        )
    )
    await write_audit(
        db,
        actor_id=operator_id,
        action="kb_document.publish",
        target_type="kb_document",
        target_id=doc.id,
        payload={"docKey": doc.doc_key, "archivedDocumentId": archived_id},
    )

    # 通知：给启用中的顾问各写一条（规模可控时同步）
    advisors = (
        await db.execute(
            select(SysUser.id).where(
                SysUser.is_deleted.is_(False),
                SysUser.status == 1,
            )
        )
    ).scalars().all()
    for uid in advisors:
        db.add(
            AdvisorNotification(
                user_id=uid,
                type="kb_published",
                title=f"知识库已更新：{doc.title}",
                body=f"{doc.category} / v{doc.version} 已生效",
                ref_type="kb_document",
                ref_id=doc.id,
            )
        )

    await db.commit()
    await publish_event(
        KB_PUBLISHED_STREAM,
        {
            "documentId": doc.id,
            "docKey": doc.doc_key,
            "category": doc.category,
            "title": doc.title,
        },
    )
    return {
        "id": doc.id,
        "status": doc.status,
        "publishedAt": now.isoformat(),
        "archivedDocumentId": archived_id,
    }


async def search_published(
    db: AsyncSession,
    *,
    query: str,
    category: str | None = None,
    top_k: int = 5,
) -> list[dict]:
    q = (query or "").strip()
    if not q:
        return []

    # 1) 向量召回
    vector_hits = get_vector_store().search(
        embed_text(q),
        top_k=max(top_k * 4, 12),
        category=category,
    )
    vector_scores = {int(h["chunkId"]): float(h["score"]) for h in vector_hits}

    # 2) 关键词候选（ILIKE + overlap）
    stmt = select(KbChunk, KbDocument).join(
        KbDocument, KbDocument.id == KbChunk.document_id
    ).where(
        KbChunk.is_published.is_(True),
        KbChunk.is_deleted.is_(False),
        KbDocument.is_deleted.is_(False),
        KbDocument.status == STATUS_PUBLISHED,
    )
    if category:
        stmt = stmt.where(KbChunk.category == category)

    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]{2,}", q)
    if tokens:
        like_clauses = [KbChunk.content.ilike(f"%{t}%") for t in tokens[:5]]
        from sqlalchemy import or_

        stmt = stmt.where(or_(*like_clauses))

    # 若向量已召回，也把这些 chunk 拉出来合并
    chunk_ids = list(vector_scores.keys())
    rows = (await db.execute(stmt.limit(200))).all()
    by_id: dict[int, tuple] = {chunk.id: (chunk, doc) for chunk, doc in rows}

    if chunk_ids:
        missing = [cid for cid in chunk_ids if cid not in by_id]
        if missing:
            extra = (
                await db.execute(
                    select(KbChunk, KbDocument)
                    .join(KbDocument, KbDocument.id == KbChunk.document_id)
                    .where(
                        KbChunk.id.in_(missing),
                        KbChunk.is_published.is_(True),
                        KbChunk.is_deleted.is_(False),
                        KbDocument.is_deleted.is_(False),
                        KbDocument.status == STATUS_PUBLISHED,
                    )
                )
            ).all()
            for chunk, doc in extra:
                by_id[chunk.id] = (chunk, doc)

    vw = float(settings.VECTOR_SEARCH_WEIGHT)
    vw = min(max(vw, 0.0), 1.0)
    kw = 1.0 - vw

    scored: list[dict] = []
    for chunk_id, (chunk, doc) in by_id.items():
        keyword_score = _token_overlap_score(q, chunk.content)
        if keyword_score <= 0 and tokens and chunk_id not in vector_scores:
            keyword_score = 0.4
        v_score = vector_scores.get(chunk_id, 0.0)
        if v_score <= 0 and keyword_score <= 0:
            continue
        if v_score > 0 and keyword_score > 0:
            score = round(vw * v_score + kw * keyword_score, 4)
        elif v_score > 0:
            score = round(v_score, 4)
        else:
            score = round(keyword_score, 4)
        scored.append(
            {
                "chunkId": chunk.id,
                "score": score,
                "content": chunk.content,
                "documentId": doc.id,
                "title": doc.title,
                "category": chunk.category,
                "updatedAt": (
                    doc.published_at.isoformat()
                    if doc.published_at
                    else doc.updated_at.isoformat()
                ),
            }
        )
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


async def record_blind_spot(
    db: AsyncSession,
    *,
    question_text: str,
    reason: str,
    advisor_user_id: int | None = None,
    customer_id: int | None = None,
    conversation_id: int | None = None,
    suggestion_event_id: int | None = None,
    top_score: float | None = None,
) -> None:
    db.add(
        KbBlindSpot(
            question_text=question_text,
            reason=reason,
            advisor_user_id=advisor_user_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            suggestion_event_id=suggestion_event_id,
            top_score=top_score,
            status=0,
        )
    )


async def list_blind_spots(
    db: AsyncSession,
    *,
    status: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    stmt = select(KbBlindSpot).where(KbBlindSpot.is_deleted.is_(False))
    if status is not None:
        stmt = stmt.where(KbBlindSpot.status == status)
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = (
        await db.execute(
            stmt.order_by(KbBlindSpot.id.desc())
            .offset(max(page - 1, 0) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return {
        "total": total,
        "items": [
            {
                "id": r.id,
                "questionText": r.question_text,
                "reason": r.reason,
                "topScore": float(r.top_score) if r.top_score is not None else None,
                "status": r.status,
                "createdAt": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


async def update_blind_spot_status(
    db: AsyncSession, *, spot_id: int, status: int
) -> dict:
    row = (
        await db.execute(
            select(KbBlindSpot).where(
                KbBlindSpot.id == spot_id,
                KbBlindSpot.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise BizError(ErrorCode.NOT_FOUND, "盲区记录不存在")
    if status not in (0, 1, 2):
        raise BizError(ErrorCode.PARAM_INVALID, "status 非法")
    row.status = status
    await db.commit()
    return {"id": row.id, "status": row.status}
