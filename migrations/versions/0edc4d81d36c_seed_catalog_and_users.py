"""seed catalog and users

Revision ID: 0edc4d81d36c
Revises: 6c8e1e05563d
Create Date: 2026-10-24 01:22:44.911662

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0edc4d81d36c'
down_revision: Union[str, Sequence[str], None] = '6c8e1e05563d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    models = sa.table("models", sa.column("id"), sa.column("slug"), sa.column("price"))
    legs = sa.table(
        "legs",
        sa.column("model_id"), sa.column("provider"), sa.column("priority"),
        sa.column("max_ref_images"), sa.column("skip_on_moderation"),
    )
    users = sa.table("users", sa.column("id"), sa.column("balance"))

    op.bulk_insert(models, [
        {"id": 1, "slug": "image-fast", "price": 2},
        {"id": 2, "slug": "video-long", "price": 25},
    ])
    op.bulk_insert(legs, [
        {"model_id": 1, "provider": "alpha", "priority": 1, "max_ref_images": 4, "skip_on_moderation": False},
        {"model_id": 1, "provider": "beta", "priority": 2, "max_ref_images": 10, "skip_on_moderation": False},
        {"model_id": 2, "provider": "beta", "priority": 1, "max_ref_images": 2, "skip_on_moderation": False},
        {"model_id": 2, "provider": "alpha", "priority": 2, "max_ref_images": 1, "skip_on_moderation": True},
    ])
    op.bulk_insert(users, [{"id": i, "balance": 0} for i in (1, 2, 3)])

    op.execute("SELECT setval(pg_get_serial_sequence('models', 'id'), (SELECT max(id) FROM models))")
    op.execute("SELECT setval(pg_get_serial_sequence('users', 'id'), (SELECT max(id) FROM users))")


def downgrade() -> None:
    op.execute("DELETE FROM users WHERE id IN (1, 2, 3)")
    op.execute("DELETE FROM legs")
    op.execute("DELETE FROM models")