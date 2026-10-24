import asyncio
import logging
import uuid

from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.models import Attempt, Task
from app.services.dispatch import dispatch, fail_and_advance

logger = logging.getLogger(__name__)

ACTIVE = ("sending", "sent")
BATCH = 50
_dispatching: set[asyncio.Task] = set()


async def expire_one(attempt_id: uuid.UUID, task_id: uuid.UUID) -> uuid.UUID | None:
    async with SessionLocal() as session, session.begin():
        task = await session.scalar(
            select(Task).where(Task.id == task_id).with_for_update(skip_locked=True)
        )
        if task is None:
            return None
        attempt = await session.get(Attempt, attempt_id)
        expired = await session.scalar(
            select(Attempt.deadline_at < func.now()).where(Attempt.id == attempt_id))
        if task.status != "processing" or attempt.status not in ACTIVE or not expired:
            return None
        logger.info("attempt %s (%s) timed out", attempt_id, attempt.provider)
        nxt = await fail_and_advance(session, task, attempt, status="timed_out", error_type="timeout")
        return nxt.id if nxt else None


async def sweep() -> int:
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(Attempt.id, Attempt.task_id)
            .where(Attempt.status.in_(ACTIVE), Attempt.deadline_at < func.now())
            .order_by(Attempt.deadline_at)
            .limit(BATCH)
        )).all()

    expired = 0
    for attempt_id, task_id in rows:
        nxt = await expire_one(attempt_id, task_id)
        if nxt is not None:
            t = asyncio.create_task(dispatch(nxt))
            _dispatching.add(t)
            t.add_done_callback(_dispatching.discard)
        expired += 1
    return expired


async def run() -> None:
    logger.info("watchdog started")
    while True:
        try:
            await sweep()
        except Exception:
            logger.exception("watchdog sweep failed")
        await asyncio.sleep(settings.WATCHDOG_INTERVAL)
