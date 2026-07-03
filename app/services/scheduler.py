from __future__ import annotations

from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import Settings
from app.db.session import SessionLocal
from app.services.calendar import get_trading_status
from app.services.collector import collect_market_snapshot

_scheduler: Optional[BackgroundScheduler] = None


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
    db = SessionLocal()
    try:
        collect_market_snapshot(db, settings, force=False)
    except Exception:
        pass
    finally:
        db.close()
