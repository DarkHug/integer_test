import asyncio

from sqlalchemy import text
from tests.conftest import provider_webhook, signed, topup

from app.db import engine
from app.services import watchdog


async def generate(client, user_id: int = 1, model: str = "image-fast") -> str:
    resp = await client.post("/generate", json={"user_id": user_id, "model_slug": model, "prompt": "cat"})
    assert resp.status_code == 202, resp.text
    return resp.json()["task_id"]


async def expire_active_attempts():
    """Переводит дедлайн активных попыток в прошлое и запускает один круг сторожа"""
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE attempts SET deadline_at = now() - interval '1 second' "
            "WHERE status IN ('sending', 'sent')"
        ))
    await watchdog.sweep()
    await asyncio.gather(*list(watchdog._dispatching))


async def ledger_kinds(client, user_id: int = 1) -> list[str]:
    resp = await client.get(f"/users/{user_id}/balance", params={"limit": 100})
    return [e["kind"] for e in resp.json()["ledger"]]


async def test_concurrent_payment_webhooks_credit_once(client):
    raw, headers = signed({"payment_id": "pay-1", "user_id": 1, "tokens": 100, "status": "succeeded"})

    responses = await asyncio.gather(*(
        client.post("/webhooks/payments", content=raw, headers=headers) for _ in range(20)
    ))

    assert all(r.status_code == 200 for r in responses)
    assert sum(r.json()["credited"] for r in responses) == 1
    balance = (await client.get("/users/1/balance")).json()
    assert balance["balance"] == 100
    assert await ledger_kinds(client) == ["topup"]


async def test_concurrent_failed_on_last_leg_refund_once(client, provider_calls):
    await topup(client, 1, 100)
    task_id = await generate(client)

    alpha = provider_calls[0]
    await provider_webhook(client, "alpha", alpha["attempt_id"], "failed", error_type="technical")
    beta = provider_calls[1]
    assert beta["provider"] == "beta"

    responses = await asyncio.gather(*(
        provider_webhook(client, "beta", beta["attempt_id"], "failed", error_type="technical")
        for _ in range(10)
    ))

    assert all(r.status_code == 200 for r in responses)
    task = (await client.get(f"/tasks/{task_id}")).json()
    assert task["status"] == "failed"
    assert (await ledger_kinds(client)).count("refund") == 1
    assert (await client.get("/users/1/balance")).json()["balance"] == 100


async def test_first_leg_fails_task_completes_on_second(client, provider_calls):
    await topup(client, 1, 100)
    task_id = await generate(client)

    await provider_webhook(client, "alpha", provider_calls[0]["attempt_id"], "failed", error_type="technical")
    await provider_webhook(
        client, "beta", provider_calls[1]["attempt_id"], "completed",
        result_url="https://files.beta.example/1.png",
    )

    task = (await client.get(f"/tasks/{task_id}")).json()
    assert task["status"] == "completed"
    assert task["result_url"] == "https://files.beta.example/1.png"
    assert [(a["provider"], a["status"], a["error_type"]) for a in task["attempts"]] == [
        ("alpha", "failed", "technical"),
        ("beta", "completed", None),
    ]
    assert (await client.get("/users/1/balance")).json()["balance"] == 98


async def test_late_completed_while_task_alive_is_accepted(client, provider_calls):
    """Правило 6: сторож закрыл alpha, задача ушла на beta, потом пришёл поздний ответ alpha."""
    await topup(client, 1, 100)
    task_id = await generate(client)
    alpha = provider_calls[0]

    await expire_active_attempts()
    assert provider_calls[1]["provider"] == "beta"

    resp = await provider_webhook(
        client, "alpha", alpha["attempt_id"], "completed",
        result_url="https://files.alpha.example/late.png",
    )
    assert resp.status_code == 200

    task = (await client.get(f"/tasks/{task_id}")).json()
    assert task["status"] == "completed"
    assert task["result_url"] == "https://files.alpha.example/late.png"
    assert [(a["provider"], a["status"]) for a in task["attempts"]] == [
        ("alpha", "completed"),
        ("beta", "superseded"),
    ]
    assert "refund" not in await ledger_kinds(client)
    assert (await client.get("/users/1/balance")).json()["balance"] == 98


async def test_late_completed_after_refund_is_ignored(client, provider_calls):
    await topup(client, 1, 100)
    task_id = await generate(client)
    alpha = provider_calls[0]

    await expire_active_attempts()  # alpha -> beta
    await expire_active_attempts()  # beta -> failed + возврат

    resp = await provider_webhook(
        client, "alpha", alpha["attempt_id"], "completed",
        result_url="https://files.alpha.example/late.png",
    )
    assert resp.status_code == 200

    task = (await client.get(f"/tasks/{task_id}")).json()
    assert task["status"] == "failed"
    assert task["result_url"] is None
    assert (await ledger_kinds(client)).count("refund") == 1
    assert (await client.get("/users/1/balance")).json()["balance"] == 100
