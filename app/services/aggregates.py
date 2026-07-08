from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Iterable, Optional

from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import Session

from app.db.tables import DailyAggregate, IndexSnapshot, SectorSnapshot, StockSectorMap, StockSnapshot, WeeklyAggregate

QUALITY_LIVE = "live"
QUALITY_BACKFILLED = "backfilled"
QUALITY_PARTIAL = "partial"
QUALITY_MISSING = "missing"


def rebuild_daily_aggregate(db: Session, trade_date: str, data_quality: str = QUALITY_LIVE) -> int:
    db.flush()
    index_row = db.scalar(
        select(IndexSnapshot)
        .where(IndexSnapshot.trade_date == trade_date)
        .order_by(IndexSnapshot.snapshot_time.desc(), IndexSnapshot.id.desc())
        .limit(1)
    )
    if index_row is None:
        return 0

    snapshot_time = index_row.snapshot_time
    db.execute(delete(DailyAggregate).where(DailyAggregate.trade_date == trade_date))
    rows = 0

    db.add(
        DailyAggregate(
            trade_date=trade_date,
            target_type="index",
            target_code=index_row.index_code,
            target_name=index_row.index_name,
            open_price=_first_index_price(db, trade_date) or index_row.current_price,
            close_price=index_row.current_price,
            high_price=index_row.current_price,
            low_price=index_row.current_price,
            change_percent=index_row.change_percent,
            volume=index_row.volume,
            turnover=index_row.turnover,
            fund_amount=index_row.turnover,
            snapshot_time=snapshot_time,
            data_source=index_row.data_source,
            data_quality=data_quality,
        )
    )
    rows += 1

    for sector in db.scalars(
        select(SectorSnapshot)
        .where(SectorSnapshot.trade_date == trade_date, SectorSnapshot.snapshot_time == snapshot_time)
        .order_by(SectorSnapshot.sector_code)
    ):
        db.add(
            DailyAggregate(
                trade_date=trade_date,
                target_type="sector",
                target_code=sector.sector_code,
                target_name=sector.sector_name,
                open_price=0,
                close_price=0,
                high_price=0,
                low_price=0,
                change_percent=sector.change_percent,
                volume=sector.volume,
                turnover=sector.turnover,
                fund_amount=sector.fund_amount,
                snapshot_time=snapshot_time,
                data_source=sector.data_source,
                data_quality=data_quality,
            )
        )
        rows += 1

    stock_rows = db.execute(
        select(StockSnapshot, StockSectorMap)
        .where(StockSnapshot.trade_date == trade_date, StockSnapshot.snapshot_time == snapshot_time)
        .join(StockSectorMap, StockSnapshot.stock_code == StockSectorMap.stock_code)
        .order_by(StockSnapshot.stock_code, StockSectorMap.sector_code)
    ).all()
    seen: set[tuple[str, str]] = set()
    for stock, mapping in stock_rows:
        key = (stock.stock_code, mapping.sector_code)
        if key in seen:
            continue
        seen.add(key)
        db.add(
            DailyAggregate(
                trade_date=trade_date,
                target_type="stock",
                target_code=stock.stock_code,
                target_name=stock.stock_name,
                sector_code=mapping.sector_code,
                sector_name=mapping.sector_name,
                open_price=stock.open_price or stock.current_price,
                close_price=stock.current_price,
                high_price=stock.high_price or stock.current_price,
                low_price=stock.low_price or stock.current_price,
                change_percent=stock.change_percent,
                volume=stock.volume,
                turnover=stock.turnover,
                fund_amount=stock.fund_amount,
                snapshot_time=snapshot_time,
                data_source=stock.data_source,
                data_quality=data_quality,
            )
        )
        rows += 1

    return rows


def rebuild_recent_weekly_aggregates(db: Session, max_weeks: int = 4) -> int:
    db.flush()
    dates = recent_trade_dates(db, max_weeks * 5)
    if not dates:
        return 0
    week_ranges = _recent_week_ranges(dates, max_weeks)
    rows = 0
    for start, end in week_ranges:
        rows += rebuild_weekly_aggregate(db, start, end)
    return rows


def rebuild_weekly_aggregate(db: Session, week_start: str, week_end: str) -> int:
    daily_rows = list(
        db.scalars(
            select(DailyAggregate)
            .where(DailyAggregate.trade_date >= week_start, DailyAggregate.trade_date <= week_end)
            .order_by(DailyAggregate.trade_date.asc(), DailyAggregate.id.asc())
        )
    )
    if not daily_rows:
        return 0

    db.execute(delete(WeeklyAggregate).where(WeeklyAggregate.week_start == week_start, WeeklyAggregate.week_end == week_end))
    grouped: dict[tuple[str, str, Optional[str]], list[DailyAggregate]] = defaultdict(list)
    for row in daily_rows:
        grouped[(row.target_type, row.target_code, row.sector_code)].append(row)

    rows = 0
    for _, items in grouped.items():
        first = items[0]
        last = items[-1]
        quality = _merge_quality(item.data_quality for item in items)
        db.add(
            WeeklyAggregate(
                week_start=week_start,
                week_end=week_end,
                target_type=last.target_type,
                target_code=last.target_code,
                target_name=last.target_name,
                sector_code=last.sector_code,
                sector_name=last.sector_name,
                open_price=first.open_price,
                close_price=last.close_price,
                high_price=max(item.high_price for item in items),
                low_price=min(item.low_price for item in items),
                change_percent=_change_percent(first.open_price, last.close_price, last.change_percent),
                volume=sum(item.volume for item in items),
                turnover=sum(item.turnover for item in items),
                fund_amount=sum(item.fund_amount for item in items),
                trading_days=len({item.trade_date for item in items}),
                data_source="+".join(sorted({item.data_source for item in items})),
                data_quality=quality,
            )
        )
        rows += 1
    db.flush()
    return rows


def recent_trade_dates(db: Session, limit: int) -> list[str]:
    return list(
        db.scalars(
            select(DailyAggregate.trade_date)
            .distinct()
            .order_by(DailyAggregate.trade_date.desc())
            .limit(limit)
        )
    )


def daily_rows_for_date(
    db: Session,
    trade_date: str,
    target_type: str,
    sector_code: Optional[str] = None,
) -> list[DailyAggregate]:
    stmt = select(DailyAggregate).where(DailyAggregate.trade_date == trade_date, DailyAggregate.target_type == target_type)
    if sector_code:
        stmt = stmt.where(DailyAggregate.sector_code == sector_code)
    return list(db.scalars(stmt.order_by(DailyAggregate.turnover.desc())))


def weekly_ranges(db: Session, limit: int = 4) -> list[tuple[str, str]]:
    return list(
        db.execute(
            select(WeeklyAggregate.week_start, WeeklyAggregate.week_end)
            .distinct()
            .order_by(WeeklyAggregate.week_end.desc(), WeeklyAggregate.week_start.desc())
            .limit(limit)
        )
    )


def weekly_rows(
    db: Session,
    week_start: str,
    week_end: str,
    target_type: str,
    sector_code: Optional[str] = None,
) -> list[WeeklyAggregate]:
    stmt = select(WeeklyAggregate).where(
        WeeklyAggregate.week_start == week_start,
        WeeklyAggregate.week_end == week_end,
        WeeklyAggregate.target_type == target_type,
    )
    if sector_code:
        stmt = stmt.where(WeeklyAggregate.sector_code == sector_code)
    return list(db.scalars(stmt.order_by(WeeklyAggregate.turnover.desc())))


def trim_aggregate_history(db: Session, keep_days: int = 30) -> None:
    dates = recent_trade_dates(db, keep_days)
    if not dates:
        return
    db.execute(delete(DailyAggregate).where(DailyAggregate.trade_date.not_in(dates)))
    oldest = min(dates)
    db.execute(delete(WeeklyAggregate).where(WeeklyAggregate.week_end < oldest))


def _first_index_price(db: Session, trade_date: str) -> Optional[float]:
    row = db.scalar(
        select(IndexSnapshot)
        .where(IndexSnapshot.trade_date == trade_date)
        .order_by(IndexSnapshot.snapshot_time.asc(), IndexSnapshot.id.asc())
        .limit(1)
    )
    return row.current_price if row else None


def _recent_week_ranges(desc_dates: list[str], max_weeks: int) -> list[tuple[str, str]]:
    dates = sorted(desc_dates)
    ranges: dict[tuple[int, int], list[str]] = defaultdict(list)
    for value in dates:
        year, week, _ = datetime.strptime(value, "%Y-%m-%d").isocalendar()
        ranges[(year, week)].append(value)
    ordered = sorted(ranges.values(), key=lambda items: items[-1], reverse=True)[:max_weeks]
    return [(items[0], items[-1]) for items in ordered]


def _merge_quality(values: Iterable[str]) -> str:
    qualities = set(values)
    if QUALITY_MISSING in qualities:
        return QUALITY_MISSING
    if QUALITY_PARTIAL in qualities or len(qualities) > 1:
        return QUALITY_PARTIAL
    if QUALITY_BACKFILLED in qualities:
        return QUALITY_BACKFILLED
    return QUALITY_LIVE


def _change_percent(open_price: float, close_price: float, fallback: float) -> float:
    if open_price > 0:
        return round((close_price - open_price) / open_price * 100, 4)
    return fallback
