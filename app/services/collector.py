from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.tables import JobLog
from app.models import MarketSnapshot
from app.services.aggregates import rebuild_daily_aggregate, rebuild_recent_weekly_aggregates, trim_aggregate_history
from app.services.calendar import get_trading_status
from app.services.provider import get_provider
from app.services.snapshot_store import save_snapshot, trim_old_snapshots


def collect_market_snapshot(db: Session, settings: Settings, force: bool = False) -> MarketSnapshot:
    started_at = datetime.utcnow()
    if _is_rate_limited(db, settings, started_at, force):
        raise RuntimeError(f"collection rate limited, retry after {settings.min_collect_interval_seconds} seconds")

    job = JobLog(job_name="collect_market_snapshot", status="running", started_at=started_at, rows_count=0)
    db.add(job)
    db.flush()
    try:
        status = get_trading_status(settings)
        if not status.is_trade_day and not force:
            job.status = "skipped"
            job.finished_at = datetime.utcnow()
            db.commit()
            raise RuntimeError(status.message or "non-trade day, collection skipped")

        provider = get_provider(settings)
        snapshot = provider.snapshot(status)
        rows = save_snapshot(db, snapshot, settings.data_provider)
        trade_date = snapshot.trading_status.last_trade_date if not snapshot.trading_status.is_trade_day else snapshot.trading_status.trade_date
        rows += rebuild_daily_aggregate(db, trade_date)
        rows += rebuild_recent_weekly_aggregates(db)
        trim_old_snapshots(db, keep_trade_dates=settings.snapshot_keep_trade_dates)
        trim_aggregate_history(db, keep_days=settings.aggregate_keep_trade_days)
        job.status = "success"
        job.rows_count = rows
        job.finished_at = datetime.utcnow()
        db.commit()
        return snapshot
    except Exception as exc:
        db.rollback()
        failed = JobLog(
            job_name="collect_market_snapshot",
            status="failed",
            started_at=started_at,
            finished_at=datetime.utcnow(),
            error_message=str(exc),
            rows_count=0,
        )
        db.add(failed)
        db.commit()
        raise


def _is_rate_limited(db: Session, settings: Settings, now: datetime, force: bool) -> bool:
    if force:
        return False
    latest = db.scalar(
        select(JobLog)
        .where(JobLog.job_name == "collect_market_snapshot")
        .order_by(JobLog.started_at.desc(), JobLog.id.desc())
        .limit(1)
    )
    if latest is None:
        return False
    elapsed = (now - latest.started_at).total_seconds()
    return elapsed < settings.min_collect_interval_seconds
