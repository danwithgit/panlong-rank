from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class TradingCalendar(Base, TimestampMixin):
    __tablename__ = "trading_calendar"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_date: Mapped[str] = mapped_column(String(10), unique=True, index=True, nullable=False)
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False)
    pretrade_date: Mapped[str] = mapped_column(String(10), nullable=False)


class IndexSnapshot(Base):
    __tablename__ = "index_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    index_code: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    index_name: Mapped[str] = mapped_column(String(80), nullable=False)
    current_price: Mapped[float] = mapped_column(Float, nullable=False)
    change_value: Mapped[float] = mapped_column(Float, nullable=False)
    change_percent: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    turnover: Mapped[float] = mapped_column(Float, nullable=False)
    snapshot_time: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    trade_date: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    data_source: Mapped[str] = mapped_column(String(40), nullable=False)


class StockSnapshot(Base):
    __tablename__ = "stock_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    stock_name: Mapped[str] = mapped_column(String(80), nullable=False)
    sector_code: Mapped[Optional[str]] = mapped_column(String(24), index=True, nullable=True)
    sector_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    current_price: Mapped[float] = mapped_column(Float, nullable=False)
    change_percent: Mapped[float] = mapped_column(Float, nullable=False)
    change_value: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    turnover: Mapped[float] = mapped_column(Float, nullable=False)
    fund_amount: Mapped[float] = mapped_column(Float, nullable=False)
    high_price: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    low_price: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    open_price: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    previous_close: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    snapshot_time: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    trade_date: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    data_source: Mapped[str] = mapped_column(String(40), nullable=False)


class SectorSnapshot(Base):
    __tablename__ = "sector_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sector_code: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    sector_name: Mapped[str] = mapped_column(String(80), nullable=False)
    change_percent: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    turnover: Mapped[float] = mapped_column(Float, nullable=False)
    fund_amount: Mapped[float] = mapped_column(Float, nullable=False)
    leader_stock_code: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    leader_stock_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    snapshot_time: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    trade_date: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    data_source: Mapped[str] = mapped_column(String(40), nullable=False)


class StockUniverse(Base, TimestampMixin):
    __tablename__ = "stock_universe"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(24), unique=True, index=True, nullable=False)
    stock_name: Mapped[str] = mapped_column(String(80), nullable=False)
    market: Mapped[str] = mapped_column(String(8), index=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
    last_seen_date: Mapped[str] = mapped_column(String(10), index=True, nullable=False)


class StockSectorMap(Base, TimestampMixin):
    __tablename__ = "stock_sector_map"
    __table_args__ = (UniqueConstraint("stock_code", "sector_code", name="uq_stock_sector"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    stock_name: Mapped[str] = mapped_column(String(80), nullable=False)
    sector_code: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    sector_name: Mapped[str] = mapped_column(String(80), nullable=False)
    sector_type: Mapped[str] = mapped_column(String(24), default="industry", nullable=False)


class SectorLeaderConfig(Base, TimestampMixin):
    __tablename__ = "sector_leader_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sector_code: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    sector_name: Mapped[str] = mapped_column(String(80), nullable=False)
    stock_code: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    stock_name: Mapped[str] = mapped_column(String(80), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Ranking(Base):
    __tablename__ = "rankings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_date: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    period_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    period_start: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    period_end: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    rank_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    sector_code: Mapped[Optional[str]] = mapped_column(String(24), index=True, nullable=True)
    sector_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    stock_code: Mapped[Optional[str]] = mapped_column(String(24), index=True, nullable=True)
    stock_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    rank_no: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    change_percent: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    volume: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    turnover: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    fund_amount: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    snapshot_time: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class DailyAggregate(Base):
    __tablename__ = "daily_aggregates"
    __table_args__ = (
        UniqueConstraint("trade_date", "target_type", "target_code", "sector_code", name="uq_daily_target_sector"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_date: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    target_type: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    target_code: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    target_name: Mapped[str] = mapped_column(String(80), nullable=False)
    sector_code: Mapped[Optional[str]] = mapped_column(String(24), index=True, nullable=True)
    sector_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    open_price: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    close_price: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    high_price: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    low_price: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    change_percent: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    volume: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    turnover: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    fund_amount: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    snapshot_time: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    data_source: Mapped[str] = mapped_column(String(40), nullable=False)
    data_quality: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class WeeklyAggregate(Base):
    __tablename__ = "weekly_aggregates"
    __table_args__ = (
        UniqueConstraint("week_start", "week_end", "target_type", "target_code", "sector_code", name="uq_weekly_target_sector"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    week_start: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    week_end: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    target_type: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    target_code: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    target_name: Mapped[str] = mapped_column(String(80), nullable=False)
    sector_code: Mapped[Optional[str]] = mapped_column(String(24), index=True, nullable=True)
    sector_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    open_price: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    close_price: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    high_price: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    low_price: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    change_percent: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    volume: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    turnover: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    fund_amount: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    trading_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expected_trading_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missing_trading_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    data_source: Mapped[str] = mapped_column(String(40), nullable=False)
    data_quality: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class BackfillTask(Base):
    __tablename__ = "backfill_tasks"
    __table_args__ = (
        UniqueConstraint("task_type", "target_type", "target_code", "sector_code", "trade_date", name="uq_backfill_task"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    target_type: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    target_code: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    target_name: Mapped[str] = mapped_column(String(80), nullable=False)
    sector_code: Mapped[Optional[str]] = mapped_column(String(24), index=True, nullable=True)
    sector_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    trade_date: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), index=True, default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime, index=True, default=datetime.utcnow, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class JobLog(Base):
    __tablename__ = "job_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_name: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rows_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
