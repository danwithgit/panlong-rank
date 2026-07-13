from __future__ import annotations

from typing import Optional

from sqlalchemy import select
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


def summary_report(db: Session, target_type: str = "sector") -> dict:
    dates = recent_trade_dates(db, 7)
    if not dates:
        return {
            "trade_date": None,
            "target_type": target_type,
            "date_start": None,
            "date_end": None,
            "days": 0,
            "metric_note": _volume_metric_note(),
            "items": [],
            "data_quality": "missing",
        }

    latest_date = dates[0]
    daily_volume = daily_rank(db, latest_date, target_type, "volume", 1)
    daily_turnover = daily_rank(db, latest_date, target_type, "turnover", 1)
    cumulative_rows = _cumulative_rows(db, dates, target_type)
    seven_day_volume = _top_cumulative(cumulative_rows, "volume")
    seven_day_turnover = _top_cumulative(cumulative_rows, "turnover")
    quality_rows = [
        item
        for item in [
            *(daily_volume.get("items") or []),
            *(daily_turnover.get("items") or []),
            seven_day_volume,
            seven_day_turnover,
        ]
        if item
    ]
    return {
        "trade_date": latest_date,
        "target_type": target_type,
        "date_start": min(dates),
        "date_end": max(dates),
        "days": len(dates),
        "metric_note": _volume_metric_note(),
        "items": [
            {
                "key": "today_volume",
                "title": "今日最大买入量",
                "metric": "volume",
                "metric_label": "成交量",
                "period_label": latest_date,
                "item": _first_item(daily_volume),
            },
            {
                "key": "today_turnover",
                "title": "今日最大成交额",
                "metric": "turnover",
                "metric_label": "成交额",
                "period_label": latest_date,
                "item": _first_item(daily_turnover),
            },
            {
                "key": "seven_day_volume",
                "title": "7日累计最大买入量",
                "metric": "volume",
                "metric_label": "累计成交量",
                "period_label": f"{min(dates)} ~ {max(dates)}",
                "item": seven_day_volume,
            },
            {
                "key": "seven_day_turnover",
                "title": "7日累计最大成交额",
                "metric": "turnover",
                "metric_label": "累计成交额",
                "period_label": f"{min(dates)} ~ {max(dates)}",
                "item": seven_day_turnover,
            },
        ],
        "data_quality": _dict_quality(quality_rows),
    }


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


def _volume_metric_note() -> str:
    return "当前免费行情源没有逐笔主动买入字段，买入量按成交量口径展示。"


def _first_item(payload: dict) -> Optional[dict]:
    items = payload.get("items") or []
    return items[0] if items else None


def _cumulative_rows(db: Session, dates: list[str], target_type: str) -> list[dict]:
    rows = list(
        db.scalars(
            select(DailyAggregate)
            .where(DailyAggregate.trade_date.in_(dates), DailyAggregate.target_type == target_type)
            .order_by(DailyAggregate.trade_date.asc(), DailyAggregate.id.asc())
        )
    )
    grouped: dict[tuple[str, Optional[str]], dict] = {}
    for row in rows:
        key = (row.target_code, row.sector_code)
        item = grouped.setdefault(
            key,
            {
                "rank": 0,
                "target_type": row.target_type,
                "target_code": row.target_code,
                "target_name": row.target_name,
                "sector_code": row.sector_code,
                "sector_name": row.sector_name,
                "current_price": row.close_price,
                "change_percent": row.change_percent,
                "volume": 0,
                "turnover": 0,
                "fund_amount": 0,
                "trading_days": 0,
                "expected_trading_days": len(dates),
                "missing_trading_days": 0,
                "data_quality": row.data_quality,
                "data_source": row.data_source,
                "_trade_dates": set(),
                "_qualities": set(),
                "_sources": set(),
            },
        )
        item["target_name"] = row.target_name
        item["sector_name"] = row.sector_name
        item["current_price"] = row.close_price
        item["change_percent"] = row.change_percent
        item["volume"] += row.volume
        item["turnover"] += row.turnover
        item["fund_amount"] += row.fund_amount
        item["_trade_dates"].add(row.trade_date)
        item["_qualities"].add(row.data_quality)
        item["_sources"].add(row.data_source)

    values = []
    for item in grouped.values():
        trading_days = len(item["_trade_dates"])
        item["trading_days"] = trading_days
        item["missing_trading_days"] = max(len(dates) - trading_days, 0)
        item["data_quality"] = _merge_dict_quality(item["_qualities"], item["missing_trading_days"])
        item["data_source"] = "+".join(sorted(item["_sources"]))
        del item["_trade_dates"]
        del item["_qualities"]
        del item["_sources"]
        values.append(item)
    return values


def _top_cumulative(rows: list[dict], metric: str) -> Optional[dict]:
    ranked = sorted(rows, key=lambda item: item.get(metric) or 0, reverse=True)
    if not ranked:
        return None
    item = dict(ranked[0])
    item["rank"] = 1
    return item


def _dict_quality(rows: list[dict]) -> str:
    if not rows:
        return "missing"
    qualities = {row.get("data_quality") for row in rows if row.get("data_quality")}
    if len(qualities) == 1:
        return next(iter(qualities))
    return "partial"


def _merge_dict_quality(qualities: set[str], missing_days: int) -> str:
    if not qualities:
        return "missing"
    if "missing" in qualities:
        return "missing"
    if missing_days > 0 or "partial" in qualities or len(qualities) > 1:
        return "partial"
    if "backfilled" in qualities:
        return "backfilled"
    return "live"


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
