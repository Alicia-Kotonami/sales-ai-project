from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api import agent, asr, rag, reply, schedules, tags
from app.config import settings

app = FastAPI(title="sales-ai AI Runtime", version="0.1.0")

app.include_router(reply.router)
app.include_router(tags.router)
app.include_router(schedules.router)
app.include_router(asr.router)
app.include_router(rag.router)
app.include_router(agent.router)


@app.get("/health")
async def health():
    provider = (settings.AI_RUNTIME_PROVIDER or "deepseek").strip().lower()
    has_key = bool((settings.DEEPSEEK_API_KEY or "").strip())
    return JSONResponse(
        {
            "status": "ok",
            "provider": provider,
            "deepseekConfigured": has_key if provider == "deepseek" else None,
        }
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.AI_RUNTIME_HOST,
        port=int(settings.AI_RUNTIME_PORT),
        reload=False,
    )
