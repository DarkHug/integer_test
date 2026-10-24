from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import User
from app.security import verified_body
from app.services import ledger

router = APIRouter()


class PaymentWebhook(BaseModel):
    payment_id: str
    user_id: int
    tokens: int = Field(gt=0)
    status: str


@router.post("/webhooks/payments")
async def payment_webhook(
        body: bytes = Depends(verified_body),
        session: AsyncSession = Depends(get_session),
):
    try:
        payload = PaymentWebhook.model_validate_json(body)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    if payload.status != "succeeded":
        return {"credited": False}

    async with session.begin():
        if await session.get(User, payload.user_id) is None:
            raise HTTPException(status_code=404, detail="user not found")
        credited = await ledger.topup(
            session, user_id=payload.user_id, tokens=payload.tokens, payment_id=payload.payment_id
        )
    return {"credited": credited}
