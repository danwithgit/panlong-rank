from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import Session

from app.db.tables import (
    IndexSnapshot,
    SectorLeaderConfig,
    SectorSnapshot,
    StockSectorMap,
    StockSnapshot,
    TradingCalendar,
)
from app.models import BoardQuote, IndexQuote, MarketSnapshot, StockQuote, TradingStatus


def save_trading_calendar(db: Session, status: TradingStatus) -> None:
    existing = db.scalar(select(TradingCalendar).where(TradingCalendar.trade_date == status.trade_date))
    if existing is None:
        db.add(
            TradingCalendar(
                trade_date=status.trade_date,
                is_open=status.is_trade_day,
                pretrade_date=status.last_trade_date,
            )
        )
    else:
        existing.is_open = status.is_trade_day
        existing.pretrade_date = status.last_trade_date


def save_snapshot(db: Session, snapshot: MarketSnapshot, data_source: str) -> int:
    source = snapshot.data_source if snapshot.data_source != "unknown" else data_source
    trade_date = snapshot.trading_status.last_trade_date if not snapshot.trading_status.is_trade_day else snapshot.trading_status.trade_date
    snapshot_time = snapshot.index.updated_at.replace(tzinfo=None)
    save_trading_calendar(db, snapshot.trading_status)
    leader_map = _leader_map(db, snapshot)
    rows = 0

    db.add(
        IndexSnapshot(
            index_code=snapshot.index.code,
            index_name=snapshot.index.name,
            current_price=snapshot.index.current,
            change_value=snapshot.index.change,
            change_percent=snapshot.index.change_percent,
            volume=snapshot.index.volume,
            turnover=snapshot.index.amount,
            snapshot_time=snapshot_time,
            trade_date=trade_date,
            data_source=source,
        )
    )
    rows += 1

    for board in snapshot.boards:
        leader = leader_map.get(board.code)
        db.add(
            SectorSnapshot(
                sector_code=board.code,
                sector_name=board.name,
                change_percent=board.change_percent,
                volume=board.volume,
                turnover=board.amount,
                fund_amount=board.capital_flow,
                leader_stock_code=leader[0] if leader else board.leader_stock_code,
                leader_stock_name=leader[1] if leader else board.leader_stock_name,
                snapshot_time=snapshot_time,
                trade_date=trade_date,
                data_source=source,
            )
        )
        rows += 1

    saved_stock_codes = set()
    for stock in snapshot.stocks:
        _upsert_stock_sector(db, stock)
        if stock.code in saved_stock_codes:
            continue
        saved_stock_codes.add(stock.code)
        db.add(
            StockSnapshot(
                stock_code=stock.code,
                stock_name=stock.name,
                current_price=stock.price,
                change_percent=stock.change_percent,
                change_value=0,
                volume=stock.volume,
                turnover=stock.amount,
                fund_amount=stock.capital_flow,
                high_price=stock.price,
                low_price=stock.price,
                open_price=stock.price,
                previous_close=0,
                snapshot_time=snapshot_time,
                trade_date=trade_date,
                data_source=source,
            )
        )
        rows += 1

    return rows


def latest_snapshot(db: Session, status: TradingStatus) -> Optional[MarketSnapshot]:
    trade_date = status.trade_date if status.is_trade_day else status.last_trade_date
    for index_row in _latest_index_rows(db, trade_date, limit=20):
        sector_rows = _sector_rows_at(db, trade_date, index_row.snapshot_time)
        stock_rows = _latest_stock_rows(db, trade_date, index_row.snapshot_time)
        if sector_rows and stock_rows:
            return _snapshot_from_rows(index_row, sector_rows, stock_rows, status)
    return None


def snapshot_for_period(
    db: Session,
    status: TradingStatus,
    start: Optional[datetime],
    end: Optional[datetime],
    boundary_tolerance_seconds: Optional[int] = None,
    max_gap_seconds: Optional[int] = None,
) -> Optional[MarketSnapshot]:
    trade_date = status.trade_date if status.is_trade_day else status.last_trade_date
    if start is None and end is None:
        return latest_snapshot(db, status)
    end_snapshot = _snapshot_at_or_before(db, status, trade_date, end)
    if end_snapshot is None:
        return None
    start_snapshot = _snapshot_at_or_after(db, status, trade_date, start)
    if start_snapshot is None:
        return None
    if start_snapshot.index.updated_at == end_snapshot.index.updated_at:
        return None
    if boundary_tolerance_seconds is not None:
        tolerance = timedelta(seconds=boundary_tolerance_seconds)
        if abs(start_snapshot.index.updated_at - start) > tolerance:
            return None
        if abs(end_snapshot.index.updated_at - end) > tolerance:
            return None
    if max_gap_seconds is not None and not _has_continuous_index_snapshots(
        db,
        trade_date,
        start_snapshot.index.updated_at,
        end_snapshot.index.updated_at,
        max_gap_seconds,
    ):
        return None
    return diff_snapshots(start_snapshot, end_snapshot)


def has_snapshots(db: Session) -> bool:
    return bool(db.scalar(select(IndexSnapshot.id).limit(1)))


def trim_old_snapshots(db: Session, keep_trade_dates: int = 10) -> None:
    dates = db.scalars(
        select(IndexSnapshot.trade_date).distinct().order_by(IndexSnapshot.trade_date.desc()).limit(keep_trade_dates)
    ).all()
    if not dates:
        return
    db.execute(delete(IndexSnapshot).where(IndexSnapshot.trade_date.not_in(dates)))
    db.execute(delete(SectorSnapshot).where(SectorSnapshot.trade_date.not_in(dates)))
    db.execute(delete(StockSnapshot).where(StockSnapshot.trade_date.not_in(dates)))


def diff_snapshots(start: MarketSnapshot, end: MarketSnapshot) -> MarketSnapshot:
    start_boards = {item.code: item for item in start.boards}
    start_stocks = {item.code: item for item in start.stocks}
    boards: list[BoardQuote] = []
    stocks: list[StockQuote] = []

    for board in end.boards:
        base = start_boards.get(board.code)
        if base is None:
            boards.append(board)
            continue
        boards.append(
            board.model_copy(
                update={
                    "volume": max(board.volume - base.volume, 0),
                    "amount": max(board.amount - base.amount, 0),
                    "capital_flow": board.capital_flow - base.capital_flow,
                    "change_percent": _price_change_percent(base.change_percent, board.change_percent),
                }
            )
        )

    for stock in end.stocks:
        base = start_stocks.get(stock.code)
        if base is None:
            stocks.append(stock)
            continue
        stocks.append(
            stock.model_copy(
                update={
                    "volume": max(stock.volume - base.volume, 0),
                    "amount": max(stock.amount - base.amount, 0),
                    "capital_flow": stock.capital_flow - base.capital_flow,
                    "change_percent": _real_price_change_percent(base.price, stock.price),
                }
            )
        )

    return end.model_copy(update={"boards": boards, "stocks": stocks})


def _upsert_stock_sector(db: Session, stock: StockQuote) -> None:
    existing = db.scalar(
        select(StockSectorMap).where(
            and_(StockSectorMap.stock_code == stock.code, StockSectorMap.sector_code == stock.board_code)
        )
    )
    if existing is None:
        db.add(
            StockSectorMap(
                stock_code=stock.code,
                stock_name=stock.name,
                sector_code=stock.board_code,
                sector_name=stock.board_name,
                sector_type="industry",
            )
        )
    else:
        existing.stock_name = stock.name
        existing.sector_name = stock.board_name


def _leader_map(db: Session, snapshot: MarketSnapshot) -> dict[str, tuple[str, str]]:
    manual = {
        item.sector_code: (item.stock_code, item.stock_name)
        for item in db.scalars(
            select(SectorLeaderConfig)
            .where(SectorLeaderConfig.enabled == True)  # noqa: E712
            .order_by(SectorLeaderConfig.priority.asc(), SectorLeaderConfig.id.asc())
        )
    }
    result = dict(manual)
    for board in snapshot.boards:
        if board.code in result:
            continue
        stocks = [stock for stock in snapshot.stocks if stock.board_code == board.code]
        if not stocks:
            if board.leader_stock_code and board.leader_stock_name:
                result[board.code] = (board.leader_stock_code, board.leader_stock_name)
            continue
        result[board.code] = _auto_leader(stocks)
    return result


def _auto_leader(stocks: list[StockQuote]) -> tuple[str, str]:
    amount_rank = _rank_lookup(stocks, lambda item: item.amount)
    fund_rank = _rank_lookup(stocks, lambda item: item.capital_flow)
    change_rank = _rank_lookup(stocks, lambda item: item.change_percent)
    volume_rank = _rank_lookup(stocks, lambda item: item.volume)

    def score(stock: StockQuote) -> float:
        return (
            0.4 / amount_rank[stock.code]
            + 0.3 / fund_rank[stock.code]
            + 0.2 / change_rank[stock.code]
            + 0.1 / volume_rank[stock.code]
        )

    leader = max(stocks, key=score)
    return leader.code, leader.name


def _rank_lookup(stocks: list[StockQuote], scorer) -> dict[str, int]:
    ranked = sorted(stocks, key=scorer, reverse=True)
    return {stock.code: index for index, stock in enumerate(ranked, start=1)}


def _latest_index(db: Session, trade_date: str) -> Optional[IndexSnapshot]:
    return db.scalar(
        select(IndexSnapshot)
        .where(IndexSnapshot.trade_date == trade_date)
        .order_by(IndexSnapshot.snapshot_time.desc(), IndexSnapshot.id.desc())
        .limit(1)
    )


def _latest_index_rows(db: Session, trade_date: str, limit: int) -> list[IndexSnapshot]:
    return list(
        db.scalars(
            select(IndexSnapshot)
            .where(IndexSnapshot.trade_date == trade_date)
            .order_by(IndexSnapshot.snapshot_time.desc(), IndexSnapshot.id.desc())
            .limit(limit)
        )
    )


def _latest_sector_rows(db: Session, trade_date: str) -> list[SectorSnapshot]:
    latest_time = db.scalar(select(func.max(SectorSnapshot.snapshot_time)).where(SectorSnapshot.trade_date == trade_date))
    if latest_time is None:
        return []
    return _sector_rows_at(db, trade_date, latest_time)


def _sector_rows_at(db: Session, trade_date: str, snapshot_time: datetime) -> list[SectorSnapshot]:
    return list(
        db.scalars(
            select(SectorSnapshot)
            .where(SectorSnapshot.trade_date == trade_date, SectorSnapshot.snapshot_time == snapshot_time)
            .order_by(SectorSnapshot.sector_code)
        )
    )


def _latest_stock_rows(db: Session, trade_date: str, snapshot_time: Optional[datetime] = None) -> list[tuple[StockSnapshot, StockSectorMap]]:
    if snapshot_time is None:
        snapshot_time = db.scalar(select(func.max(StockSnapshot.snapshot_time)).where(StockSnapshot.trade_date == trade_date))
    if snapshot_time is None:
        return []
    rows = db.execute(
        select(StockSnapshot, StockSectorMap)
        .where(StockSnapshot.trade_date == trade_date, StockSnapshot.snapshot_time == snapshot_time)
        .join(StockSectorMap, StockSnapshot.stock_code == StockSectorMap.stock_code)
        .order_by(StockSnapshot.stock_code)
    ).all()
    return list(rows)


def _snapshot_at_or_before(
    db: Session,
    status: TradingStatus,
    trade_date: str,
    target: Optional[datetime],
) -> Optional[MarketSnapshot]:
    if target is None:
        return latest_snapshot(db, status)
    index_row = db.scalar(
        select(IndexSnapshot)
        .where(IndexSnapshot.trade_date == trade_date, IndexSnapshot.snapshot_time <= target)
        .order_by(IndexSnapshot.snapshot_time.desc(), IndexSnapshot.id.desc())
        .limit(1)
    )
    if index_row is None:
        return None
    snapshot_time = index_row.snapshot_time
    sector_rows = list(
        db.scalars(
            select(SectorSnapshot)
            .where(SectorSnapshot.trade_date == trade_date, SectorSnapshot.snapshot_time == snapshot_time)
            .order_by(SectorSnapshot.sector_code)
        )
    )
    stock_rows = _latest_stock_rows(db, trade_date, snapshot_time)
    if not sector_rows or not stock_rows:
        return None
    return _snapshot_from_rows(index_row, sector_rows, stock_rows, status)


def _snapshot_at_or_after(
    db: Session,
    status: TradingStatus,
    trade_date: str,
    target: Optional[datetime],
) -> Optional[MarketSnapshot]:
    if target is None:
        return latest_snapshot(db, status)
    index_row = db.scalar(
        select(IndexSnapshot)
        .where(IndexSnapshot.trade_date == trade_date, IndexSnapshot.snapshot_time >= target)
        .order_by(IndexSnapshot.snapshot_time.asc(), IndexSnapshot.id.asc())
        .limit(1)
    )
    if index_row is None:
        return None
    snapshot_time = index_row.snapshot_time
    sector_rows = _sector_rows_at(db, trade_date, snapshot_time)
    stock_rows = _latest_stock_rows(db, trade_date, snapshot_time)
    if not sector_rows or not stock_rows:
        return None
    return _snapshot_from_rows(index_row, sector_rows, stock_rows, status)


def _has_continuous_index_snapshots(
    db: Session,
    trade_date: str,
    start: datetime,
    end: datetime,
    max_gap_seconds: int,
) -> bool:
    times = list(
        db.scalars(
            select(IndexSnapshot.snapshot_time)
            .where(
                IndexSnapshot.trade_date == trade_date,
                IndexSnapshot.snapshot_time >= start,
                IndexSnapshot.snapshot_time <= end,
            )
            .order_by(IndexSnapshot.snapshot_time.asc())
        )
    )
    if len(times) < 2:
        return False
    return all((right - left).total_seconds() <= max_gap_seconds for left, right in zip(times, times[1:]))


def _snapshot_from_rows(
    index_row: IndexSnapshot,
    sector_rows: list[SectorSnapshot],
    stock_rows: list[tuple[StockSnapshot, StockSectorMap]],
    status: TradingStatus,
) -> MarketSnapshot:
    index = IndexQuote(
        name=index_row.index_name,
        code=index_row.index_code,
        current=index_row.current_price,
        change=index_row.change_value,
        change_percent=index_row.change_percent,
        volume=index_row.volume,
        amount=index_row.turnover,
        updated_at=index_row.snapshot_time,
        trading_status=status,
        data_source=index_row.data_source,
    )
    boards = [
        BoardQuote(
            code=row.sector_code,
            name=row.sector_name,
            change_percent=row.change_percent,
            volume=row.volume,
            amount=row.turnover,
            capital_flow=row.fund_amount,
            leader_stock_code=row.leader_stock_code,
            leader_stock_name=row.leader_stock_name,
            updated_at=row.snapshot_time,
        )
        for row in sector_rows
    ]
    stocks = [
        StockQuote(
            code=stock.stock_code,
            name=stock.stock_name,
            board_code=mapping.sector_code,
            board_name=mapping.sector_name,
            price=stock.current_price,
            change_percent=stock.change_percent,
            volume=stock.volume,
            amount=stock.turnover,
            capital_flow=stock.fund_amount,
            updated_at=stock.snapshot_time,
        )
        for stock, mapping in stock_rows
    ]
    return MarketSnapshot(index=index, boards=boards, stocks=stocks, trading_status=status, data_source=index_row.data_source)




def _price_change_percent(start_percent: float, end_percent: float) -> float:
    return round(end_percent - start_percent, 4)


def _real_price_change_percent(start_price: float, end_price: float) -> float:
    if start_price <= 0:
        return 0
    return round((end_price - start_price) / start_price * 100, 4)
