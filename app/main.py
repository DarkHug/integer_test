from fastapi import FastAPI

app = FastAPI(title="Generation service")


@app.get("/health")
async def health():
    return {"ok": True}