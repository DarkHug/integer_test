import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Attempt, GenModel, LedgerEntry, Leg, Task, User

router = APIRouter()

ACTIVE = ("sending", "sent")


@router.get("/tasks/{task_id}")
async def get_task(task_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")

    model_slug = await session.scalar(select(GenModel.slug).where(GenModel.id == task.model_id))
    rows = (await session.execute(
        select(Attempt, Leg.priority)
        .join(Leg, Leg.id == Attempt.leg_id)
        .where(Attempt.task_id == task_id)
        .order_by(Attempt.created_at)
    )).all()

    current = next(
        ({"provider": a.provider, "priority": p} for a, p in rows if a.status in ACTIVE),
        None,
    )
    return {
        "id": str(task.id),
        "model": model_slug,
        "status": task.status,
        "result_url": task.result_url,
        "created_at": task.created_at,
        "current_leg": current,
        "attempts": [
            {
                "provider": a.provider,
                "priority": p,
                "status": a.status,
                "error_type": a.error_type,
                "started_at": a.created_at,
                "finished_at": a.finished_at,
            }
            for a, p in rows
        ],
    }


@router.get("/users/{user_id}/balance")
async def get_balance(
        user_id: int,
        limit: int = Query(20, ge=1, le=100),
        session: AsyncSession = Depends(get_session),
):
    async with session.begin():
        await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        user = await session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="user not found")
        entries = (await session.scalars(
            select(LedgerEntry)
            .where(LedgerEntry.user_id == user_id)
            .order_by(LedgerEntry.id.desc())
            .limit(limit)
        )).all()

    return {
        "user_id": user.id,
        "balance": user.balance,
        "ledger": [
            {
                "id": e.id,
                "kind": e.kind,
                "amount": e.amount,
                "task_id": str(e.task_id) if e.task_id else None,
                "payment_id": e.payment_id,
                "created_at": e.created_at,
            }
            for e in entries
        ],
    }
