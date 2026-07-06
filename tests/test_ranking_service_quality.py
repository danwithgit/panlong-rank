from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.session import Base
from app.models import BoardQuote, IndexQuote, MarketSnapshot, StockQuote, Timeframe, TradingStatus
from app.services.ranking_service import snapshot_for_timeframe_with_settings
from app.services.snapshot_store import save_snapshot


CN_TZ = ZoneInfo("Asia/Shanghai")


def _db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _snapshot(at: datetime) -> MarketSnapshot:
    status = TradingStatus(
        is_trade_day=True,
        trade_date=at.strftime("%Y-%m-%d"),
        last_trade_date=at.strftime("%Y-%m-%d"),
        session="afternoon_trading",
    )
    return MarketSnapshot(
        index=IndexQuote(
            name="上证指数",
            code="000001",
            current=4000,
            change=1,
            change_percent=0.1,
            volume=1000,
            amount=2000,
            updated_at=at,
            trading_status=status,
        ),
        boards=[
            BoardQuote(
                code="BK001",
                name="测试板块",
                change_percent=1,
                volume=100,
                amount=200,
                capital_flow=200,
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
                price=10,
                change_percent=1,
                volume=100,
                amount=200,
                capital_flow=200,
                updated_at=at,
            )
        ],
        trading_status=status,
    )


def test_realtime_snapshot_rejects_stale_trade_session_data():
    db = _db()
    stale_at = datetime.now(CN_TZ) - timedelta(minutes=30)
    save_snapshot(db, _snapshot(stale_at), "sample")
    db.commit()
    status = TradingStatus(
        is_trade_day=True,
        trade_date=stale_at.strftime("%Y-%m-%d"),
        last_trade_date=stale_at.strftime("%Y-%m-%d"),
        session="afternoon_trading",
    )

    snapshot = snapshot_for_timeframe_with_settings(
        db,
        status,
        Settings(data_provider="sample", max_realtime_snapshot_age_seconds=600),
        Timeframe.realtime,
    )

    assert snapshot is None


def test_realtime_snapshot_allows_stale_non_trade_day_data():
    db = _db()
    stale_at = datetime.now(CN_TZ) - timedelta(days=2)
    save_snapshot(db, _snapshot(stale_at), "sample")
    db.commit()
    status = TradingStatus(
        is_trade_day=False,
        trade_date=(stale_at + timedelta(days=1)).strftime("%Y-%m-%d"),
        last_trade_date=stale_at.strftime("%Y-%m-%d"),
        session="closed",
    )

    snapshot = snapshot_for_timeframe_with_settings(
        db,
        status,
        Settings(data_provider="sample", max_realtime_snapshot_age_seconds=600),
        Timeframe.realtime,
    )

    assert snapshot is not None
