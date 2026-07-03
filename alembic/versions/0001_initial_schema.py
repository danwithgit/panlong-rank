"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trading_calendar",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trade_date", sa.String(length=10), nullable=False, unique=True),
        sa.Column("is_open", sa.Boolean(), nullable=False),
        sa.Column("pretrade_date", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_trading_calendar_trade_date", "trading_calendar", ["trade_date"])

    op.create_table(
        "index_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("index_code", sa.String(length=24), nullable=False),
        sa.Column("index_name", sa.String(length=80), nullable=False),
        sa.Column("current_price", sa.Float(), nullable=False),
        sa.Column("change_value", sa.Float(), nullable=False),
        sa.Column("change_percent", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("turnover", sa.Float(), nullable=False),
        sa.Column("snapshot_time", sa.DateTime(), nullable=False),
        sa.Column("trade_date", sa.String(length=10), nullable=False),
        sa.Column("data_source", sa.String(length=40), nullable=False),
    )
    op.create_index("ix_index_snapshots_index_code", "index_snapshots", ["index_code"])
    op.create_index("ix_index_snapshots_snapshot_time", "index_snapshots", ["snapshot_time"])
    op.create_index("ix_index_snapshots_trade_date", "index_snapshots", ["trade_date"])

    op.create_table(
        "sector_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sector_code", sa.String(length=24), nullable=False),
        sa.Column("sector_name", sa.String(length=80), nullable=False),
        sa.Column("change_percent", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("turnover", sa.Float(), nullable=False),
        sa.Column("fund_amount", sa.Float(), nullable=False),
        sa.Column("leader_stock_code", sa.String(length=24), nullable=True),
        sa.Column("leader_stock_name", sa.String(length=80), nullable=True),
        sa.Column("snapshot_time", sa.DateTime(), nullable=False),
        sa.Column("trade_date", sa.String(length=10), nullable=False),
        sa.Column("data_source", sa.String(length=40), nullable=False),
    )
    op.create_index("ix_sector_snapshots_sector_code", "sector_snapshots", ["sector_code"])
    op.create_index("ix_sector_snapshots_snapshot_time", "sector_snapshots", ["snapshot_time"])
    op.create_index("ix_sector_snapshots_trade_date", "sector_snapshots", ["trade_date"])

    op.create_table(
        "stock_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stock_code", sa.String(length=24), nullable=False),
        sa.Column("stock_name", sa.String(length=80), nullable=False),
        sa.Column("current_price", sa.Float(), nullable=False),
        sa.Column("change_percent", sa.Float(), nullable=False),
        sa.Column("change_value", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("turnover", sa.Float(), nullable=False),
        sa.Column("fund_amount", sa.Float(), nullable=False),
        sa.Column("high_price", sa.Float(), nullable=False),
        sa.Column("low_price", sa.Float(), nullable=False),
        sa.Column("open_price", sa.Float(), nullable=False),
        sa.Column("previous_close", sa.Float(), nullable=False),
        sa.Column("snapshot_time", sa.DateTime(), nullable=False),
        sa.Column("trade_date", sa.String(length=10), nullable=False),
        sa.Column("data_source", sa.String(length=40), nullable=False),
    )
    op.create_index("ix_stock_snapshots_stock_code", "stock_snapshots", ["stock_code"])
    op.create_index("ix_stock_snapshots_snapshot_time", "stock_snapshots", ["snapshot_time"])
    op.create_index("ix_stock_snapshots_trade_date", "stock_snapshots", ["trade_date"])

    op.create_table(
        "stock_sector_map",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stock_code", sa.String(length=24), nullable=False),
        sa.Column("stock_name", sa.String(length=80), nullable=False),
        sa.Column("sector_code", sa.String(length=24), nullable=False),
        sa.Column("sector_name", sa.String(length=80), nullable=False),
        sa.Column("sector_type", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("stock_code", "sector_code", name="uq_stock_sector"),
    )
    op.create_index("ix_stock_sector_map_stock_code", "stock_sector_map", ["stock_code"])
    op.create_index("ix_stock_sector_map_sector_code", "stock_sector_map", ["sector_code"])

    op.create_table(
        "sector_leader_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sector_code", sa.String(length=24), nullable=False),
        sa.Column("sector_name", sa.String(length=80), nullable=False),
        sa.Column("stock_code", sa.String(length=24), nullable=False),
        sa.Column("stock_name", sa.String(length=80), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sector_leader_config_sector_code", "sector_leader_config", ["sector_code"])
    op.create_index("ix_sector_leader_config_stock_code", "sector_leader_config", ["stock_code"])

    op.create_table(
        "rankings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trade_date", sa.String(length=10), nullable=False),
        sa.Column("period_type", sa.String(length=32), nullable=False),
        sa.Column("period_start", sa.String(length=8), nullable=True),
        sa.Column("period_end", sa.String(length=8), nullable=True),
        sa.Column("rank_type", sa.String(length=32), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("sector_code", sa.String(length=24), nullable=True),
        sa.Column("sector_name", sa.String(length=80), nullable=True),
        sa.Column("stock_code", sa.String(length=24), nullable=True),
        sa.Column("stock_name", sa.String(length=80), nullable=True),
        sa.Column("rank_no", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("change_percent", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("turnover", sa.Float(), nullable=False),
        sa.Column("fund_amount", sa.Float(), nullable=False),
        sa.Column("snapshot_time", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_rankings_trade_date", "rankings", ["trade_date"])
    op.create_index("ix_rankings_period_type", "rankings", ["period_type"])
    op.create_index("ix_rankings_rank_type", "rankings", ["rank_type"])
    op.create_index("ix_rankings_target_type", "rankings", ["target_type"])
    op.create_index("ix_rankings_sector_code", "rankings", ["sector_code"])
    op.create_index("ix_rankings_stock_code", "rankings", ["stock_code"])
    op.create_index("ix_rankings_snapshot_time", "rankings", ["snapshot_time"])

    op.create_table(
        "job_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_name", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("rows_count", sa.Integer(), nullable=False),
    )
    op.create_index("ix_job_logs_job_name", "job_logs", ["job_name"])


def downgrade() -> None:
    op.drop_table("job_logs")
    op.drop_table("rankings")
    op.drop_table("sector_leader_config")
    op.drop_table("stock_sector_map")
    op.drop_table("stock_snapshots")
    op.drop_table("sector_snapshots")
    op.drop_table("index_snapshots")
    op.drop_table("trading_calendar")
