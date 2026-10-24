import uuid

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LedgerEntry, User


class InsufficientFunds(Exception):
    pass


async def topup(session: AsyncSession, *, user_id: int, tokens: int, payment_id: str) -> bool:
    stmt = (
        insert(LedgerEntry)
        .values(user_id=user_id, amount=tokens, kind="topup", payment_id=payment_id)
        .on_conflict_do_nothing(constraint="uq_ledger_payment")
        .returning(LedgerEntry.id)
    )
    if (await session.execute(stmt)).scalar_one_or_none() is None:
        return False
    await session.execute(
        update(User).where(User.id == user_id).values(balance=User.balance + tokens)
    )
    return True


async def charge(session: AsyncSession, *, user_id: int, task_id: uuid.UUID, amount: int) -> None:
    result = await session.execute(
        update(User)
        .where(User.id == user_id, User.balance >= amount)
        .values(balance=User.balance - amount)
        .returning(User.id)
    )
    if result.scalar_one_or_none() is None:
        raise InsufficientFunds
    session.add(LedgerEntry(user_id=user_id, amount=-amount, kind="charge", task_id=task_id))


async def refund(session: AsyncSession, *, user_id: int, task_id: uuid.UUID, amount: int) -> bool:
    stmt = (
        insert(LedgerEntry)
        .values(user_id=user_id, amount=amount, kind="refund", task_id=task_id)
        .on_conflict_do_nothing(constraint="uq_ledger_task_kind")
        .returning(LedgerEntry.id)
    )
    if (await session.execute(stmt)).scalar_one_or_none() is None:
        return False
    await session.execute(
        update(User).where(User.id == user_id).values(balance=User.balance + amount)
    )
    return True
