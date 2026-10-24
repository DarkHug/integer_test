import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ValidationError

from app.security import verified_body
from app.services import results
from app.services.dispatch import PROVIDER_URLS, dispatch

router = APIRouter()


class ProviderWebhook(BaseModel):
    attempt_id: uuid.UUID
    external_id: str
    status: Literal["completed", "failed"]
    result_url: str | None = None
    error_type: Literal["technical", "moderation", "payload"] | None = None


@router.post("/webhooks/providers/{name}")
async def provider_webhook(
        name: str,
        background: BackgroundTasks,
        body: bytes = Depends(verified_body),
):
    if name not in PROVIDER_URLS:
        raise HTTPException(status_code=404, detail="unknown provider")
    try:
        payload = ProviderWebhook.model_validate_json(body)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())
    if payload.status == "failed" and payload.error_type is None:
        raise HTTPException(status_code=422, detail="error_type required for failed")
    if payload.status == "completed" and not payload.result_url:
        raise HTTPException(status_code=422, detail="result_url required for completed")

    try:
        next_attempt = await results.apply_result(provider=name, **payload.model_dump())
    except results.UnknownAttempt:
        raise HTTPException(status_code=404, detail="unknown attempt")

    if next_attempt is not None:
        background.add_task(dispatch, next_attempt)
    return {"ok": True}
