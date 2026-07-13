from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.db.tables import DailyAggregate, WeeklyAggregate
from app.models import Timeframe
from app.services.aggregates import daily_rows_for_date, recent_trade_dates, weekly_ranges, weekly_rows
from app.services.ranking_service import build_single_rank, snapshot_for_timeframe_with_settings

RANK_METRICS = {
    "turnover": "turnover",
    "volume": "volume",
    "fund": "fund_amount",
    "change": "change_percent",
}


def recent_daily_options(db: Session, limit: int = 7) -> list[dict]:
    return [{"trade_date": value} for value in recent_trade_dates(db, limit)]


def recent_weekly_options(db: Session, limit: int = 4) -> list[dict]:
    return [
        {"week_start": start, "week_end": end, "label": f"{start} ~ {end}"}
        for start, end in weekly_ranges(db, limit)
    ]


def daily_rank(
    db: Session,
    trade_date: Optional[str],
    target_type: str,
    metric: str,
    limit: int,
    sector_code: Optional[str] = None,
) -> dict:
    selected_date = trade_date or _default_daily_date(db)
    if selected_date is None:
        return {"trade_date": None, "items": [], "data_quality": "missing"}
    rows = daily_rows_for_date(db, selected_date, target_type, sector_code=sector_code)
    return {
        "trade_date": selected_date,
        "target_type": target_type,
        "metric": metric,
        "sector_code": sector_code,
        "items": _rank_rows(rows, metric, limit),
        "data_quality": _quality(rows),
    }


def weekly_rank(
    db: Session,
    week_start: Optional[str],
    week_end: Optional[str],
    target_type: str,
    metric: str,
    limit: int,
    sector_code: Optional[str] = None,
) -> dict:
    if not week_start or not week_end:
        options = weekly_ranges(db, 1)
        if not options:
            return {"week_start": None, "week_end": None, "items": [], "data_quality": "missing"}
        week_start, week_end = options[0]
    rows = weekly_rows(db, week_start, week_end, target_type, sector_code=sector_code)
    return {
        "week_start": week_start,
        "week_end": week_end,
        "label": f"{week_start} ~ {week_end}",
        "target_type": target_type,
        "metric": metric,
        "sector_code": sector_code,
        "items": _rank_rows(rows, metric, limit),
        "data_quality": _quality(rows),
    }


def compare_daily(
    db: Session,
    target_type: str,
    target_code: str,
    trade_date: Optional[str],
    sector_code: Optional[str] = None,
    days: int = 3,
) -> dict:
    dates = recent_trade_dates(db, 30)
    if not dates:
        return {"target_type": target_type, "target_code": target_code, "items": [], "data_quality": "missing"}
    selected = trade_date or dates[0]
    ordered = sorted(dates, reverse=True)
    if selected not in ordered:
        selected = ordered[0]
    start_index = ordered.index(selected)
    compare_dates = ordered[start_index : start_index + days]
    rows = [_find_daily(db, target_type, target_code, item, sector_code=sector_code) for item in compare_dates]
    rows = [row for row in rows if row is not None]
    return {
        "target_type": target_type,
        "target_code": target_code,
        "sector_code": sector_code,
        "trade_date": selected,
        "items": [_compare_item(row, _previous_row(db, row, ordered)) for row in rows],
        "data_quality": _quality(rows),
    }


def compare_timeframe(
    db: Session,
    status,
    settings,
    timeframe: Timeframe,
    target_type: str,
    metric: str,
    limit: int,
    sector_code: Optional[str] = None,
) -> dict:
    snapshot = snapshot_for_timeframe_with_settings(db, status, settings, timeframe)
    if snapshot is None:
        return {
            "timeframe": timeframe.value,
            "target_type": target_type,
            "metric": metric,
            "items": [],
            "data_quality": "missing",
        }
    block = build_single_rank(snapshot, timeframe, metric, target_type, limit, sector_code=sector_code)
    return {
        "timeframe": timeframe.value,
        "trade_date": snapshot.trading_status.trade_date if snapshot.trading_status.is_trade_day else snapshot.trading_status.last_trade_date,
        "target_type": target_type,
        "metric": metric,
        "sector_code": sector_code,
        "items": [item.model_dump(mode="json") for item in block.items],
        "data_quality": "live",
    }


def _default_daily_date(db: Session) -> Optional[str]:
    dates = recent_trade_dates(db, 1)
    return dates[0] if dates else None


def _rank_rows(rows: list, metric: str, limit: int) -> list[dict]:
    attr = RANK_METRICS[metric]
    ranked = sorted(rows, key=lambda row: getattr(row, attr), reverse=True)[:limit]
    return [_row_item(row, rank) for rank, row in enumerate(ranked, start=1)]


def _row_item(row, rank: int) -> dict:
    return {
        "rank": rank,
        "target_type": row.target_type,
        "target_code": row.target_code,
        "target_name": row.target_name,
        "sector_code": row.sector_code,
        "sector_name": row.sector_name,
        "current_price": row.close_price,
        "change_percent": row.change_percent,
        "volume": row.volume,
        "turnover": row.turnover,
        "fund_amount": row.fund_amount,
        "trading_days": getattr(row, "trading_days", None),
        "expected_trading_days": getattr(row, "expected_trading_days", None),
        "missing_trading_days": getattr(row, "missing_trading_days", None),
        "data_quality": row.data_quality,
        "data_source": row.data_source,
    }


def _compare_item(row: DailyAggregate, previous: Optional[DailyAggregate]) -> dict:
    return {
        "trade_date": row.trade_date,
        "target_code": row.target_code,
        "target_name": row.target_name,
        "sector_code": row.sector_code,
        "sector_name": row.sector_name,
        "current_price": row.close_price,
        "change_percent": row.change_percent,
        "volume": row.volume,
        "turnover": row.turnover,
        "fund_amount": row.fund_amount,
        "volume_change_percent": _pct_change(previous.volume if previous else 0, row.volume),
        "turnover_change_percent": _pct_change(previous.turnover if previous else 0, row.turnover),
        "fund_change_percent": _pct_change(previous.fund_amount if previous else 0, row.fund_amount),
        "data_quality": row.data_quality,
    }


def _previous_row(db: Session, row: DailyAggregate, ordered_dates: list[str]) -> Optional[DailyAggregate]:
    try:
        index = ordered_dates.index(row.trade_date)
    except ValueError:
        return None
    if index + 1 >= len(ordered_dates):
        return None
    return _find_daily(db, row.target_type, row.target_code, ordered_dates[index + 1], sector_code=row.sector_code)


def _find_daily(
    db: Session,
    target_type: str,
    target_code: str,
    trade_date: str,
    sector_code: Optional[str] = None,
) -> Optional[DailyAggregate]:
    rows = daily_rows_for_date(db, trade_date, target_type, sector_code=sector_code)
    for row in rows:
        if row.target_code == target_code:
            return row
    return None


def _pct_change(previous: float, current: float) -> Optional[float]:
    if previous <= 0:
        return None
    return round((current - previous) / previous * 100, 4)


def _quality(rows: list) -> str:
    if not rows:
        return "missing"
    qualities = {row.data_quality for row in rows}
    if len(qualities) == 1:
        return next(iter(qualities))
    return "partial"
