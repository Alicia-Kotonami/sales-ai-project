"""
阶段 F 一键冒烟：跑 docs/smoke-test.md 中的后端 curl（JSON 用 httpx，避免 PowerShell 吞引号）。

用法（conda RAG_study，仓库根目录）：

    python -m scripts.smoke_test
    bash scripts/smoke_test.sh
"""
from __future__ import annotations

import os
import sys

import httpx

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:8000").rstrip("/")
ADMIN = {"X-Debug-User-Id": "1"}
ADVISOR = {"X-Debug-User-Id": "2"}


class SmokeError(RuntimeError):
    pass


def _print(ok: bool, name: str, extra: str = "") -> None:
    mark = "OK" if ok else "FAIL"
    print(f"[{mark}] {name} {extra}".rstrip())


def _code(resp: httpx.Response) -> int | None:
    try:
        return int(resp.json().get("code"))
    except Exception:
        return None


def main() -> int:
    timeout = httpx.Timeout(30.0)
    failed = 0
    with httpx.Client(base_url=BASE, timeout=timeout) as c:

        def run(name: str, fn):
            nonlocal failed
            try:
                fn()
            except SmokeError as exc:
                failed += 1
                _print(False, name, str(exc))
            except Exception as exc:  # noqa: BLE001
                failed += 1
                _print(False, name, f"{type(exc).__name__}: {exc}")

        # ---- 健康 ----
        def health():
            for path in ("/health", "/health/db", "/health/redis"):
                resp = c.get(path)
                body = resp.json()
                if body.get("code") != 0:
                    raise SmokeError(path)
            _print(True, "health")

        run("health", health)

        # ---- 历史接口 ----
        def login():
            resp = c.post("/api/v1/auth/login", json={"wechat_userid": "wx_advisor_002"})
            if _code(resp) != 0:
                raise SmokeError(resp.text)
            _print(True, "auth.login")

        def p1():
            resp = c.get("/api/v1/profiles/3", headers=ADVISOR)
            if _code(resp) != 0:
                raise SmokeError(resp.text)
            resp2 = c.get("/api/v1/profiles/1", headers=ADVISOR)
            if _code(resp2) != 1003:
                raise SmokeError(f"顾问读客户1 应为1003 实际{_code(resp2)}")
            _print(True, "P1")

        def t0_t3():
            if _code(c.get("/api/v1/tags/catalog", headers=ADVISOR)) != 0:
                raise SmokeError("T0")
            if _code(c.get("/api/v1/customers/3/tags", headers=ADVISOR)) != 0:
                raise SmokeError("T3")
            _print(True, "T0/T3")

        def s4_a3_a4_a9():
            if _code(c.get("/api/v1/schedules/today", headers=ADVISOR)) != 0:
                raise SmokeError("S4")
            if _code(
                c.get(
                    "/api/v1/admin/customers",
                    headers=ADMIN,
                    params={"ownerUserId": 2},
                )
            ) != 0:
                raise SmokeError("A3")
            if _code(c.get("/api/v1/admin/customers/3/communications", headers=ADMIN)) != 0:
                raise SmokeError("A4")
            if _code(c.get("/api/v1/admin/dashboard/adoption-rate", headers=ADMIN)) != 0:
                raise SmokeError("A9")
            _print(True, "S4/A3/A4/A9")

        run("auth.login", login)
        run("P1", p1)
        run("T0/T3", t0_t3)
        run("S4/A3/A4/A9", s4_a3_a4_a9)

        # ---- 阶段 B ----
        def stage_b():
            if _code(c.get("/api/v1/admin/users", params={"page": 1, "page_size": 20}, headers=ADMIN)) != 0:
                raise SmokeError("A1a")
            if _code(c.get("/api/v1/admin/users", headers=ADVISOR)) != 1003:
                raise SmokeError("A1a advisor")
            create = c.post(
                "/api/v1/admin/users",
                headers=ADMIN,
                json={
                    "wechatUserid": "wx_advisor_smoke",
                    "name": "测试顾问",
                    "roleCode": "advisor",
                    "regionId": 1,
                    "dataScope": 1,
                },
            )
            if _code(create) not in (0, 1001):
                raise SmokeError(f"A1b {_code(create)}")
            if _code(c.put("/api/v1/admin/users/2", headers=ADMIN, json={"name": "刘大伟"})) != 0:
                raise SmokeError("A1c")
            if _code(
                c.put(
                    "/api/v1/admin/users/2/permissions",
                    headers=ADMIN,
                    json={"roleCode": "advisor", "dataScope": 1},
                )
            ) != 0:
                raise SmokeError("A2")
            if _code(c.get("/api/v1/admin/orders", params={"page": 1, "page_size": 20}, headers=ADMIN)) != 0:
                raise SmokeError("A5 list")
            if _code(c.get("/api/v1/admin/orders/1", headers=ADMIN)) not in (0, 1004):
                raise SmokeError("A5 detail")
            for path in (
                "/api/v1/admin/dashboard/funnel",
                "/api/v1/admin/dashboard/renewal-rate",
                "/api/v1/admin/dashboard/advisor-efficiency",
            ):
                if _code(c.get(path, headers=ADMIN)) != 0:
                    raise SmokeError(path)
            t4 = c.post(
                "/api/v1/admin/tags",
                headers=ADMIN,
                json={
                    "code": "intent_smoke",
                    "name": "冒烟意向",
                    "category": "intent",
                    "measurableRule": "7日内主动询价",
                    "maxPerCustomer": 1,
                    "sortOrder": 99,
                },
            )
            if _code(t4) not in (0, 1001):
                raise SmokeError(f"T4 {_code(t4)}")
            if _code(c.put("/api/v1/admin/tags/1", headers=ADMIN, json={"sortOrder": 1})) != 0:
                raise SmokeError("T5")
            if _code(
                c.put(
                    "/api/v1/admin/tags/1/sop",
                    headers=ADMIN,
                    json={
                        "name": "高意向SOP",
                        "steps": [
                            {
                                "seq": 1,
                                "action": "24小时内邀约试听",
                                "offset_days": 1,
                                "template": "您好",
                            }
                        ],
                    },
                )
            ) != 0:
                raise SmokeError("T6")
            if _code(c.get("/api/v1/admin/tags/1/stats", headers=ADMIN)) != 0:
                raise SmokeError("T7")
            if _code(
                c.post(
                    "/api/v1/admin/tags",
                    headers=ADVISOR,
                    json={
                        "code": "x",
                        "name": "x",
                        "category": "intent",
                        "measurableRule": "x",
                    },
                )
            ) != 1003:
                raise SmokeError("T4 advisor")
            _print(True, "stage B")

        run("stage B", stage_b)

        # ---- 阶段 C ----
        def stage_c():
            r1 = c.post(
                "/api/v1/reply/suggestions/stream",
                headers=ADVISOR,
                json={
                    "conversationId": 2,
                    "customerId": 3,
                    "currentMessage": {"type": "text", "text": "数学怎么收费"},
                },
            )
            if r1.status_code != 200 or "suggest_done" not in r1.text:
                raise SmokeError("R1 text")
            r1a = c.post(
                "/api/v1/reply/suggestions/stream",
                headers=ADVISOR,
                json={
                    "conversationId": 2,
                    "customerId": 3,
                    "currentMessage": {
                        "type": "audio",
                        "audioUrl": "oss://msg/demo.amr",
                    },
                },
            )
            if "asr_result" not in r1a.text:
                raise SmokeError("R1 audio")
            t1 = c.post(
                "/api/v1/tags/recommendations/stream",
                headers=ADVISOR,
                json={"customerId": 3, "conversationId": 2},
            )
            if "tag_recommend_done" not in t1.text:
                raise SmokeError("T1")
            s1 = c.post(
                "/api/v1/schedules/parse",
                headers=ADVISOR,
                json={"text": "明天下午跟进试听"},
            )
            if _code(s1) != 0:
                raise SmokeError("S1")
            _print(True, "stage C")

        run("stage C", stage_c)

        # ---- 阶段 D ----
        def stage_d():
            spec = c.get("/openapi.json").json().get("paths", {})
            if "/api/v1/wecom/callback" not in spec:
                print("[SKIP] stage D 回调/OAuth：8000 进程无企微路由，重启 uvicorn 后再验")
            else:
                g = c.get("/api/v1/wecom/callback", params={"echostr": "ping-ok"})
                if g.text != "ping-ok":
                    raise SmokeError(f"D1 GET {g.text}")
                p = c.post("/api/v1/wecom/callback", content="<xml></xml>")
                if p.text != "ok":
                    raise SmokeError(f"D1 POST {p.text}")
                oauth = c.post("/api/v1/auth/wecom-oauth", json={"code": "wx_advisor_002"})
                if _code(oauth) != 0:
                    raise SmokeError(f"D2 {oauth.text}")
                bad = c.post("/api/v1/auth/wecom-oauth", json={})
                if _code(bad) != 1001:
                    raise SmokeError("D2 missing code")
            created = c.post(
                "/api/v1/schedules/tasks",
                headers=ADVISOR,
                json={
                    "customerId": 3,
                    "type": 1,
                    "title": "试听回访",
                    "dueAt": "2026-09-23T20:00:00+08:00",
                    "priority": 1,
                },
            )
            if _code(created) != 0:
                raise SmokeError(f"S2 {created.text}")
            task_id = created.json()["data"]["taskId"]
            sync = c.post(f"/api/v1/schedules/tasks/{task_id}/sync-wechat", headers=ADVISOR)
            if _code(sync) != 0:
                raise SmokeError(f"S5 {sync.text}")
            _print(True, "stage D")

        run("stage D", stage_d)

    if failed:
        print(f"smoke_test FAILED ({failed} groups)")
        return 1
    print("smoke_test PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
