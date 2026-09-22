import asyncio
from typing import AsyncGenerator
from datetime import datetime, timedelta, timezone

MOCK_CANDIDATES = {
    ("presale", "primary"): [
        "家长您好，小学阶段我们更推荐先做一次免费测评，看看孩子的基础和习惯，再定课程会更稳妥~",
        "您好，我们小学课程按「校内同步 + 思维拓展」两条线走，可以先约一节试听课感受一下。",
    ],
    ("presale", "junior"): [
        "家长您好，初中阶段我们按课时包设置，先给孩子做一次免费测评再定制方案更稳妥~",
        "您好，初中单科我们有多种班型，可以先了解孩子目前数学/物理的薄弱点，再约试听。",
    ],
    ("presale", "senior"): [
        "家长您好，高中阶段时间紧，我们建议先做一次学科诊断，再匹配冲刺/同步课程。",
        "您好，高中课程我们按目标院校和当前分数段来规划，可以先把最近一次月考成绩发我看看。",
    ],
    ("aftersale", "primary"): [
        "家长您好，这周孩子的课后练习完成得不错，我会继续跟进，有问题随时找我~",
        "您好，本周反馈：孩子在应用题读题上还需要多练，我整理了一份练习，稍后发您。",
    ],
    ("aftersale", "junior"): [
        "家长您好，本周数学错题我整理好了，建议周末花 30 分钟重做一遍，下周我再跟进。",
        "您好，孩子这次物理小测有进步，我建议保持节奏，接下来重点放在力学综合题。",
    ],
    ("aftersale", "senior"): [
        "家长您好，本周阶段测已出，我按目标院校做了分数拆解，晚点电话跟您细说。",
        "您好，孩子这周状态稳定，建议继续保持每日 30 分钟英语听力，我下周再复盘。",
    ],
}


async def stream_reply_mock(
    *,
    scenario_tags: list[str],
    chunk_size: int = 6,
    per_chunk_delay: float = 0.05,
) -> AsyncGenerator[dict, None]:
    """
    以 SSE 事件的形式，流式返回 2 条候选话术。
    yield 的每个 dict 就是 data 部分（不含 event: xxx）。
    """
    stage_tag = scenario_tags[0]     # presale / aftersale
    stage = scenario_tags[1] if len(scenario_tags) > 1 else "primary"
    candidates = MOCK_CANDIDATES.get((stage_tag, stage)) or MOCK_CANDIDATES[
        ("presale", "primary")
    ]

    for idx, text in enumerate(candidates, start=1):
        for i in range(0, len(text), chunk_size):
            yield {
                "event": "suggest_chunk",
                "data": {"candidateId": idx, "delta": text[i : i + chunk_size]},
            }
            await asyncio.sleep(per_chunk_delay)


async def infer_tags_mock(
    *,
    profile_sections: dict,
    selected_tag_ids: set[int],
    catalog: list[dict],
) -> list[dict]:
    """
    根据画像给出固定标签推荐（Mock）。
    输入：
    - profile_sections: 画像 sections
    - selected_tag_ids: 当前已生效 tag_id 集合
    - catalog: enabled 标签目录（每项含 tagId / code / name / category）
    输出：[{action, tagId, reason, confidence, evidenceRefs, sopSummary}]
    """
    by_code = {c["code"]: c for c in catalog}
    results: list[dict] = []

    grade = ((profile_sections.get("basic") or {}).get("grade") or "").upper()
    weak = ((profile_sections.get("study") or {}).get("weak_subjects") or [])
    weak_str = "、".join(weak)

    # 1) 学段：G7~G9 -> stage_junior
    if grade.startswith("G") and grade[1:].isdigit():
        n = int(grade[1:])
        if 7 <= n <= 9 and "stage_junior" in by_code:
            t = by_code["stage_junior"]
            if t["tagId"] not in selected_tag_ids:
                results.append({
                    "action": "check",
                    "tagId": t["tagId"],
                    "reason": f"画像学段 {grade} 命中初中",
                    "confidence": 0.92,
                    "evidenceRefs": ["profile:basic.grade"],
                    "sopSummary": None,
                })

    # 2) 学科：weak_subjects 里含数学 / 物理
    if "数学" in weak and "subject_math" in by_code:
        t = by_code["subject_math"]
        if t["tagId"] not in selected_tag_ids:
            results.append({
                "action": "check",
                "tagId": t["tagId"],
                "reason": f"薄弱学科包含数学（{weak_str}）",
                "confidence": 0.88,
                "evidenceRefs": ["profile:study.weak_subjects"],
                "sopSummary": None,
            })
    if "物理" in weak and "subject_phys" in by_code:
        t = by_code["subject_phys"]
        if t["tagId"] not in selected_tag_ids:
            results.append({
                "action": "check",
                "tagId": t["tagId"],
                "reason": f"薄弱学科包含物理（{weak_str}）",
                "confidence": 0.85,
                "evidenceRefs": ["profile:study.weak_subjects"],
                "sopSummary": None,
            })

    # 3) 高意向：preference.price_sensitivity=高
    price = ((profile_sections.get("preference") or {}).get("price_sensitivity") or "")
    if price == "高" and "intent_high" in by_code:
        t = by_code["intent_high"]
        if t["tagId"] not in selected_tag_ids:
            results.append({
                "action": "check",
                "tagId": t["tagId"],
                "reason": "画像价格敏感度高，近期询问价格与课时",
                "confidence": 0.80,
                "evidenceRefs": ["profile:preference.price_sensitivity"],
                "sopSummary": None,
            })

    # 4) 取消推荐：已选初中数学但画像里没有数学
    math_id = by_code.get("subject_math", {}).get("tagId")
    if math_id and math_id in selected_tag_ids and "数学" not in weak:
        results.append({
            "action": "uncheck",
            "tagId": math_id,
            "reason": "画像薄弱学科已无数学，建议取消",
            "confidence": 0.75,
            "evidenceRefs": ["profile:study.weak_subjects"],
            "sopSummary": None,
        })

    return results



_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}


def _next_weekday(base: datetime, weekday: int) -> datetime:
    """下周 weekday（周一=1 ... 周日=7）。"""
    days_ahead = (7 - base.weekday()) + (weekday - 1)
    if days_ahead <= 0:
        days_ahead += 7
    return base + timedelta(days=days_ahead)


async def parse_time_mock(text: str) -> list[dict]:
    """
    Mock 时间解析：覆盖几种常见说法：
    - 今天 / 明天 / 后天
    - 下周X / 本周X
    - X天以后 / X小时后
    - 具体日期 2026-09-25
    返回：[{rawTime, parsedAt, task, priority, confidence, sourceRefs}]
    """
    now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))
    results: list[dict] = []

    def make(raw: str, parsed: datetime, task: str, priority: str, conf: float):
        results.append({
            "rawTime": raw,
            "parsedAt": parsed.isoformat(),
            "task": task,
            "priority": priority,
            "confidence": conf,
            "sourceRefs": [],
        })

    if "今天" in text:
        make("今天", now.replace(hour=20, minute=0, second=0, microsecond=0),
             "今日跟进", "P1", 0.9)
    if "明天" in text:
        make("明天", (now + timedelta(days=1)).replace(hour=20, minute=0, second=0, microsecond=0),
             "明日跟进", "P1", 0.9)
    if "后天" in text:
        make("后天", (now + timedelta(days=2)).replace(hour=20, minute=0, second=0, microsecond=0),
             "后天跟进", "P1", 0.85)

    # 下周X / 本周X
    for kw, base in (("下周", _next_weekday(now, 1)), ("本周", now)):
        if kw in text:
            for cn, wd in _CN_NUM.items():
                if f"{kw}{cn}" in text:
                    target = _next_weekday(now, wd) if kw == "下周" else (
                        base + timedelta(days=wd - 1 - base.weekday())
                    )
                    target = target.replace(hour=20, minute=0, second=0, microsecond=0)
                    make(f"{kw}{cn}", target, f"{kw}{cn}跟进", "P1", 0.8)
                    break

    # X天以后 / X小时后
    import re
    m = re.search(r"(\d+)\s*天(?:以)?后", text)
    if m:
        n = int(m.group(1))
        make(f"{n}天后", (now + timedelta(days=n)).replace(hour=20, minute=0, second=0, microsecond=0),
             f"{n}天后跟进", "P2", 0.75)
    m = re.search(r"(\d+)\s*(?:个)?小时(?:以)?后", text)
    if m:
        n = int(m.group(1))
        make(f"{n}小时后", now + timedelta(hours=n), f"{n}小时后跟进", "P1", 0.7)

    # 具体日期
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m:
        y, mo, d = map(int, m.groups())
        try:
            target = datetime(y, mo, d, 20, 0, tzinfo=now.tzinfo)
            make(m.group(0), target, "指定日期跟进", "P2", 0.85)
        except ValueError:
            pass

    return results
