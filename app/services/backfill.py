from __future__ import annotations

from datetime import datetime, timedelta
import time
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.tables import BackfillTask, DailyAggregate, StockSectorMap
from app.services.aggregates import QUALITY_BACKFILLED, rebuild_recent_weekly_aggregates, trim_aggregate_history

CN_TZ = ZoneInfo("Asia/Shanghai")


def seed_stock_daily_backfill_tasks(db: Session, settings: Settings) -> int:
    if not settings.backfill_enabled:
        return 0
    dates = _recent_calendar_dates(settings.aggregate_keep_trade_days)
    mappings = list(
        db.scalars(
            select(StockSectorMap)
            .order_by(StockSectorMap.updated_at.desc(), StockSectorMap.stock_code.asc())
            .limit(max(settings.backfill_batch_size * 20, 60))
        )
    )
    created = 0
    for mapping in mappings:
        for trade_date in dates:
            if _has_daily_stock(db, mapping.stock_code, mapping.sector_code, trade_date):
                continue
            existing = db.scalar(
                select(BackfillTask).where(
                    BackfillTask.task_type == "daily_hist",
                    BackfillTask.target_type == "stock",
                    BackfillTask.target_code == mapping.stock_code,
                    BackfillTask.sector_code == mapping.sector_code,
                    BackfillTask.trade_date == trade_date,
                )
            )
            if existing is not None:
                continue
            db.add(
                BackfillTask(
                    task_type="daily_hist",
                    target_type="stock",
                    target_code=mapping.stock_code,
                    target_name=mapping.stock_name,
                    sector_code=mapping.sector_code,
                    sector_name=mapping.sector_name,
                    trade_date=trade_date,
                    status="pending",
                    next_run_at=datetime.utcnow(),
                )
            )
            created += 1
    return created


def run_backfill_batch(db: Session, settings: Settings) -> dict:
    if not settings.backfill_enabled:
        return {"processed": 0, "succeeded": 0, "failed": 0}
    now = datetime.utcnow()
    tasks = list(
        db.scalars(
            select(BackfillTask)
            .where(
                BackfillTask.status.in_(["pending", "failed"]),
                BackfillTask.next_run_at <= now,
                BackfillTask.attempts < settings.backfill_max_attempts,
            )
            .order_by(BackfillTask.next_run_at.asc(), BackfillTask.id.asc())
            .limit(settings.backfill_batch_size)
        )
    )
    processed = succeeded = failed = 0
    for task in tasks:
        processed += 1
        try:
            _run_task(db, task)
            task.status = "success"
            task.last_error = None
            succeeded += 1
            db.commit()
        except Exception as exc:
            db.rollback()
            task = db.get(BackfillTask, task.id)
            if task is not None:
                task.status = "failed"
                task.attempts += 1
                task.last_error = str(exc)
                task.next_run_at = datetime.utcnow() + timedelta(minutes=min(60, 2**task.attempts))
                db.commit()
            failed += 1
        time.sleep(0.8)
    if succeeded:
        rebuild_recent_weekly_aggregates(db)
        trim_aggregate_history(db, keep_days=settings.aggregate_keep_trade_days)
        db.commit()
    return {"processed": processed, "succeeded": succeeded, "failed": failed}


def _run_task(db: Session, task: BackfillTask) -> None:
    if task.task_type == "daily_hist" and task.target_type == "stock":
        _backfill_stock_daily(db, task)
        return
    raise RuntimeError(f"unsupported backfill task: {task.task_type}/{task.target_type}")


def _backfill_stock_daily(db: Session, task: BackfillTask) -> None:
    import akshare as ak

    trade_key = task.trade_date.replace("-", "")
    df = ak.stock_zh_a_hist(
        symbol=task.target_code,
        period="daily",
        start_date=trade_key,
        end_date=trade_key,
        adjust="",
        timeout=12,
    )
    if df.empty:
        raise RuntimeError("empty daily history")
    row = df.iloc[-1]
    values = {
        "target_name": task.target_name,
        "sector_code": task.sector_code,
        "sector_name": task.sector_name,
        "open_price": _num(row, ["开盘", "open"]),
        "close_price": _num(row, ["收盘", "close"]),
        "high_price": _num(row, ["最高", "high"]),
        "low_price": _num(row, ["最低", "low"]),
        "change_percent": _num(row, ["涨跌幅", "change_percent"]),
        "volume": _num(row, ["成交量", "volume"]),
        "turnover": _num(row, ["成交额", "turnover"]),
        "fund_amount": _num(row, ["成交额", "turnover"]),
        "snapshot_time": datetime.strptime(task.trade_date + " 15:00:00", "%Y-%m-%d %H:%M:%S"),
        "data_source": "akshare_hist",
        "data_quality": QUALITY_BACKFILLED,
    }
    existing = db.scalar(
        select(DailyAggregate).where(
            DailyAggregate.trade_date == task.trade_date,
            DailyAggregate.target_type == "stock",
            DailyAggregate.target_code == task.target_code,
            DailyAggregate.sector_code == task.sector_code,
        )
    )
    if existing is None:
        db.add(
            DailyAggregate(
                trade_date=task.trade_date,
                target_type="stock",
                target_code=task.target_code,
                **values,
            )
        )
        return
    for key, value in values.items():
        setattr(existing, key, value)


def _has_daily_stock(db: Session, stock_code: str, sector_code: str, trade_date: str) -> bool:
    return bool(
        db.scalar(
            select(DailyAggregate.id)
            .where(
                DailyAggregate.trade_date == trade_date,
                DailyAggregate.target_type == "stock",
                DailyAggregate.target_code == stock_code,
                DailyAggregate.sector_code == sector_code,
            )
            .limit(1)
        )
    )


def _recent_calendar_dates(days: int) -> list[str]:
    today = datetime.now(CN_TZ).date()
    dates = []
    current = today
    while len(dates) < days:
        if current.weekday() < 5:
            dates.append(current.isoformat())
        current -= timedelta(days=1)
    return dates


def _num(row, columns: list[str]) -> float:
    for column in columns:
        if column in row:
            try:
                return float(row[column])
            except (TypeError, ValueError):
                return 0.0
    return 0.0
