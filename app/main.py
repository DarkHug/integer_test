import logging

from fastapi import FastAPI

from app.api import generate, payments, provider_webhooks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Generation service")
app.include_router(payments.router)
app.include_router(generate.router)
app.include_router(provider_webhooks.router)


@app.get("/health")
async def health():
    return {"ok": True}
