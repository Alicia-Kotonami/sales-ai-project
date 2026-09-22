"""
手动跑批：把某天的 suggestion_event 聚合进 adoption_daily_stat。
用法（项目根目录，激活 conda 环境）：
    python -m scripts.run_adoption_daily_stat            # 聚合昨天
    python -m scripts.run_adoption_daily_stat 2026-09-21 # 聚合指定日期
"""
import asyncio
import sys
from datetime import date, timedelta

from app.db.session import AsyncSessionLocal
from app.services.stats_service import aggregate_adoption_for_day


async def main(target: date) -> None:
    async with AsyncSessionLocal() as db:
        written = await aggregate_adoption_for_day(db, target)
        await db.commit()
    print(f"[OK] {target} adoption_daily_stat 已写入 {written} 行")


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        y, m, d = map(int, sys.argv[1].split("-"))
        target_date = date(y, m, d)
    else:
        target_date = date.today() - timedelta(days=1)
    asyncio.run(main(target_date))