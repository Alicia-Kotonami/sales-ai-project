from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer, Profile


@dataclass
class InjectedProfile:
    version: int          # >0 表示真实画像版本；<0 表示草稿 -id；0 表示只用了主档
    sections: dict[str, Any]
    from_draft: bool      # True 表示用了草稿（confidence 下调）


async def load_profile_for_reply(
    db: AsyncSession, customer_id: int
) -> InjectedProfile:
    """
    画像注入优先级（HLD FR-2.3 / API-LLD R1）：
    1. 最新 CONFIRMED/EDITED 画像
    2. 否则最新 DRAFT/PENDING 草稿
    3. 否则客户主档最小上下文（grade/school/name）
    """
    # 1) 生效画像
    stmt = (
        select(Profile)
        .where(
            Profile.customer_id == customer_id,
            Profile.status.in_([2, 3]),
            Profile.is_deleted.is_(False),
        )
        .order_by(Profile.version.desc())
        .limit(1)
    )
    profile = (await db.execute(stmt)).scalar_one_or_none()
    if profile is not None:
        return InjectedProfile(
            version=profile.version,
            sections=profile.sections_json or {},
            from_draft=False,
        )

    # 2) 草稿画像
    stmt = (
        select(Profile)
        .where(
            Profile.customer_id == customer_id,
            Profile.status.in_([0, 1]),
            Profile.is_deleted.is_(False),
        )
        .order_by(Profile.id.desc())
        .limit(1)
    )
    draft = (await db.execute(stmt)).scalar_one_or_none()
    if draft is not None:
        return InjectedProfile(
            version=-draft.id,   # 负数标记草稿
            sections=draft.sections_json or {},
            from_draft=True,
        )

    # 3) 客户主档最小上下文
    stmt = select(Customer).where(
        Customer.id == customer_id, Customer.is_deleted.is_(False)
    )
    customer = (await db.execute(stmt)).scalar_one_or_none()
    if customer is None:
        return InjectedProfile(version=0, sections={}, from_draft=False)

    sections = {
        "basic": {
            "student_name": customer.name_encrypted or "",
            "grade": customer.grade or "",
            "school": customer.school or "",
        }
    }
    return InjectedProfile(version=0, sections=sections, from_draft=False)


def detect_scenario(
    *,
    sections: dict[str, Any],
    has_paid_order: bool,
) -> tuple[list[str], str]:
    """
    客户的细节场景
    返回 (scenarioTags, type)
    - presale / aftersale
    - primary / junior / senior
    - type: "sales" | "service"
    """
    # 售前/售后
    is_after = bool(has_paid_order)
    stage_tag = "presale" if not is_after else "aftersale"

    # 学段
    grade = ((sections.get("basic") or {}).get("grade") or "").upper()
    stage = "primary"
    if grade.startswith("G"):
        try:
            n = int(grade[1:])
            if 7 <= n <= 9:
                stage = "junior"
            elif 10 <= n <= 12:
                stage = "senior"
        except ValueError:
            pass

    scenario_tags = [stage_tag, stage]
    return scenario_tags, ("service" if is_after else "sales")