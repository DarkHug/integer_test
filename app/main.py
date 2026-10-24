from fastapi import FastAPI

from app.api import payments

app = FastAPI(title="Generation service")
app.include_router(payments.router)


@app.get("/health")
async def health():
    return {"ok": True}
