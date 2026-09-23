from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.post("/v1/tags/recommend")
async def tags_recommend(body: dict):
    """标签推荐桩：从 catalog 挑一个未选中的标签。"""
    catalog = body.get("catalog") or []
    selected = set(body.get("selectedTagIds") or [])
    recs = []
    for item in catalog:
        if not isinstance(item, dict):
            continue
        tag_id = item.get("tagId")
        if tag_id is None or tag_id in selected:
            continue
        recs.append(
            {
                "action": "check",
                "tagId": tag_id,
                "reason": "ai_runtime 目录内推荐（桩）",
                "confidence": 0.8,
                "evidenceRefs": ["profile:basic"],
            }
        )
        break
    return {"recommendations": recs}
