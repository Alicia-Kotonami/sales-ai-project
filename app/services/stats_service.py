from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AdoptionDailyStat,
    ScheduleTask,
    SuggestionEvent,
    SysUser,
)

CN_TZ = timezone(timedelta(hours=8))


# ============ 日聚合：suggestion_event -> adoption_daily_stat ============

async def aggregate_adoption_for_day(db: AsyncSession, stat_date: date) -> int:
    """
    把某天（按 +08:00）的 suggestion_event 聚合进 adoption_daily_stat。
    - suggest_cnt 只计 exposed_at IS NOT NULL
    - adopt_cnt = action=1，edit_cnt = action=3，reject_cnt = action=2，ignore_cnt = action=4
    - adopt_rate = (adopt_cnt + edit_cnt) / suggest_cnt
    返回写入的顾问行数。
    """
    start = datetime(stat_date.year, stat_date.month, stat_date.day, tzinfo=CN_TZ)
    end = start + timedelta(days=1)

    # 1) 分母：按 advisor 聚合曝光数
    stmt = (
        select(
            SuggestionEvent.advisor_user_id.label("advisor_id"),
            func.count(SuggestionEvent.id).label("suggest_cnt"),
            func.count().filter(SuggestionEvent.action == 1).label("adopt_cnt"),
            func.count().filter(SuggestionEvent.action == 3).label("edit_cnt"),
            func.count().filter(SuggestionEvent.action == 2).label("reject_cnt"),
            func.count().filter(SuggestionEvent.action == 4).label("ignore_cnt"),
        )
        .where(
            SuggestionEvent.exposed_at.is_not(None),
            SuggestionEvent.exposed_at >= start,
            SuggestionEvent.exposed_at < end,
            SuggestionEvent.is_deleted.is_(False),
            SuggestionEvent.advisor_user_id.is_not(None),
        )
        .group_by(SuggestionEvent.advisor_user_id)
    )
    rows = (await db.execute(stmt)).all()

    # 2) 删除当日旧记录（幂等重跑）
    existing = await db.execute(
        select(AdoptionDailyStat).where(AdoptionDailyStat.stat_date == stat_date)
    )
    for r in existing.scalars().all():
        await db.delete(r)
    await db.flush()

    # 3) 写入新记录
    written = 0
    for r in rows:
        suggest_cnt = int(r.suggest_cnt or 0)
        adopt_cnt = int(r.adopt_cnt or 0)
        edit_cnt = int(r.edit_cnt or 0)
        adopt_rate = (
            Decimal(str(round((adopt_cnt + edit_cnt) * 100 / suggest_cnt, 2)))
            if suggest_cnt
            else Decimal("0.00")
        )
        db.add(
            AdoptionDailyStat(
                stat_date=stat_date,
                advisor_user_id=r.advisor_id,
                suggest_cnt=suggest_cnt,
                adopt_cnt=adopt_cnt,
                edit_cnt=edit_cnt,
                reject_cnt=int(r.reject_cnt or 0),
                ignore_cnt=int(r.ignore_cnt or 0),
                adopt_rate=adopt_rate,
                converted_cnt=0,
            )
        )
        written += 1

    return written


# ============ A9 查询：优先读聚合表，缺失回源 ============

async def get_adoption_rate(
    db: AsyncSession,
    *,
    from_date: date,
    to_date: date,
    region_id: int | None = None,
) -> dict:
    """
    返回：
    {
      overall: {exposedCnt, adoptCnt, editCnt, adoptRate},
      byAdvisor: [{advisorId, nameMasked, adoptRate, trend, flag}],
      extras: {...}  # 本步先留空
    }
    主管传 region_id 会过滤顾问范围。
    """
    # 1) 先尝试从聚合表读
    agg_stmt = (
        select(
            AdoptionDailyStat.advisor_user_id,
            func.sum(AdoptionDailyStat.suggest_cnt).label("suggest_cnt"),
            func.sum(AdoptionDailyStat.adopt_cnt).label("adopt_cnt"),
            func.sum(AdoptionDailyStat.edit_cnt).label("edit_cnt"),
            func.sum(AdoptionDailyStat.reject_cnt).label("reject_cnt"),
            func.sum(AdoptionDailyStat.ignore_cnt).label("ignore_cnt"),
        )
        .where(
            AdoptionDailyStat.stat_date >= from_date,
            AdoptionDailyStat.stat_date <= to_date,
            AdoptionDailyStat.is_deleted.is_(False),
        )
        .group_by(AdoptionDailyStat.advisor_user_id)
    )
    agg_rows = (await db.execute(agg_stmt)).all()

    if not agg_rows:
        # 2) 回源 suggestion_event
        start = datetime(from_date.year, from_date.month, from_date.day, tzinfo=CN_TZ)
        end = datetime(to_date.year, to_date.month, to_date.day, tzinfo=CN_TZ) + timedelta(days=1)
        raw_stmt = (
            select(
                SuggestionEvent.advisor_user_id,
                func.count(SuggestionEvent.id).label("suggest_cnt"),
                func.count().filter(SuggestionEvent.action == 1).label("adopt_cnt"),
                func.count().filter(SuggestionEvent.action == 3).label("edit_cnt"),
                func.count().filter(SuggestionEvent.action == 2).label("reject_cnt"),
                func.count().filter(SuggestionEvent.action == 4).label("ignore_cnt"),
            )
            .where(
                SuggestionEvent.exposed_at.is_not(None),
                SuggestionEvent.exposed_at >= start,
                SuggestionEvent.exposed_at < end,
                SuggestionEvent.is_deleted.is_(False),
                SuggestionEvent.advisor_user_id.is_not(None),
            )
            .group_by(SuggestionEvent.advisor_user_id)
        )
        agg_rows = (await db.execute(raw_stmt)).all()

    # 3) 载入顾问信息（用于脱敏 + 按 region 过滤）
    advisor_ids = [r.advisor_user_id for r in agg_rows]
    advisors: dict[int, SysUser] = {}
    if advisor_ids:
        a_stmt = select(SysUser).where(SysUser.id.in_(advisor_ids))
        for a in (await db.execute(a_stmt)).scalars().all():
            advisors[a.id] = a

    def _mask(raw: str | None) -> str:
        return (raw[0] + "*") if raw else ""

    total_exposed = total_adopt = total_edit = 0
    by_advisor: list[dict] = []
    per_advisor_exposed: dict[int, int] = {}
    per_advisor_used: dict[int, int] = defaultdict(int)

    for r in agg_rows:
        advisor = advisors.get(r.advisor_user_id)
        if advisor is None:
            continue
        if region_id is not None and advisor.region_id != region_id:
            continue

        suggest_cnt = int(r.suggest_cnt or 0)
        adopt_cnt = int(r.adopt_cnt or 0)
        edit_cnt = int(r.edit_cnt or 0)
        rate = (
            round((adopt_cnt + edit_cnt) * 100 / suggest_cnt, 2)
            if suggest_cnt
            else 0.0
        )

        total_exposed += suggest_cnt
        total_adopt += adopt_cnt
        total_edit += edit_cnt

        per_advisor_exposed[advisor.id] = suggest_cnt
        per_advisor_used[advisor.id] = adopt_cnt + edit_cnt

        by_advisor.append({
            "advisorId": advisor.id,
            "name": _mask(advisor.name),
            "adoptRate": rate,
            "trend": "flat",  # 本步先固定
            "flag": "",       # 本步先占位，下方统一判
        })

    # 4) 从不采纳告警：需要最近 7 个工作日窗口（用 stat_date >= to_date-6 近似）
    if by_advisor:
        week_start = to_date - timedelta(days=6)
        week_stmt = (
            select(
                AdoptionDailyStat.advisor_user_id,
                func.sum(AdoptionDailyStat.suggest_cnt).label("suggest_cnt"),
                func.sum(AdoptionDailyStat.adopt_cnt).label("adopt_cnt"),
                func.sum(AdoptionDailyStat.edit_cnt).label("edit_cnt"),
            )
            .where(
                AdoptionDailyStat.stat_date >= week_start,
                AdoptionDailyStat.stat_date <= to_date,
                AdoptionDailyStat.is_deleted.is_(False),
            )
            .group_by(AdoptionDailyStat.advisor_user_id)
        )
        week_rows = (await db.execute(week_stmt)).all()
        week_map = {r.advisor_user_id: r for r in week_rows}
        for item in by_advisor:
            wr = week_map.get(item["advisorId"])
            if wr is None:
                continue
            sc = int(wr.suggest_cnt or 0)
            ac = int(wr.adopt_cnt or 0)
            ec = int(wr.edit_cnt or 0)
            if sc < 20 * 5:  # 日均曝光 >= 20，7 天则 >= 140
                continue
            rate = (ac + ec) * 100 / sc if sc else 0
            if rate < 10:
                item["flag"] = "NEVER_ADOPT_ALERT"

    overall_rate = (
        round((total_adopt + total_edit) * 100 / total_exposed, 2)
        if total_exposed
        else 0.0
    )

    return {
        "dateRange": f"{from_date.isoformat()}~{to_date.isoformat()}",
        "overall": {
            "exposedCnt": total_exposed,
            "adoptCnt": total_adopt,
            "editCnt": total_edit,
            "adoptRate": overall_rate,
        },
        "byAdvisor": by_advisor,
        "extras": {
            "profileConfirmRate": None,
            "tagConfirmRate": None,
            "scheduleConfirmRate": None,
        },
        "metricDefinition": "使用率 = (原样采纳 + 采纳后编辑) / 侧边栏实际曝光次数",
    }


def _month_range(from_date: date | None, to_date: date | None) -> tuple[date, date]:
    today = date.today()
    if to_date is None:
        to_date = today
    if from_date is None:
        from_date = date(to_date.year, to_date.month, 1)
    return from_date, to_date


def _bounds(from_date: date, to_date: date) -> tuple[datetime, datetime]:
    start = datetime(from_date.year, from_date.month, from_date.day, tzinfo=CN_TZ)
    end = datetime(to_date.year, to_date.month, to_date.day, tzinfo=CN_TZ) + timedelta(days=1)
    return start, end


async def get_funnel(
    db: AsyncSession,
    *,
    from_date: date,
    to_date: date,
    region_id: int | None,
) -> dict:
    from app.models import Customer, Conversation, Order, ScheduleTask

    start, end = _bounds(from_date, to_date)

    lead_stmt = select(func.count()).select_from(Customer).where(
        Customer.is_deleted.is_(False),
        Customer.created_at >= start,
        Customer.created_at < end,
    )
    if region_id is not None:
        lead_stmt = lead_stmt.where(Customer.region_id == region_id)
    leads = int((await db.execute(lead_stmt)).scalar() or 0)

    first_conv = (
        select(
            Conversation.customer_id.label("cid"),
            func.min(func.coalesce(Conversation.started_at, Conversation.created_at)).label("first_at"),
        )
        .where(Conversation.is_deleted.is_(False), Conversation.customer_id.is_not(None))
        .group_by(Conversation.customer_id)
        .subquery()
    )
    consult_stmt = (
        select(func.count())
        .select_from(first_conv)
        .join(Customer, Customer.id == first_conv.c.cid)
        .where(
            Customer.is_deleted.is_(False),
            first_conv.c.first_at >= start,
            first_conv.c.first_at < end,
        )
    )
    if region_id is not None:
        consult_stmt = consult_stmt.where(Customer.region_id == region_id)
    consults = int((await db.execute(consult_stmt)).scalar() or 0)

    trial_stmt = (
        select(func.count(func.distinct(ScheduleTask.customer_id)))
        .join(Customer, Customer.id == ScheduleTask.customer_id)
        .where(
            ScheduleTask.type == 1,
            ScheduleTask.status == 2,
            ScheduleTask.is_deleted.is_(False),
            Customer.is_deleted.is_(False),
            ScheduleTask.updated_at >= start,
            ScheduleTask.updated_at < end,
        )
    )
    if region_id is not None:
        trial_stmt = trial_stmt.where(Customer.region_id == region_id)
    trials = int((await db.execute(trial_stmt)).scalar() or 0)

    deal_stmt = (
        select(func.count(func.distinct(Order.customer_id)))
        .join(Customer, Customer.id == Order.customer_id)
        .where(
            Order.status.in_((1, 3)),
            Order.paid_at.is_not(None),
            Order.paid_at >= start,
            Order.paid_at < end,
            Order.is_deleted.is_(False),
            Customer.is_deleted.is_(False),
        )
    )
    if region_id is not None:
        deal_stmt = deal_stmt.where(Customer.region_id == region_id)
    deals = int((await db.execute(deal_stmt)).scalar() or 0)

    names = ["线索", "首咨", "试听", "成交"]
    cnts = [leads, consults, trials, deals]
    steps = []
    for i, (name, cnt) in enumerate(zip(names, cnts)):
        prev = cnts[i - 1] if i else None
        if i == 0:
            rate = 100.0
        elif not prev:
            rate = 0.0
        else:
            rate = round(cnt * 100 / prev, 2)
        steps.append({"name": name, "cnt": cnt, "rate": rate})

    return {
        "dateRange": f"{from_date.isoformat()}~{to_date.isoformat()}",
        "steps": steps,
    }


async def get_renewal_rate(
    db: AsyncSession,
    *,
    from_date: date,
    to_date: date,
    region_id: int | None,
) -> dict:
    from app.models import Customer, Order

    start, end = _bounds(from_date, to_date)
    expire_stmt = (
        select(Order.customer_id, Order.id, Order.expire_at)
        .join(Customer, Customer.id == Order.customer_id)
        .where(
            Order.status.in_((1, 3)),
            Order.expire_at >= start,
            Order.expire_at < end,
            Order.is_deleted.is_(False),
            Customer.is_deleted.is_(False),
            Order.customer_id.is_not(None),
        )
    )
    if region_id is not None:
        expire_stmt = expire_stmt.where(Customer.region_id == region_id)
    expired = (await db.execute(expire_stmt)).all()
    expire_customers = {r.customer_id for r in expired}

    renewed: set[int] = set()
    if expired:
        for row in expired:
            window_end = row.expire_at + timedelta(days=30)
            found = (
                await db.execute(
                    select(Order.id).where(
                        Order.customer_id == row.customer_id,
                        Order.id != row.id,
                        Order.status.in_((1, 3)),
                        Order.paid_at.is_not(None),
                        Order.paid_at > row.expire_at,
                        Order.paid_at <= window_end,
                        Order.is_deleted.is_(False),
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if found is not None:
                renewed.add(row.customer_id)

    expire_cnt = len(expire_customers)
    renewed_cnt = len(renewed)
    rate = round(renewed_cnt * 100 / expire_cnt, 2) if expire_cnt else 0.0
    return {
        "expireCnt": expire_cnt,
        "renewedCnt": renewed_cnt,
        "renewalRate": rate,
    }


async def get_advisor_efficiency(
    db: AsyncSession,
    *,
    from_date: date,
    to_date: date,
    region_id: int | None,
) -> dict:
    from app.models import Conversation, Customer, Order, SysRole, SysUser

    start, end = _bounds(from_date, to_date)

    advisor_stmt = (
        select(SysUser)
        .join(SysRole, SysRole.id == SysUser.role_id)
        .where(
            SysUser.is_deleted.is_(False),
            SysUser.status == 1,
            SysRole.code == "advisor",
        )
    )
    if region_id is not None:
        advisor_stmt = advisor_stmt.where(SysUser.region_id == region_id)
    advisors = (await db.execute(advisor_stmt)).scalars().all()

    conv_stmt = (
        select(Conversation.advisor_user_id, func.count(Conversation.id))
        .where(
            Conversation.is_deleted.is_(False),
            Conversation.advisor_user_id.is_not(None),
            func.coalesce(Conversation.started_at, Conversation.created_at) >= start,
            func.coalesce(Conversation.started_at, Conversation.created_at) < end,
        )
        .group_by(Conversation.advisor_user_id)
    )
    conv_map = {r[0]: int(r[1] or 0) for r in (await db.execute(conv_stmt)).all()}

    cust_stmt = (
        select(Customer.owner_user_id, func.count(Customer.id))
        .where(Customer.is_deleted.is_(False), Customer.owner_user_id.is_not(None))
        .group_by(Customer.owner_user_id)
    )
    cust_map = {r[0]: int(r[1] or 0) for r in (await db.execute(cust_stmt)).all()}

    deal_stmt = (
        select(
            Customer.owner_user_id,
            func.count(Order.id),
            func.coalesce(func.sum(Order.amount), 0),
        )
        .join(Customer, Customer.id == Order.customer_id)
        .where(
            Order.status.in_((1, 3)),
            Order.paid_at.is_not(None),
            Order.paid_at >= start,
            Order.paid_at < end,
            Order.is_deleted.is_(False),
            Customer.is_deleted.is_(False),
        )
        .group_by(Customer.owner_user_id)
    )
    deal_map: dict[int, tuple[int, float]] = {}
    for owner_id, cnt, amount in (await db.execute(deal_stmt)).all():
        deal_map[owner_id] = (int(cnt or 0), float(amount or 0))

    def _mask(raw: str | None) -> str:
        return (raw[0] + "*") if raw else ""

    by_advisor = []
    for a in advisors:
        deal_cnt, amount = deal_map.get(a.id, (0, 0.0))
        by_advisor.append(
            {
                "advisorId": a.id,
                "nameMasked": _mask(a.name),
                "convCnt": conv_map.get(a.id, 0),
                "dealCnt": deal_cnt,
                "amount": round(amount, 2),
                "customers": cust_map.get(a.id, 0),
            }
        )

    return {
        "dateRange": f"{from_date.isoformat()}~{to_date.isoformat()}",
        "byAdvisor": by_advisor,
    }