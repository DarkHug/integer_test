from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import GenModel, Leg, Task, User
from app.services import ledger
from app.services.dispatch import dispatch, new_attempt

router = APIRouter()

MAX_ACTIVE_TASKS = 3


class GenerateIn(BaseModel):
    user_id: int
    model_slug: str
    prompt: str = Field(min_length=1)
    ref_images: list[str] = []


@router.post("/generate", status_code=202)
async def generate(data: GenerateIn, session: AsyncSession = Depends(get_session)):
    async with session.begin():
        model = await session.scalar(select(GenModel).where(GenModel.slug == data.model_slug))
        if model is None:
            raise HTTPException(status_code=404, detail="model not found")

        leg = await session.scalar(
            select(Leg)
            .where(Leg.model_id == model.id, Leg.max_ref_images >= len(data.ref_images))
            .order_by(Leg.priority)
            .limit(1)
        )
        if leg is None:
            raise HTTPException(status_code=400, detail="no leg accepts this number of ref images")

        user = await session.scalar(select(User).where(User.id == data.user_id).with_for_update())
        if user is None:
            raise HTTPException(status_code=404, detail="user not found")

        active = await session.scalar(
            select(func.count()).select_from(Task)
            .where(Task.user_id == user.id, Task.status == "processing")
        )
        if active >= MAX_ACTIVE_TASKS:
            raise HTTPException(status_code=429, detail="too many active tasks")

        task = Task(user_id=user.id, model_id=model.id, prompt=data.prompt, ref_images=data.ref_images)
        session.add(task)
        await session.flush()

        try:
            await ledger.charge(session, user_id=user.id, task_id=task.id, amount=model.price)
        except ledger.InsufficientFunds:
            raise HTTPException(status_code=402, detail="insufficient tokens")

        attempt = new_attempt(task, leg)
        session.add(attempt)
        await session.flush()
        task_id, attempt_id = task.id, attempt.id

    await dispatch(attempt_id)
    return {"task_id": str(task_id)}
