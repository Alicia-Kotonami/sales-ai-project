"""
阶段 C 网关 remote 契约与 5001/5002/5003 校验。不改进程默认 AI_MODE。

    python -m scripts.verify_ai_remote
"""
from __future__ import annotations

import asyncio
import json
import socket
import threading
from contextlib import closing
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.config import settings
from app.core.errors import BizError, ErrorCode
from app.services import ai_gateway


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_uvicorn(app: FastAPI, port: int) -> uvicorn.Server:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server


async def _wait_up(port: int) -> None:
    url = f"http://127.0.0.1:{port}/health"
    async with httpx.AsyncClient() as client:
        for _ in range(50):
            try:
                resp = await client.get(url, timeout=0.2)
                if resp.status_code < 500:
                    return
            except httpx.HTTPError:
                await asyncio.sleep(0.05)
        raise RuntimeError(f"mock server 127.0.0.1:{port} 未起来")


def _ok_app() -> FastAPI:
    import importlib.util

    path = Path(__file__).with_name("mock_ai_remote.py")
    spec = importlib.util.spec_from_file_location("mock_ai_remote", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 mock_ai_remote.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.app


def _slow_app() -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/v1/tags/recommend")
    async def tags(request: Request):
        await request.json()
        await asyncio.sleep(5)
        return {"recommendations": []}

    @app.post("/v1/schedules/parse")
    async def parse(request: Request):
        await request.json()
        await asyncio.sleep(5)
        return {"candidates": []}

    @app.post("/v1/reply/stream")
    async def reply(request: Request):
        await request.json()

        async def gen():
            await asyncio.sleep(5)
            yield "event: suggest_chunk\ndata: {\"candidateId\": 1, \"delta\": \"晚\"}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/v1/asr")
    async def asr(request: Request):
        await request.json()
        await asyncio.sleep(5)
        return {"text": "too late", "asrStatus": 2}

    return app


def _busy_app() -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/v1/tags/recommend")
    async def tags():
        return JSONResponse({"message": "busy"}, status_code=503)

    return app


async def _run() -> None:
    saved_mode = settings.AI_MODE
    saved_base = settings.AI_REMOTE_BASE_URL
    saved_timeout = settings.AI_TIMEOUT_SECONDS
    servers: list[uvicorn.Server] = []

    def restore() -> None:
        settings.AI_MODE = saved_mode
        settings.AI_REMOTE_BASE_URL = saved_base
        settings.AI_TIMEOUT_SECONDS = saved_timeout
        for srv in servers:
            srv.should_exit = True

    try:
        ok_port = _free_port()
        slow_port = _free_port()
        busy_port = _free_port()
        servers.append(_start_uvicorn(_ok_app(), ok_port))
        servers.append(_start_uvicorn(_slow_app(), slow_port))
        servers.append(_start_uvicorn(_busy_app(), busy_port))
        await _wait_up(ok_port)
        await _wait_up(slow_port)
        await _wait_up(busy_port)

        settings.AI_MODE = "remote"
        settings.AI_TIMEOUT_SECONDS = 1

        settings.AI_REMOTE_BASE_URL = f"http://127.0.0.1:{ok_port}"
        chunks = []
        async for item in ai_gateway.infer_reply_stream(
            conversation_id=1,
            customer_id=1,
            current_message={"type": "text", "text": "hi"},
            profile={},
            scenario_tags=["presale", "junior"],
        ):
            chunks.append(item)
        assert any(i["event"] == "suggest_chunk" for i in chunks), chunks
        recs = await ai_gateway.infer_tags(
            profile_sections={},
            selected_tag_ids=set(),
            catalog=[{"tagId": 9, "code": "intent_high", "name": "高意向", "category": "intent"}],
        )
        assert recs and recs[0]["tagId"] == 9, recs
        parsed = await ai_gateway.parse_time("明天联系")
        assert parsed and parsed[0]["rawTime"], parsed
        asr_text = await ai_gateway.transcribe_audio(audio_url="oss://ok.amr")
        assert "数学" in asr_text, asr_text
        print("[OK] remote 成功路径 /v1/reply/stream /v1/tags/recommend /v1/schedules/parse /v1/asr")

        try:
            await ai_gateway.transcribe_audio(audio_url="oss://fail.amr")
            raise AssertionError("ASR fail 应抛 5003")
        except BizError as exc:
            assert exc.code == int(ErrorCode.ASR_FAILED), exc.code
        print("[OK] ASR 失败 5003")

        settings.AI_REMOTE_BASE_URL = f"http://127.0.0.1:{slow_port}"
        for name, coro in (
            ("tags", ai_gateway.infer_tags(profile_sections={}, selected_tag_ids=set(), catalog=[])),
            ("parse", ai_gateway.parse_time("明天")),
        ):
            try:
                await coro
                raise AssertionError(f"{name} 应超时 5002")
            except BizError as exc:
                assert exc.code == int(ErrorCode.AI_TIMEOUT), (name, exc.code, exc.message)
        try:
            async for _ in ai_gateway.infer_reply_stream(
                conversation_id=1,
                customer_id=1,
                current_message={"type": "text", "text": "hi"},
                profile={},
                scenario_tags=["presale"],
            ):
                pass
            raise AssertionError("reply stream 应超时 5002")
        except BizError as exc:
            assert exc.code == int(ErrorCode.AI_TIMEOUT), (exc.code, exc.message)
        try:
            await ai_gateway.transcribe_audio(audio_url="oss://slow.amr")
            raise AssertionError("ASR 超时应 5003")
        except BizError as exc:
            assert exc.code == int(ErrorCode.ASR_FAILED), exc.code
        print("[OK] 3s 熔断：推理 5002 / ASR 5003")

        settings.AI_REMOTE_BASE_URL = f"http://127.0.0.1:{busy_port}"
        try:
            await ai_gateway.infer_tags(profile_sections={}, selected_tag_ids=set(), catalog=[])
            raise AssertionError("busy 应 5001")
        except BizError as exc:
            assert exc.code == int(ErrorCode.AI_BUSY), exc.code
        print("[OK] 网关不可用 5001")

        settings.AI_MODE = "mock"
        mock_asr = await ai_gateway.transcribe_audio(audio_url=None, fallback_text=None)
        assert mock_asr == "（语音转写占位文本）", mock_asr
        print("[OK] mock ASR 占位未改")
        print(json.dumps({"pass": True}, ensure_ascii=False))
    finally:
        restore()


if __name__ == "__main__":
    asyncio.run(_run())
