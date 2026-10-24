import logging
import uuid

from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import Attempt, Task
from app.services.dispatch import fail_and_advance, lock_task, utcnow

logger = logging.getLogger(__name__)

ACTIVE = ("sending", "sent")


class UnknownAttempt(Exception):
    pass


def _complete(task: Task, attempt: Attempt, external_id: str, result_url: str) -> None:
    attempt.status = "completed"
    attempt.external_id = external_id
    attempt.finished_at = utcnow()
    task.status = "completed"
    task.result_url = result_url


async def apply_result(
        *,
        provider: str,
        attempt_id: uuid.UUID,
        external_id: str,
        status: str,
        result_url: str | None,
        error_type: str | None,
) -> uuid.UUID | None:

    async with SessionLocal() as session, session.begin():
        task_id = await session.scalar(select(Attempt.task_id).where(Attempt.id == attempt_id))
        if task_id is None:
            raise UnknownAttempt
        task = await lock_task(session, task_id)
        attempt = await session.get(Attempt, attempt_id)
        if attempt.provider != provider:
            raise UnknownAttempt

        if task.status != "processing":
            logger.info(f"late %s for attempt %s ignored: task already %s", status, attempt_id, task.status)
            return None

        if attempt.status in ACTIVE:
            if status == "completed":
                _complete(task, attempt, external_id, result_url)
                return None
            nxt = await fail_and_advance(session, task, attempt, status="failed", error_type=error_type)
            return nxt.id if nxt else None

        if attempt.status == "timed_out" and status == "completed":
            _complete(task, attempt, external_id, result_url)
            await session.execute(
                update(Attempt)
                .where(Attempt.task_id == task.id, Attempt.status.in_(ACTIVE))
                .values(status="superseded", finished_at=utcnow())
            )
            logger.info("late completed for attempt %s accepted, active attempts superseded", attempt_id)
            return None

        logger.info("duplicate %s for attempt %s ignored (attempt %s)", status, attempt_id, attempt.status)
        return None
