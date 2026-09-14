from fastapi import FastAPI

from app.core.config import settings

app = FastAPI(title=settings.APP_NAME, version="0.1.0")


@app.get("/")
def read_root():
    return {
        "message": "Hello, Sales AI System!",
        "env": settings.APP_ENV,
        "app": settings.APP_NAME,
    }


@app.get("/health")
def health():
    return {"status": "ok"}



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )



