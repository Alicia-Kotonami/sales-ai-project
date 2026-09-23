"""Agent 可调用能力：对 AI 开放的只读工具。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CustomerTag, Order, Tag
from app.services import knowledge_service
from app.services.profile_injector import load_profile_for_reply

CAPABILITY_CATALOG = [
    {
        "name": "kb_search",
        "description": "检索集团知识库（概况/开班/荣誉/FAQ）",
    },
    {
        "name": "profile_get",
        "description": "查询客户已确认画像与学情信息",
    },
    {
        "name": "order_list",
        "description": "查询客户历史订单与课时信息",
    },
    {
        "name": "tag_list",
        "description": "查询客户当前标签（薄弱科/意向等）",
    },
    {
        "name": "course_plan_search",
        "description": "检索开班计划（知识库 course_plan）",
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def invoke_capability(
    db: AsyncSession,
    *,
    name: str,
    args: dict,
) -> dict:
    if name == "kb_search":
        hits = await knowledge_service.search_published(
            db,
            query=str(args.get("query") or ""),
            category=args.get("category"),
            top_k=int(args.get("topK") or 5),
        )
        return {
            "ok": True,
            "capability": name,
            "data": {"hits": hits},
            "sourceRefs": [
                {
                    "type": "kb_chunk",
                    "refId": str(h["chunkId"]),
                    "label": h.get("title") or "知识库",
                    "updatedAt": h.get("updatedAt"),
                    "excerpt": (h.get("content") or "")[:120],
                }
                for h in hits
            ],
            "fetchedAt": _now_iso(),
        }

    if name == "course_plan_search":
        hits = await knowledge_service.search_published(
            db,
            query=str(args.get("query") or ""),
            category="course_plan",
            top_k=int(args.get("topK") or 5),
        )
        return {
            "ok": True,
            "capability": name,
            "data": {"hits": hits},
            "sourceRefs": [
                {
                    "type": "kb_chunk",
                    "refId": str(h["chunkId"]),
                    "label": f"开班计划：{h.get('title')}",
                    "updatedAt": h.get("updatedAt"),
                    "excerpt": (h.get("content") or "")[:120],
                }
                for h in hits
            ],
            "fetchedAt": _now_iso(),
        }

    if name == "profile_get":
        customer_id = int(args["customerId"])
        injected = await load_profile_for_reply(db, customer_id)
        return {
            "ok": True,
            "capability": name,
            "data": {
                "profileVersion": injected.version,
                "sections": injected.sections,
                "updatedAt": _now_iso(),
            },
            "sourceRefs": [
                {
                    "type": "profile",
                    "refId": str(customer_id),
                    "label": f"客户画像 v{injected.version}",
                    "updatedAt": _now_iso(),
                }
            ],
            "fetchedAt": _now_iso(),
        }

    if name == "order_list":
        customer_id = int(args["customerId"])
        limit = int(args.get("limit") or 20)
        rows = (
            await db.execute(
                select(Order)
                .where(
                    Order.customer_id == customer_id,
                    Order.is_deleted.is_(False),
                )
                .order_by(Order.id.desc())
                .limit(limit)
            )
        ).scalars().all()
        orders = [
            {
                "orderId": o.id,
                "productName": o.product_name,
                "amount": float(o.amount) if o.amount is not None else None,
                "status": o.status,
                "paidAt": o.paid_at.isoformat() if o.paid_at else None,
            }
            for o in rows
        ]
        return {
            "ok": True,
            "capability": name,
            "data": {"orders": orders},
            "sourceRefs": [
                {
                    "type": "order",
                    "refId": str(o["orderId"]),
                    "label": o.get("productName") or "订单",
                    "updatedAt": o.get("paidAt"),
                }
                for o in orders
            ],
            "fetchedAt": _now_iso(),
        }

    if name == "tag_list":
        customer_id = int(args["customerId"])
        rows = (
            await db.execute(
                select(CustomerTag, Tag)
                .join(Tag, Tag.id == CustomerTag.tag_id)
                .where(
                    CustomerTag.customer_id == customer_id,
                    CustomerTag.is_deleted.is_(False),
                    Tag.is_deleted.is_(False),
                    CustomerTag.status.in_([0, 1]),
                )
            )
        ).all()
        tags = [
            {
                "tagId": tag.id,
                "code": tag.code,
                "name": tag.name,
                "updatedAt": ct.updated_at.isoformat() if ct.updated_at else None,
                "confidence": float(ct.confidence) if ct.confidence is not None else None,
            }
            for ct, tag in rows
        ]
        return {
            "ok": True,
            "capability": name,
            "data": {"tags": tags},
            "sourceRefs": [
                {
                    "type": "tag",
                    "refId": str(t["tagId"]),
                    "label": t["name"],
                    "updatedAt": t.get("updatedAt"),
                }
                for t in tags
            ],
            "fetchedAt": _now_iso(),
        }

    return {
        "ok": False,
        "capability": name,
        "data": {},
        "sourceRefs": [],
        "fetchedAt": _now_iso(),
        "error": f"unknown capability: {name}",
    }
