import asyncio
from typing import AsyncGenerator


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