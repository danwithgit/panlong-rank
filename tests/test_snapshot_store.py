from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.db.tables import IndexSnapshot
from app.models import BoardQuote, IndexQuote, MarketSnapshot, StockQuote, TradingStatus
from app.services.snapshot_store import save_snapshot, snapshot_for_period


def _db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _snapshot(at: datetime, volume: float, amount: float, price: float) -> MarketSnapshot:
    status = TradingStatus(
        is_trade_day=True,
        trade_date="2026-07-03",
        last_trade_date="2026-07-03",
        session="morning_trading",
    )
    return MarketSnapshot(
        index=IndexQuote(
            name="上证指数",
            code="000001",
            current=price,
            change=1,
            change_percent=1,
            volume=volume,
            amount=amount,
            updated_at=at,
            trading_status=status,
        ),
        boards=[
            BoardQuote(
                code="BK001",
                name="测试板块",
                change_percent=2,
                volume=volume,
                amount=amount,
                capital_flow=amount / 10,
                leader_stock_code="000001",
                leader_stock_name="测试股票",
                updated_at=at,
            )
        ],
        stocks=[
            StockQuote(
                code="000001",
                name="测试股票",
                board_code="BK001",
                board_name="测试板块",
                price=price,
                change_percent=2,
                volume=volume,
                amount=amount,
                capital_flow=amount / 10,
                updated_at=at,
            )
        ],
        trading_status=status,
    )


def test_snapshot_for_period_uses_database_interval_diff():
    db = _db()
    status = TradingStatus(
        is_trade_day=True,
        trade_date="2026-07-03",
        last_trade_date="2026-07-03",
        session="morning_trading",
    )
    start = datetime(2026, 7, 3, 9, 30)
    end = datetime(2026, 7, 3, 10, 30)
    save_snapshot(db, _snapshot(start, 100, 1000, 10), "sample")
    save_snapshot(db, _snapshot(end, 180, 2100, 11), "sample")
    db.commit()

    result = snapshot_for_period(db, status, start, end)

    assert result.boards[0].volume == 80
    assert result.boards[0].amount == 1100
    assert result.stocks[0].volume == 80
    assert result.stocks[0].amount == 1100
    assert result.stocks[0].change_percent == 10


def test_snapshot_for_period_requires_distinct_start_and_end_snapshots():
    db = _db()
    status = TradingStatus(
        is_trade_day=True,
        trade_date="2026-07-03",
        last_trade_date="2026-07-03",
        session="morning_trading",
    )
    at = datetime(2026, 7, 3, 10, 10)
    save_snapshot(db, _snapshot(at, 100, 1000, 10), "sample")
    db.commit()

    result = snapshot_for_period(db, status, datetime(2026, 7, 3, 9, 30), datetime(2026, 7, 3, 10, 30))

    assert result is None


def test_latest_snapshot_uses_one_collection_batch():
    db = _db()
    status = TradingStatus(
        is_trade_day=True,
        trade_date="2026-07-03",
        last_trade_date="2026-07-03",
        session="morning_trading",
    )
    save_snapshot(db, _snapshot(datetime(2026, 7, 3, 9, 40), 100, 1000, 10), "sample")
    save_snapshot(db, _snapshot(datetime(2026, 7, 3, 10, 10), 200, 3000, 11), "sample")
    db.commit()

    result = snapshot_for_period(db, status, None, None)

    assert len(result.boards) == 1
    assert len(result.stocks) == 1
    assert result.boards[0].updated_at == datetime(2026, 7, 3, 10, 10)
    assert result.stocks[0].updated_at == datetime(2026, 7, 3, 10, 10)


def test_latest_snapshot_skips_incomplete_newer_batch():
    db = _db()
    status = TradingStatus(
        is_trade_day=True,
        trade_date="2026-07-03",
        last_trade_date="2026-07-03",
        session="morning_trading",
    )
    complete_at = datetime(2026, 7, 3, 10, 10)
    incomplete_at = datetime(2026, 7, 3, 10, 20)
    save_snapshot(db, _snapshot(complete_at, 200, 3000, 11), "sample")
    db.add(
        IndexSnapshot(
            index_code="000001",
            index_name="上证指数",
            current_price=12,
            change_value=2,
            change_percent=2,
            volume=300,
            turnover=5000,
            snapshot_time=incomplete_at,
            trade_date="2026-07-03",
            data_source="sample",
        )
    )
    db.commit()

    result = snapshot_for_period(db, status, None, None)

    assert result.index.updated_at == complete_at
    assert result.boards[0].updated_at == complete_at
    assert result.stocks[0].updated_at == complete_at


def test_snapshot_for_period_rejects_boundary_snapshot_outside_tolerance():
    db = _db()
    status = TradingStatus(
        is_trade_day=True,
        trade_date="2026-07-03",
        last_trade_date="2026-07-03",
        session="morning_trading",
    )
    save_snapshot(db, _snapshot(datetime(2026, 7, 3, 9, 40), 100, 1000, 10), "sample")
    save_snapshot(db, _snapshot(datetime(2026, 7, 3, 10, 30), 180, 2100, 11), "sample")
    db.commit()

    result = snapshot_for_period(
        db,
        status,
        datetime(2026, 7, 3, 9, 30),
        datetime(2026, 7, 3, 10, 30),
        boundary_tolerance_seconds=300,
        max_gap_seconds=3600,
    )

    assert result is None


def test_snapshot_for_period_rejects_large_collection_gap():
    db = _db()
    status = TradingStatus(
        is_trade_day=True,
        trade_date="2026-07-03",
        last_trade_date="2026-07-03",
        session="morning_trading",
    )
    save_snapshot(db, _snapshot(datetime(2026, 7, 3, 9, 30), 100, 1000, 10), "sample")
    save_snapshot(db, _snapshot(datetime(2026, 7, 3, 10, 30), 180, 2100, 11), "sample")
    db.commit()

    result = snapshot_for_period(
        db,
        status,
        datetime(2026, 7, 3, 9, 30),
        datetime(2026, 7, 3, 10, 30),
        boundary_tolerance_seconds=300,
        max_gap_seconds=600,
    )

    assert result is None
