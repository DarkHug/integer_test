import logging

from fastapi import FastAPI

from app.api import generate, payments

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Generation service")
app.include_router(payments.router)
app.include_router(generate.router)


@app.get("/health")
async def health():
    return {"ok": True}
