import asyncio
import json
import os
import subprocess
import sys

# Настройки должны быть заданы ДО импорта приложения: settings читаются при импорте.
TEST_DB = "app_test"
PG_HOST_URL = os.getenv("TEST_PG_URL", "postgresql://app:app@localhost:5432")
os.environ["DATABASE_URL"] = PG_HOST_URL.replace("postgresql://", "postgresql+asyncpg://") + f"/{TEST_DB}"
os.environ["WEBHOOK_SECRET"] = "test-secret"
os.environ["PROVIDER_TIMEOUT"] = "60"

import asyncpg  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.security import sign  # noqa: E402
from app.services import dispatch  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def database():
    async def create():
        conn = await asyncpg.connect(f"{PG_HOST_URL}/postgres")
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB):
            await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
        await conn.close()

    asyncio.run(create())
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=os.environ.copy())


@pytest.fixture(autouse=True)
async def clean_db():
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE attempts, ledger_entries, tasks RESTART IDENTITY CASCADE"))
        await conn.execute(text("UPDATE users SET balance = 0"))
    yield
    await engine.dispose()


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def provider_calls(monkeypatch):
    """Подменяет отправку провайдеру: всегда 202, запоминает отправленные попытки."""
    calls: list[dict] = []

    async def fake_post(provider: str, url: str, payload: dict):
        calls.append({"provider": provider, **payload})
        return f"{provider}-ext-{len(calls)}", None

    monkeypatch.setattr(dispatch, "post_to_provider", fake_post)
    return calls


def signed(body: dict) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    return raw, {"X-Signature": sign(raw), "Content-Type": "application/json"}


async def topup(client, user_id: int, tokens: int, payment_id: str = "seed-payment"):
    raw, headers = signed({"payment_id": payment_id, "user_id": user_id, "tokens": tokens, "status": "succeeded"})
    resp = await client.post("/webhooks/payments", content=raw, headers=headers)
    assert resp.status_code == 200


async def provider_webhook(client, provider: str, attempt_id: str, status: str, **extra):
    body = {"attempt_id": attempt_id, "external_id": f"{provider}-ext", "status": status, **extra}
    raw, headers = signed(body)
    return await client.post(f"/webhooks/providers/{provider}", content=raw, headers=headers)
