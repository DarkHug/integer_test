import hashlib
import hmac

from fastapi import Header, HTTPException, Request

from app.config import settings


def sign(body: bytes) -> str:
    key = settings.WEBHOOK_SECRET.get_secret_value().encode()
    return hmac.new(key, body, hashlib.sha256).hexdigest()


async def verified_body(request: Request, x_signature: str = Header(...)) -> bytes:
    body = await request.body()
    if not hmac.compare_digest(sign(body), x_signature):
        raise HTTPException(status_code=401, detail="invalid signature")
    return body
