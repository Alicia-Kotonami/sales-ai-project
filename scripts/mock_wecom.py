"""
企微 HTTP 打桩，仅供本地联调。不要配成生产 WECOM_API_BASE_URL。

    python -m uvicorn scripts.mock_wecom:app --host 127.0.0.1 --port 9001
"""
from __future__ import annotations

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="sales-ai mock WeCom")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/cgi-bin/gettoken")
async def gettoken(corpid: str = "", corpsecret: str = ""):
    if not corpid or not corpsecret:
        return JSONResponse({"errcode": 40013, "errmsg": "invalid corpid"})
    return {"errcode": 0, "access_token": "mock-access-token", "expires_in": 7200}


@app.get("/cgi-bin/user/getuserinfo")
async def getuserinfo(access_token: str = "", code: str = ""):
    if code in ("", "bad"):
        return JSONResponse({"errcode": 40029, "errmsg": "invalid code"})
    return {"errcode": 0, "UserId": code, "DeviceId": "mock"}


@app.post("/cgi-bin/oa/schedule/add")
async def schedule_add(request: Request, access_token: str = Query(default="")):
    body = await request.json()
    schedule = body.get("schedule") or {}
    summary = schedule.get("summary") or ""
    if not summary:
        return JSONResponse({"errcode": 40058, "errmsg": "summary empty"})
    return {"errcode": 0, "schedule_id": "mock-sch-add-001"}


@app.post("/cgi-bin/oa/schedule/update")
async def schedule_update(request: Request, access_token: str = Query(default="")):
    body = await request.json()
    schedule = body.get("schedule") or {}
    sid = schedule.get("schedule_id") or "mock-sch-upd-001"
    return {"errcode": 0, "schedule_id": sid}
