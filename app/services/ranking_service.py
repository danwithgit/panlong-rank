from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo
from typing import Callable, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.tables import Ranking
from app.models import BoardQuote, MarketSnapshot, RankingBlock, RankingItem, StockQuote, Timeframe
from app.services.periods import combine_trade_time, period_for
from app.services.rankings import timeframe_label
from app.services.snapshot_store import latest_snapshot, snapshot_for_period

CN_TZ = ZoneInfo("Asia/Shanghai")

RANK_TYPE_LABELS = {
    "turnover": "成交额",
    "volume": "成交量",
    "fund": "资金量",
    "change": "涨幅",
}

TARGET_TYPE_LABELS = {
    "sector": "板块",
    "stock": "个股",
    "leader_stock": "龙头股",
}


def snapshot_for_timeframe(db: Session, status, timeframe: Timeframe) -> Optional[MarketSnapshot]:
    return snapshot_for_timeframe_with_settings(db, status, None, timeframe)


def snapshot_for_timeframe_with_settings(db: Session, status, settings, timeframe: Timeframe) -> Optional[MarketSnapshot]:
    spec = period_for(timeframe)
    start = combine_trade_time(status.last_trade_date if not status.is_trade_day else status.trade_date, spec.start)
    end = combine_trade_time(status.last_trade_date if not status.is_trade_day else status.trade_date, spec.end)
    if start is None and end is None:
        snapshot = snapshot_for_period(db, status, start, end)
        if not _is_allowed_snapshot(snapshot, settings):
            return None
        if settings is not None and _is_realtime_like(timeframe) and _is_unusable_realtime(snapshot, status, settings):
            return None
        return snapshot
    snapshot = snapshot_for_period(
        db,
        status,
        start,
        end,
        boundary_tolerance_seconds=getattr(settings, "period_boundary_tolerance_seconds", None),
        max_gap_seconds=getattr(settings, "max_period_snapshot_gap_seconds", None),
    )
    if not _is_allowed_snapshot(snapshot, settings):
        return None
    return snapshot


def ensure_snapshot(db: Session, settings, status) -> MarketSnapshot:
    snapshot = latest_snapshot(db, status)
    if _is_allowed_snapshot(snapshot, settings):
        return snapshot
    raise RuntimeError("行情数据缺失，采集服务繁忙或上游数据源不可用")


def build_dashboard_from_db(db: Session, status, settings, timeframe: Timeframe, limit: int):
    ensure_snapshot(db, settings, status)
    snapshot = snapshot_for_timeframe_with_settings(db, status, settings, timeframe)
    if snapshot is None:
        raise RuntimeError("该时间段真实快照不足或最新数据已过期，暂不展示以免误导")
    board_rankings = build_board_rankings_from_snapshot(snapshot, timeframe, limit)
    leader_rankings = build_leader_rankings_from_snapshot(snapshot, timeframe, limit)
    return snapshot, board_rankings, leader_rankings


def build_board_detail_from_db(db: Session, status, settings, timeframe: Timeframe, limit: int, board_code: str):
    ensure_snapshot(db, settings, status)
    snapshot = snapshot_for_timeframe_with_settings(db, status, settings, timeframe)
    if snapshot is None:
        raise RuntimeError("该时间段真实快照不足或最新数据已过期，暂不展示以免误导")
    board = next((item for item in snapshot.boards if item.code == board_code), None)
    if board is None:
        return None, [], snapshot
    rankings = build_stock_rankings_from_snapshot(snapshot, timeframe, limit, board_code=board_code)
    return board, rankings, snapshot


def rank_query(
    db: Session,
    status,
    settings,
    timeframe: Timeframe,
    rank_type: str,
    target_type: str,
    limit: int,
    sector_code: Optional[str] = None,
) -> RankingBlock:
    ensure_snapshot(db, settings, status)
    snapshot = snapshot_for_timeframe_with_settings(db, status, settings, timeframe)
    if snapshot is None:
        raise RuntimeError("该时间段真实快照不足或最新数据已过期，暂不展示以免误导")
    block = build_single_rank(snapshot, timeframe, rank_type, target_type, limit, sector_code=sector_code)
    return block


def build_board_rankings_from_snapshot(snapshot: MarketSnapshot, timeframe: Timeframe, limit: int) -> list[RankingBlock]:
    return [
        build_single_rank(snapshot, timeframe, rank_type, "sector", limit)
        for rank_type in ["turnover", "volume", "fund", "change"]
    ]


def build_stock_rankings_from_snapshot(
    snapshot: MarketSnapshot,
    timeframe: Timeframe,
    limit: int,
    board_code: Optional[str] = None,
) -> list[RankingBlock]:
    return [
        build_single_rank(snapshot, timeframe, rank_type, "stock", limit, sector_code=board_code)
        for rank_type in ["turnover", "volume", "fund", "change"]
    ]


def build_leader_rankings_from_snapshot(snapshot: MarketSnapshot, timeframe: Timeframe, limit: int) -> list[RankingBlock]:
    return [
        build_single_rank(snapshot, timeframe, rank_type, "leader_stock", limit)
        for rank_type in ["turnover", "volume", "fund", "change"]
    ]


def build_single_rank(
    snapshot: MarketSnapshot,
    timeframe: Timeframe,
    rank_type: str,
    target_type: str,
    limit: int,
    sector_code: Optional[str] = None,
) -> RankingBlock:
    if rank_type not in RANK_TYPE_LABELS:
        raise ValueError(f"unsupported rank_type: {rank_type}")
    if target_type not in TARGET_TYPE_LABELS:
        raise ValueError(f"unsupported target_type: {target_type}")
    metric = _metric_for_rank_type(rank_type)
    title = f"{timeframe_label(timeframe)}{TARGET_TYPE_LABELS[target_type]}{RANK_TYPE_LABELS[rank_type]}排行榜"

    if target_type == "sector":
        if rank_type == "fund" and not _has_fund_metric(snapshot.boards):
            return _unavailable_block(target_type, rank_type, title, metric)
        items = _rank_boards(snapshot.boards, rank_type, limit)
    elif target_type == "stock":
        stocks = snapshot.stocks
        if sector_code:
            stocks = [item for item in stocks if item.board_code == sector_code]
        if rank_type == "fund" and not _has_fund_metric(stocks):
            return _unavailable_block(target_type, rank_type, title, metric)
        leaders = {board.leader_stock_code for board in snapshot.boards if board.leader_stock_code}
        items = _rank_stocks(stocks, rank_type, limit, leaders)
    else:
        leaders_by_board = {board.code: board.leader_stock_code for board in snapshot.boards if board.leader_stock_code}
        leader_stocks = [stock for stock in snapshot.stocks if leaders_by_board.get(stock.board_code) == stock.code]
        if rank_type == "fund" and not _has_fund_metric(leader_stocks):
            return _unavailable_block(target_type, rank_type, title, metric)
        items = _rank_stocks(leader_stocks, rank_type, limit, set(leaders_by_board.values()))

    return RankingBlock(
        key=f"{target_type}_{rank_type}",
        title=title,
        metric=metric,
        items=items,
    )


def _unavailable_block(target_type: str, rank_type: str, title: str, metric: str) -> RankingBlock:
    return RankingBlock(
        key=f"{target_type}_{rank_type}",
        title=title,
        metric=metric,
        metric_available=False,
        quality_note="当前数据源没有真实资金流字段",
        items=[],
    )


def _has_fund_metric(items) -> bool:
    return any(abs(float(getattr(item, "capital_flow", 0) or 0)) > 0 for item in items)


def save_ranking_blocks(db: Session, status, timeframe: Timeframe, blocks: list[RankingBlock]) -> None:
    spec = period_for(timeframe)
    trade_date = status.trade_date if status.is_trade_day else status.last_trade_date
    for block in blocks:
        target_type, rank_type = _parse_block_key(block.key)
        db.execute(
            delete(Ranking).where(
                Ranking.trade_date == trade_date,
                Ranking.period_type == spec.period_type,
                Ranking.rank_type == rank_type,
                Ranking.target_type == target_type,
            )
        )
        for item in block.items:
            db.add(
                Ranking(
                    trade_date=trade_date,
                    period_type=spec.period_type,
                    period_start=spec.start.strftime("%H:%M") if spec.start else None,
                    period_end=spec.end.strftime("%H:%M") if spec.end else None,
                    rank_type=rank_type,
                    target_type=target_type,
                    sector_code=item.board_code,
                    sector_name=item.board_name,
                    stock_code=item.stock_code,
                    stock_name=item.stock_name,
                    rank_no=item.rank,
                    price=item.current_price or 0,
                    change_percent=item.change_percent,
                    volume=item.volume,
                    turnover=item.amount,
                    fund_amount=item.capital_flow,
                    snapshot_time=item.updated_at.replace(tzinfo=None),
                    created_at=datetime.utcnow(),
                )
            )


def cached_ranking_rows(
    db: Session,
    status,
    timeframe: Timeframe,
    rank_type: str,
    target_type: str,
    limit: int,
) -> list[Ranking]:
    spec = period_for(timeframe)
    trade_date = status.trade_date if status.is_trade_day else status.last_trade_date
    return list(
        db.scalars(
            select(Ranking)
            .where(
                Ranking.trade_date == trade_date,
                Ranking.period_type == spec.period_type,
                Ranking.rank_type == rank_type,
                Ranking.target_type == target_type,
            )
            .order_by(Ranking.rank_no)
            .limit(limit)
        )
    )


def _rank_boards(boards: list[BoardQuote], rank_type: str, limit: int) -> list[RankingItem]:
    scorer = _board_scorer(rank_type)
    ranked = sorted(boards, key=scorer, reverse=True)[:limit]
    return [
        RankingItem(
            rank=index,
            board_name=item.name,
            board_code=item.code,
            change_percent=item.change_percent,
            volume=item.volume,
            amount=item.amount,
            capital_flow=item.capital_flow,
            leader_stock_name=item.leader_stock_name,
            leader_stock_code=item.leader_stock_code,
            updated_at=item.updated_at,
        )
        for index, item in enumerate(ranked, start=1)
    ]


def _rank_stocks(stocks: list[StockQuote], rank_type: str, limit: int, leaders: set) -> list[RankingItem]:
    scorer = _stock_scorer(rank_type)
    ranked = sorted(stocks, key=scorer, reverse=True)[:limit]
    return [
        RankingItem(
            rank=index,
            board_name=item.board_name,
            board_code=item.board_code,
            stock_name=item.name,
            stock_code=item.code,
            current_price=item.price,
            change_percent=item.change_percent,
            volume=item.volume,
            amount=item.amount,
            capital_flow=item.capital_flow,
            is_leader=item.code in leaders,
            updated_at=item.updated_at,
        )
        for index, item in enumerate(ranked, start=1)
    ]


def _metric_for_rank_type(rank_type: str) -> str:
    return {"turnover": "amount", "volume": "volume", "fund": "capital_flow", "change": "change_percent"}[rank_type]


def _board_scorer(rank_type: str) -> Callable[[BoardQuote], float]:
    return {
        "turnover": lambda item: item.amount,
        "volume": lambda item: item.volume,
        "fund": lambda item: item.capital_flow,
        "change": lambda item: item.change_percent,
    }[rank_type]


def _stock_scorer(rank_type: str) -> Callable[[StockQuote], float]:
    return {
        "turnover": lambda item: item.amount,
        "volume": lambda item: item.volume,
        "fund": lambda item: item.capital_flow,
        "change": lambda item: item.change_percent,
    }[rank_type]


def _parse_block_key(key: str) -> tuple[str, str]:
    if key.startswith("leader_stock_"):
        return "leader_stock", key.replace("leader_stock_", "", 1)
    parts = key.split("_")
    return parts[0], "_".join(parts[1:])


def _is_realtime_like(timeframe: Timeframe) -> bool:
    return timeframe in {Timeframe.realtime, Timeframe.daily, Timeframe.last_trade_day}


def _is_allowed_snapshot(snapshot: Optional[MarketSnapshot], settings) -> bool:
    if snapshot is None:
        return False
    if settings is None:
        return True
    provider = getattr(settings, "data_provider", "auto").lower()
    if provider == "sample":
        return True
    return not _is_sample_source(snapshot.data_source)


def _is_sample_source(data_source: str) -> bool:
    return data_source.startswith("sample") or "sample" in data_source


def _is_unusable_realtime(snapshot: Optional[MarketSnapshot], status, settings) -> bool:
    if snapshot is None or not status.is_trade_day:
        return _is_incomplete_closed_snapshot(snapshot, settings)
    if status.session == "closed":
        return _is_incomplete_closed_snapshot(snapshot, settings)
    if status.session not in {"morning_trading", "afternoon_trading", "closing_trading", "lunch_break"}:
        return False
    max_age = getattr(settings, "max_realtime_snapshot_age_seconds", None)
    if max_age is None:
        return False
    updated_at = snapshot.index.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=CN_TZ)
    return (datetime.now(CN_TZ) - updated_at.astimezone(CN_TZ)).total_seconds() > max_age


def _is_incomplete_closed_snapshot(snapshot: Optional[MarketSnapshot], settings) -> bool:
    if snapshot is None:
        return False
    min_time = _parse_complete_day_min_time(getattr(settings, "complete_day_min_snapshot_time", "14:50"))
    updated_at = snapshot.index.updated_at
    if updated_at.tzinfo is not None:
        updated_at = updated_at.astimezone(CN_TZ).replace(tzinfo=None)
    return updated_at.time() < min_time


def _parse_complete_day_min_time(value: str) -> time:
    try:
        hour, minute = value.split(":", 1)
        return time(int(hour), int(minute))
    except Exception:
        return time(14, 50)
