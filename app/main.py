from fastapi import FastAPI

app = FastAPI(title="销售赋能AI系统", version="0.1.0")


@app.get("/")
def read_root():
    return {"message": "Hello, Sales AI System!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
