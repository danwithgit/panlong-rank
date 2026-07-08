from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
import time
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.tables import BackfillTask, DailyAggregate, StockSectorMap
from app.services.aggregates import QUALITY_BACKFILLED, QUALITY_PARTIAL, rebuild_recent_weekly_aggregates, trim_aggregate_history

CN_TZ = ZoneInfo("Asia/Shanghai")


def seed_stock_daily_backfill_tasks(db: Session, settings: Settings) -> int:
    if not settings.backfill_enabled:
        return 0
    dates = _recent_trade_dates(settings.aggregate_keep_trade_days)
    created = seed_index_daily_backfill_tasks(db, settings, dates=dates)
    mappings = list(
        db.scalars(
            select(StockSectorMap)
            .order_by(StockSectorMap.updated_at.desc(), StockSectorMap.stock_code.asc())
            .limit(max(settings.backfill_batch_size * 20, 60))
        )
    )
    for mapping in mappings:
        if not _is_supported_stock_code(mapping.stock_code):
            continue
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
    db.flush()
    return created


def seed_index_daily_backfill_tasks(db: Session, settings: Settings, dates: list[str] | None = None) -> int:
    if not settings.backfill_enabled:
        return 0
    created = 0
    for trade_date in dates or _recent_trade_dates(settings.aggregate_keep_trade_days):
        if _has_daily_target(db, "index", "000001", trade_date):
            continue
        existing = db.scalar(
            select(BackfillTask).where(
                BackfillTask.task_type == "daily_hist",
                BackfillTask.target_type == "index",
                BackfillTask.target_code == "000001",
                BackfillTask.trade_date == trade_date,
            )
        )
        if existing is not None:
            continue
        db.add(
            BackfillTask(
                task_type="daily_hist",
                target_type="index",
                target_code="000001",
                target_name="上证指数",
                trade_date=trade_date,
                status="pending",
                next_run_at=datetime.utcnow(),
            )
        )
        created += 1
    db.flush()
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
    processed = succeeded = failed = skipped = 0
    for task in tasks:
        processed += 1
        if not _is_likely_trade_date(task.trade_date):
            task.status = "skipped"
            task.last_error = "non-trade date skipped by calendar filter"
            skipped += 1
            db.commit()
            continue
        if task.target_type == "stock" and not _is_supported_stock_code(task.target_code):
            task.status = "skipped"
            task.last_error = "unsupported stock code for A-share history backfill"
            skipped += 1
            db.commit()
            continue
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
    return {"processed": processed, "succeeded": succeeded, "failed": failed, "skipped": skipped}


def _run_task(db: Session, task: BackfillTask) -> None:
    if task.task_type == "daily_hist" and task.target_type == "index":
        _backfill_index_daily(db, task)
        return
    if task.task_type == "daily_hist" and task.target_type == "stock":
        _backfill_stock_daily(db, task)
        _rebuild_partial_sector_from_backfilled_stocks(db, task.trade_date)
        return
    raise RuntimeError(f"unsupported backfill task: {task.task_type}/{task.target_type}")


def _backfill_index_daily(db: Session, task: BackfillTask) -> None:
    import akshare as ak

    df = ak.stock_zh_index_daily(symbol="sh000001")
    if df.empty:
        raise RuntimeError("empty index history")
    row = _row_for_date(df, task.trade_date)
    if row is None:
        raise RuntimeError("empty index history for trade date")
    close_price = _num(row, ["close", "收盘"])
    open_price = _num(row, ["open", "开盘"]) or close_price
    values = {
        "target_name": task.target_name,
        "open_price": open_price,
        "close_price": close_price,
        "high_price": _num(row, ["high", "最高"]) or close_price,
        "low_price": _num(row, ["low", "最低"]) or close_price,
        "change_percent": _change_percent(open_price, close_price),
        "volume": _num(row, ["volume", "成交量"]),
        "turnover": _num(row, ["amount", "成交额"]),
        "fund_amount": _num(row, ["amount", "成交额"]),
        "snapshot_time": datetime.strptime(task.trade_date + " 15:00:00", "%Y-%m-%d %H:%M:%S"),
        "data_source": "akshare_index_hist",
        "data_quality": QUALITY_BACKFILLED,
    }
    _upsert_daily_aggregate(
        db,
        trade_date=task.trade_date,
        target_type="index",
        target_code=task.target_code,
        sector_code=None,
        values=values,
    )


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
        if not _is_likely_trade_date(task.trade_date):
            return
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
    _upsert_daily_aggregate(
        db,
        trade_date=task.trade_date,
        target_type="stock",
        target_code=task.target_code,
        sector_code=task.sector_code,
        values=values,
    )


def _has_daily_stock(db: Session, stock_code: str, sector_code: str, trade_date: str) -> bool:
    return _has_daily_target(db, "stock", stock_code, trade_date, sector_code=sector_code)


def _has_daily_target(
    db: Session,
    target_type: str,
    target_code: str,
    trade_date: str,
    sector_code: str | None = None,
) -> bool:
    stmt = select(DailyAggregate.id).where(
        DailyAggregate.trade_date == trade_date,
        DailyAggregate.target_type == target_type,
        DailyAggregate.target_code == target_code,
    )
    if sector_code is not None:
        stmt = stmt.where(DailyAggregate.sector_code == sector_code)
    return bool(
        db.scalar(
            stmt.limit(1)
        )
    )


def _recent_trade_dates(days: int) -> list[str]:
    dates = _akshare_trade_dates(days)
    if dates:
        return dates
    today = datetime.now(CN_TZ).date()
    fallback = []
    current = today
    while len(fallback) < days:
        if current.weekday() < 5:
            fallback.append(current.isoformat())
        current -= timedelta(days=1)
    return fallback


def _akshare_trade_dates(days: int) -> list[str]:
    try:
        import akshare as ak

        df = ak.tool_trade_date_hist_sina()
    except Exception:
        return []
    if df.empty:
        return []
    today = datetime.now(CN_TZ).date()
    values: list[str] = []
    for item in df.iloc[:, 0].tolist():
        parsed = _parse_date_value(item)
        if parsed is None or parsed > today:
            continue
        values.append(parsed.isoformat())
    return sorted(set(values), reverse=True)[:days]


def _is_likely_trade_date(value: str) -> bool:
    parsed = _parse_date_value(value)
    if parsed is None:
        return False
    known_trade_dates = _akshare_trade_date_set()
    if known_trade_dates:
        return value in known_trade_dates
    return parsed.weekday() < 5


@lru_cache(maxsize=1)
def _akshare_trade_date_set() -> set[str]:
    return set(_akshare_trade_dates(366))


def _row_for_date(df, trade_date: str):
    for column in ["date", "日期"]:
        if column not in df.columns:
            continue
        mask = df[column].map(_date_key)
        rows = df[mask == trade_date]
        if not rows.empty:
            return rows.iloc[-1]
    return None


def _date_key(value) -> str:
    parsed = _parse_date_value(value)
    return parsed.isoformat() if parsed else ""


def _rebuild_partial_sector_from_backfilled_stocks(db: Session, trade_date: str) -> int:
    stock_rows = list(
        db.scalars(
            select(DailyAggregate)
            .where(DailyAggregate.trade_date == trade_date, DailyAggregate.target_type == "stock")
            .order_by(DailyAggregate.sector_code, DailyAggregate.turnover.desc())
        )
    )
    grouped: dict[str, list[DailyAggregate]] = {}
    for row in stock_rows:
        if not row.sector_code:
            continue
        grouped.setdefault(row.sector_code, []).append(row)
    rows = 0
    for sector_code, items in grouped.items():
        first = items[0]
        values = {
            "target_name": first.sector_name or sector_code,
            "open_price": 0,
            "close_price": 0,
            "high_price": 0,
            "low_price": 0,
            "change_percent": sum(item.change_percent for item in items) / len(items),
            "volume": sum(item.volume for item in items),
            "turnover": sum(item.turnover for item in items),
            "fund_amount": sum(item.fund_amount for item in items),
            "snapshot_time": datetime.strptime(trade_date + " 15:00:00", "%Y-%m-%d %H:%M:%S"),
            "data_source": "akshare_hist_partial",
            "data_quality": QUALITY_PARTIAL,
        }
        _upsert_daily_aggregate(
            db,
            trade_date=trade_date,
            target_type="sector",
            target_code=sector_code,
            sector_code=None,
            values=values,
        )
        rows += 1
    return rows


def _upsert_daily_aggregate(
    db: Session,
    trade_date: str,
    target_type: str,
    target_code: str,
    sector_code: Optional[str],
    values: dict,
) -> None:
    stmt = select(DailyAggregate).where(
        DailyAggregate.trade_date == trade_date,
        DailyAggregate.target_type == target_type,
        DailyAggregate.target_code == target_code,
    )
    if sector_code is None:
        stmt = stmt.where(DailyAggregate.sector_code.is_(None))
    else:
        stmt = stmt.where(DailyAggregate.sector_code == sector_code)
    existing = db.scalar(stmt)
    if existing is None:
        db.add(
            DailyAggregate(
                trade_date=trade_date,
                target_type=target_type,
                target_code=target_code,
                **values,
            )
        )
        db.flush()
        return
    for key, value in values.items():
        setattr(existing, key, value)
    db.flush()


def _parse_date_value(value) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _change_percent(open_price: float, close_price: float) -> float:
    if open_price <= 0:
        return 0.0
    return round((close_price - open_price) / open_price * 100, 4)


def _is_supported_stock_code(code: str) -> bool:
    normalized = code.strip()
    return normalized.startswith(("000", "001", "002", "003", "300", "301", "600", "601", "603", "605", "688", "689", "8", "4"))


def _num(row, columns: list[str]) -> float:
    for column in columns:
        if column in row:
            try:
                return float(row[column])
            except (TypeError, ValueError):
                return 0.0
    return 0.0
