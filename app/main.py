import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.api import generate, payments, provider_webhooks
from app.services import watchdog

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(watchdog.run())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="Generation service", lifespan=lifespan)
app.include_router(payments.router)
app.include_router(generate.router)
app.include_router(provider_webhooks.router)


@app.get("/health")
async def health():
    return {"ok": True}
