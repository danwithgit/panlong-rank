from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import fcntl
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.tables import JobLog
from app.models import MarketSnapshot
from app.services.aggregates import rebuild_daily_aggregate, rebuild_recent_weekly_aggregates, trim_aggregate_history
from app.services.calendar import get_trading_status
from app.services.provider import get_provider
from app.services.snapshot_store import save_snapshot, trim_old_snapshots
from app.services.stock_metadata import load_stock_context


def collect_market_snapshot(db: Session, settings: Settings, force: bool = False) -> MarketSnapshot:
    with _collection_lock(settings.collection_lock_path):
        return _collect_market_snapshot(db, settings, force=force)


def _collect_market_snapshot(db: Session, settings: Settings, force: bool = False) -> MarketSnapshot:
    started_at = datetime.utcnow()
    if _is_rate_limited(db, settings, started_at, force):
        raise RuntimeError(f"collection rate limited, retry after {settings.min_collect_interval_seconds} seconds")

    job = JobLog(job_name="collect_market_snapshot", status="running", started_at=started_at, rows_count=0)
    db.add(job)
    db.commit()
    job_id = job.id
    try:
        status = get_trading_status(settings)
        if not status.is_trade_day and not force:
            _finish_job(db, job_id, status="skipped", rows_count=0, error_message=None)
            db.commit()
            raise RuntimeError(status.message or "non-trade day, collection skipped")

        provider = get_provider(settings)
        configure_stock_context = getattr(provider, "configure_stock_context", None)
        if configure_stock_context is not None:
            configure_stock_context(*load_stock_context(db))
        snapshot = provider.snapshot(status)
        rows = save_snapshot(db, snapshot, settings.data_provider)
        trade_date = snapshot.trading_status.last_trade_date if not snapshot.trading_status.is_trade_day else snapshot.trading_status.trade_date
        rows += rebuild_daily_aggregate(db, trade_date)
        rows += rebuild_recent_weekly_aggregates(db, max_weeks=1)
        trim_old_snapshots(db, keep_trade_dates=settings.snapshot_keep_trade_dates)
        trim_aggregate_history(db, keep_days=settings.aggregate_keep_trade_days)
        _finish_job(db, job_id, status="success", rows_count=rows, error_message=None)
        db.commit()
        return snapshot
    except Exception as exc:
        db.rollback()
        _finish_job(db, job_id, status="failed", rows_count=0, error_message=str(exc))
        db.commit()
        raise


def _finish_job(db: Session, job_id: int, status: str, rows_count: int, error_message: str | None) -> None:
    job = db.get(JobLog, job_id)
    if job is None:
        job = JobLog(job_name="collect_market_snapshot", status=status, started_at=datetime.utcnow())
        db.add(job)
    job.status = status
    job.rows_count = rows_count
    job.error_message = error_message
    job.finished_at = datetime.utcnow()


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


@contextmanager
def _collection_lock(path: str):
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("collection already running") from exc
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
