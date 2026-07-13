"""add snapshot sector and weekly quality fields

Revision ID: 0003_snapshot_quality
Revises: 0002_stock_universe
Create Date: 2026-07-13
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_snapshot_quality"
down_revision = "0002_stock_universe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "stock_snapshots" in tables:
        stock_columns = {column["name"] for column in inspector.get_columns("stock_snapshots")}
        if "sector_code" not in stock_columns:
            op.add_column("stock_snapshots", sa.Column("sector_code", sa.String(length=24), nullable=True))
            op.create_index("ix_stock_snapshots_sector_code", "stock_snapshots", ["sector_code"])
        if "sector_name" not in stock_columns:
            op.add_column("stock_snapshots", sa.Column("sector_name", sa.String(length=80), nullable=True))

    if "daily_aggregates" not in tables:
        op.create_table(
            "daily_aggregates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("trade_date", sa.String(length=10), nullable=False),
            sa.Column("target_type", sa.String(length=24), nullable=False),
            sa.Column("target_code", sa.String(length=24), nullable=False),
            sa.Column("target_name", sa.String(length=80), nullable=False),
            sa.Column("sector_code", sa.String(length=24), nullable=True),
            sa.Column("sector_name", sa.String(length=80), nullable=True),
            sa.Column("open_price", sa.Float(), nullable=False),
            sa.Column("close_price", sa.Float(), nullable=False),
            sa.Column("high_price", sa.Float(), nullable=False),
            sa.Column("low_price", sa.Float(), nullable=False),
            sa.Column("change_percent", sa.Float(), nullable=False),
            sa.Column("volume", sa.Float(), nullable=False),
            sa.Column("turnover", sa.Float(), nullable=False),
            sa.Column("fund_amount", sa.Float(), nullable=False),
            sa.Column("snapshot_time", sa.DateTime(), nullable=False),
            sa.Column("data_source", sa.String(length=40), nullable=False),
            sa.Column("data_quality", sa.String(length=24), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("trade_date", "target_type", "target_code", "sector_code", name="uq_daily_target_sector"),
        )
        op.create_index("ix_daily_aggregates_trade_date", "daily_aggregates", ["trade_date"])
        op.create_index("ix_daily_aggregates_target_type", "daily_aggregates", ["target_type"])
        op.create_index("ix_daily_aggregates_target_code", "daily_aggregates", ["target_code"])
        op.create_index("ix_daily_aggregates_sector_code", "daily_aggregates", ["sector_code"])
        op.create_index("ix_daily_aggregates_snapshot_time", "daily_aggregates", ["snapshot_time"])
        op.create_index("ix_daily_aggregates_data_quality", "daily_aggregates", ["data_quality"])

    if "weekly_aggregates" not in tables:
        op.create_table(
            "weekly_aggregates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("week_start", sa.String(length=10), nullable=False),
            sa.Column("week_end", sa.String(length=10), nullable=False),
            sa.Column("target_type", sa.String(length=24), nullable=False),
            sa.Column("target_code", sa.String(length=24), nullable=False),
            sa.Column("target_name", sa.String(length=80), nullable=False),
            sa.Column("sector_code", sa.String(length=24), nullable=True),
            sa.Column("sector_name", sa.String(length=80), nullable=True),
            sa.Column("open_price", sa.Float(), nullable=False),
            sa.Column("close_price", sa.Float(), nullable=False),
            sa.Column("high_price", sa.Float(), nullable=False),
            sa.Column("low_price", sa.Float(), nullable=False),
            sa.Column("change_percent", sa.Float(), nullable=False),
            sa.Column("volume", sa.Float(), nullable=False),
            sa.Column("turnover", sa.Float(), nullable=False),
            sa.Column("fund_amount", sa.Float(), nullable=False),
            sa.Column("trading_days", sa.Integer(), nullable=False),
            sa.Column("expected_trading_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("missing_trading_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("data_source", sa.String(length=40), nullable=False),
            sa.Column("data_quality", sa.String(length=24), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("week_start", "week_end", "target_type", "target_code", "sector_code", name="uq_weekly_target_sector"),
        )
        op.create_index("ix_weekly_aggregates_week_start", "weekly_aggregates", ["week_start"])
        op.create_index("ix_weekly_aggregates_week_end", "weekly_aggregates", ["week_end"])
        op.create_index("ix_weekly_aggregates_target_type", "weekly_aggregates", ["target_type"])
        op.create_index("ix_weekly_aggregates_target_code", "weekly_aggregates", ["target_code"])
        op.create_index("ix_weekly_aggregates_sector_code", "weekly_aggregates", ["sector_code"])
        op.create_index("ix_weekly_aggregates_data_quality", "weekly_aggregates", ["data_quality"])
    else:
        weekly_columns = {column["name"] for column in inspector.get_columns("weekly_aggregates")}
        if "expected_trading_days" not in weekly_columns:
            op.add_column(
                "weekly_aggregates",
                sa.Column("expected_trading_days", sa.Integer(), nullable=False, server_default="0"),
            )
        if "missing_trading_days" not in weekly_columns:
            op.add_column(
                "weekly_aggregates",
                sa.Column("missing_trading_days", sa.Integer(), nullable=False, server_default="0"),
            )

    if "backfill_tasks" not in tables:
        op.create_table(
            "backfill_tasks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("task_type", sa.String(length=32), nullable=False),
            sa.Column("target_type", sa.String(length=24), nullable=False),
            sa.Column("target_code", sa.String(length=24), nullable=False),
            sa.Column("target_name", sa.String(length=80), nullable=False),
            sa.Column("sector_code", sa.String(length=24), nullable=True),
            sa.Column("sector_name", sa.String(length=80), nullable=True),
            sa.Column("trade_date", sa.String(length=10), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("next_run_at", sa.DateTime(), nullable=False),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("task_type", "target_type", "target_code", "sector_code", "trade_date", name="uq_backfill_task"),
        )
        op.create_index("ix_backfill_tasks_task_type", "backfill_tasks", ["task_type"])
        op.create_index("ix_backfill_tasks_target_type", "backfill_tasks", ["target_type"])
        op.create_index("ix_backfill_tasks_target_code", "backfill_tasks", ["target_code"])
        op.create_index("ix_backfill_tasks_sector_code", "backfill_tasks", ["sector_code"])
        op.create_index("ix_backfill_tasks_trade_date", "backfill_tasks", ["trade_date"])
        op.create_index("ix_backfill_tasks_status", "backfill_tasks", ["status"])
        op.create_index("ix_backfill_tasks_next_run_at", "backfill_tasks", ["next_run_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "weekly_aggregates" in tables:
        columns = {column["name"] for column in inspector.get_columns("weekly_aggregates")}
        if "missing_trading_days" in columns:
            op.drop_column("weekly_aggregates", "missing_trading_days")
        if "expected_trading_days" in columns:
            op.drop_column("weekly_aggregates", "expected_trading_days")
    if "stock_snapshots" in tables:
        columns = {column["name"] for column in inspector.get_columns("stock_snapshots")}
        if "sector_code" in columns:
            op.drop_index("ix_stock_snapshots_sector_code", table_name="stock_snapshots")
            op.drop_column("stock_snapshots", "sector_code")
        if "sector_name" in columns:
            op.drop_column("stock_snapshots", "sector_name")
