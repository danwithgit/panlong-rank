from __future__ import annotations

from datetime import datetime, timedelta
from multiprocessing import Process
from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import Settings
from app.db.session import SessionLocal
from app.db.tables import JobLog
from app.services.backfill import run_backfill_batch, seed_stock_daily_backfill_tasks
from app.services.calendar import get_trading_status
from app.services.collector import collect_market_snapshot

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
    _scheduler.start()


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def _scheduled_collect(settings: Settings) -> None:
    status = get_trading_status(settings)
    if not status.is_trade_day or status.session in {"pre_open", "closed"}:
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


def _record_timeout(timeout_seconds: int) -> None:
    now = datetime.utcnow()
    db = SessionLocal()
    try:
        db.add(
            JobLog(
                job_name="collect_market_snapshot",
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
