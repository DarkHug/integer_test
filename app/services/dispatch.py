import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.models import Attempt, LedgerEntry, Leg, Task
from app.services import ledger

logger = logging.getLogger(__name__)

PROVIDER_URLS = {"alpha": settings.ALPHA_URL, "beta": settings.BETA_URL}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_deadline() -> datetime:
    return utcnow() + timedelta(seconds=settings.PROVIDER_TIMEOUT)


async def lock_task(session: AsyncSession, task_id: uuid.UUID) -> Task | None:
    stmt = select(Task).where(Task.id == task_id).with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


def new_attempt(task: Task, leg: Leg) -> Attempt:
    return Attempt(
        task_id=task.id,
        leg_id=leg.id,
        provider=leg.provider,
        status="sending",
        deadline_at=new_deadline(),
    )


async def fail_and_advance(
        session: AsyncSession, task: Task, attempt: Attempt, *, status: str, error_type: str
) -> Attempt | None:
    attempt.status = status
    attempt.error_type = error_type
    attempt.finished_at = utcnow()

    if error_type != "payload":
        current = await session.get(Leg, attempt.leg_id)
        stmt = (
            select(Leg)
            .where(
                Leg.model_id == task.model_id,
                Leg.priority > current.priority,
                Leg.max_ref_images >= len(task.ref_images),
            )
            .order_by(Leg.priority)
            .limit(1)
        )
        if error_type == "moderation":
            stmt = stmt.where(Leg.skip_on_moderation.is_(False))
        leg = (await session.execute(stmt)).scalar_one_or_none()
        if leg is not None:
            nxt = new_attempt(task, leg)
            session.add(nxt)
            await session.flush()
            return nxt

    task.status = "failed"
    charged = await session.scalar(
        select(LedgerEntry.amount).where(LedgerEntry.task_id == task.id, LedgerEntry.kind == "charge")
    )
    await ledger.refund(session, user_id=task.user_id, task_id=task.id, amount=-charged)
    return None


async def send_once(attempt_id: uuid.UUID) -> uuid.UUID | None:
    async with SessionLocal() as session:
        attempt = await session.get(Attempt, attempt_id)
        task = await session.get(Task, attempt.task_id)
        task_id = task.id
        provider = attempt.provider
        url = f"{PROVIDER_URLS[provider]}/tasks"
        payload = {
            "attempt_id": str(attempt.id),
            "prompt": task.prompt,
            "ref_images": task.ref_images,
            "callback_url": f"{settings.SERVICE_URL}/webhooks/providers/{provider}",
        }

    external_id, error = None, None
    try:
        async with httpx.AsyncClient(timeout=settings.SEND_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code == 202:
            external_id = resp.json()["external_id"]
        else:
            error = "sync_error"
            logger.warning("provider %s returned %s: %s", provider, resp.status_code, resp.text[:200])
    except httpx.HTTPError as e:
        error = "sync_error"
        logger.warning("provider %s request failed: %r", provider, e)

    async with SessionLocal() as session, session.begin():
        task = await lock_task(session, task_id)
        attempt = await session.get(Attempt, attempt_id)
        if task.status != "processing" or attempt.status != "sending":
            return None  # попытку уже закрыл сторож или вебхук
        if error is None:
            attempt.status = "sent"
            attempt.external_id = external_id
            attempt.deadline_at = new_deadline()
            return None
        nxt = await fail_and_advance(session, task, attempt, status="failed", error_type=error)
        return nxt.id if nxt else None


async def dispatch(attempt_id: uuid.UUID | None) -> None:
    while attempt_id is not None:
        attempt_id = await send_once(attempt_id)