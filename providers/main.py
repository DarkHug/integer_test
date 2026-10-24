import asyncio
import hashlib
import hmac
import json
import os
import random
import uuid

import httpx
from fastapi import FastAPI, Response
from pydantic import BaseModel

NAME = os.getenv("PROVIDER_NAME", "alpha")
SECRET = os.environ["WEBHOOK_SECRET"].encode()


class Behavior(BaseModel):
    fail_rate: float = 0.0
    fail_type: str = "technical"
    sync_error: str | None = None
    duplicate: bool = False
    drop: bool = False
    delay_min: float = 2
    delay_max: float = 20


class TaskIn(BaseModel):
    attempt_id: str
    prompt: str
    ref_images: list[str] = []
    callback_url: str


app = FastAPI(title=f"fake provider {NAME}")
behavior = Behavior()
_background: set[asyncio.Task] = set()


@app.put("/config")
async def set_config(new: Behavior):
    global behavior
    behavior = new
    return behavior


@app.get("/config")
async def get_config():
    return behavior


@app.post("/tasks", status_code=202)
async def create_task(task: TaskIn):
    b = behavior
    if b.sync_error == "503":
        return Response(status_code=503)
    if b.sync_error == "timeout":
        await asyncio.sleep(30)

    external_id = f"{NAME}-{uuid.uuid4().hex[:12]}"
    bg = asyncio.create_task(deliver(task, external_id, b))
    _background.add(bg)
    bg.add_done_callback(_background.discard)
    return {"external_id": external_id}


async def deliver(task: TaskIn, external_id: str, b: Behavior) -> None:
    if b.drop:
        return
    await asyncio.sleep(random.uniform(b.delay_min, b.delay_max))

    payload = {"attempt_id": task.attempt_id, "external_id": external_id}
    if random.random() < b.fail_rate:
        payload |= {"status": "failed", "error_type": b.fail_type}
    else:
        payload |= {"status": "completed", "result_url": f"https://files.{NAME}.example/{external_id}.png"}

    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Signature": hmac.new(SECRET, body, hashlib.sha256).hexdigest(),
    }
    copies = 2 if b.duplicate else 1
    async with httpx.AsyncClient(timeout=10) as client:
        await asyncio.gather(
            *(client.post(task.callback_url, content=body, headers=headers) for _ in range(copies)),
            return_exceptions=True,
        )
