"""add stock universe

Revision ID: 0002_stock_universe
Revises: 0001_initial_schema
Create Date: 2026-07-10
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_stock_universe"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stock_universe",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stock_code", sa.String(length=24), nullable=False, unique=True),
        sa.Column("stock_name", sa.String(length=80), nullable=False),
        sa.Column("market", sa.String(length=8), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("last_seen_date", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_stock_universe_stock_code", "stock_universe", ["stock_code"])
    op.create_index("ix_stock_universe_market", "stock_universe", ["market"])
    op.create_index("ix_stock_universe_active", "stock_universe", ["active"])
    op.create_index("ix_stock_universe_last_seen_date", "stock_universe", ["last_seen_date"])


def downgrade() -> None:
    op.drop_table("stock_universe")
