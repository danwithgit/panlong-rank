from __future__ import annotations

from datetime import datetime, timedelta
from multiprocessing import Process
from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.config import Settings
from app.db.session import SessionLocal
from app.db.tables import JobLog
from app.services.backfill import run_backfill_batch, seed_stock_daily_backfill_tasks
from app.services.calendar import get_trading_status
from app.services.collector import collect_market_snapshot
from app.services.stock_metadata import refresh_stock_metadata, stock_universe_count

_scheduler: Optional[BackgroundScheduler] = None
CN_TZ = ZoneInfo("Asia/Shanghai")


def start_scheduler(settings: Settings) -> None:
    global _scheduler
    if not settings.scheduler_enabled or _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    _scheduler.add_job(
        _scheduled_collect,
        "interval",
        seconds=settings.collect_interval_seconds,
        args=[settings],
        id="collect_market_snapshot",
        replace_existing=True,
        max_instances=1,
        next_run_time=datetime.now(CN_TZ),
    )
    if settings.backfill_enabled:
        _scheduler.add_job(
            _scheduled_backfill,
            "interval",
            seconds=settings.backfill_interval_seconds,
            args=[settings],
            id="backfill_daily_history",
            replace_existing=True,
            max_instances=1,
            next_run_time=datetime.now(CN_TZ) + timedelta(seconds=min(120, settings.backfill_interval_seconds)),
        )
    if settings.metadata_refresh_enabled:
        _scheduler.add_job(
            _scheduled_metadata_refresh,
            "interval",
            seconds=settings.metadata_refresh_interval_seconds,
            args=[settings],
            id="refresh_stock_metadata",
            replace_existing=True,
            max_instances=1,
            next_run_time=datetime.now(CN_TZ) + timedelta(seconds=30),
        )
    _scheduler.start()


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def _scheduled_collect(settings: Settings) -> None:
    status = get_trading_status(settings)
    if not status.is_trade_day or status.session in {"pre_open", "lunch_break", "closed"}:
        return
    timeout = max(30, settings.collect_timeout_seconds)
    process = Process(target=_collect_in_child, args=[settings])
    process.start()
    process.join(timeout)
    if process.is_alive():
        process.terminate()
        process.join(5)
        _record_timeout(timeout)


def _collect_in_child(settings: Settings) -> None:
    db = SessionLocal()
    try:
        collect_market_snapshot(db, settings, force=False)
    except Exception:
        pass
    finally:
        db.close()


def _record_timeout(timeout_seconds: int, job_name: str = "collect_market_snapshot") -> None:
    now = datetime.utcnow()
    db = SessionLocal()
    try:
        running_jobs = list(
            db.scalars(
                select(JobLog)
                .where(JobLog.job_name == job_name, JobLog.status == "running")
                .order_by(JobLog.started_at.desc(), JobLog.id.desc())
            )
        )
        if running_jobs:
            for running in running_jobs:
                running.status = "failed"
                running.finished_at = now
                running.error_message = f"collection timed out after {timeout_seconds} seconds"
                running.rows_count = 0
            db.commit()
            return
        db.add(
            JobLog(
                job_name=job_name,
                status="failed",
                started_at=now,
                finished_at=now,
                error_message=f"collection timed out after {timeout_seconds} seconds",
                rows_count=0,
            )
        )
        db.commit()
    finally:
        db.close()


def _scheduled_backfill(settings: Settings) -> None:
    status = get_trading_status(settings)
    if status.is_trade_day and status.session not in {"pre_open", "closed"}:
        return
    db = SessionLocal()
    try:
        seed_stock_daily_backfill_tasks(db, settings)
        db.commit()
        run_backfill_batch(db, settings)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _scheduled_metadata_refresh(settings: Settings) -> None:
    status = get_trading_status(settings)
    refresh_memberships = not status.is_trade_day or status.session in {"pre_open", "closed"}
    if not refresh_memberships:
        db = SessionLocal()
        try:
            if stock_universe_count(db) >= settings.min_realtime_stock_count:
                return
        finally:
            db.close()
    timeout = max(30, settings.metadata_refresh_timeout_seconds)
    process = Process(target=_metadata_in_child, args=(settings, refresh_memberships))
    process.start()
    process.join(timeout)
    if process.is_alive():
        process.terminate()
        process.join(5)
        _record_timeout(timeout, job_name="refresh_stock_metadata")


def _metadata_in_child(settings: Settings, refresh_memberships: bool) -> None:
    db = SessionLocal()
    started_at = datetime.utcnow()
    job = JobLog(job_name="refresh_stock_metadata", status="running", started_at=started_at, rows_count=0)
    db.add(job)
    db.commit()
    try:
        result = refresh_stock_metadata(db, settings, refresh_memberships=refresh_memberships)
        job = db.get(JobLog, job.id)
        job.status = "success"
        job.finished_at = datetime.utcnow()
        job.rows_count = result["universe_rows"] + result["membership_rows"]
        db.commit()
    except Exception as exc:
        db.rollback()
        job = db.get(JobLog, job.id)
        if job is not None:
            job.status = "failed"
            job.finished_at = datetime.utcnow()
            job.error_message = str(exc)
            db.commit()
    finally:
        db.close()
