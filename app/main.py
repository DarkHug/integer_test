from fastapi import FastAPI

from app.api import payments, generate

app = FastAPI(title="Generation service")
app.include_router(payments.router)
app.include_router(generate.router)


@app.get("/health")
async def health():
    return {"ok": True}
