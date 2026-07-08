from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.session import Base
from app.db.tables import JobLog
from app.models import BoardQuote, IndexQuote, MarketSnapshot, StockQuote, TradingStatus
from app.services import collector


def test_collector_does_not_hold_write_lock_while_provider_runs(monkeypatch, tmp_path):
    db_path = tmp_path / "collector.sqlite3"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 1},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False)

    status = TradingStatus(
        is_trade_day=True,
        trade_date="2026-07-08",
        last_trade_date="2026-07-08",
        session="afternoon_trading",
    )

    class LockCheckingProvider:
        def snapshot(self, trading_status):
            other = session_factory()
            try:
                other.add(JobLog(job_name="lock_probe", status="success", started_at=datetime.utcnow(), rows_count=0))
                other.commit()
            finally:
                other.close()
            return _snapshot(status)

    monkeypatch.setattr(collector, "get_trading_status", lambda settings: status)
    monkeypatch.setattr(collector, "get_provider", lambda settings: LockCheckingProvider())

    db = session_factory()
    try:
        collector.collect_market_snapshot(db, Settings(data_provider="akshare"), force=True)
    finally:
        db.close()


def _snapshot(status: TradingStatus) -> MarketSnapshot:
    now = datetime(2026, 7, 8, 14, 30)
    return MarketSnapshot(
        index=IndexQuote(
            name="上证指数",
            code="000001",
            current=4000,
            change=1,
            change_percent=0.1,
            volume=100,
            amount=1000,
            updated_at=now,
            trading_status=status,
            data_source="test",
        ),
        boards=[
            BoardQuote(
                code="new_test",
                name="测试板块",
                change_percent=1,
                volume=100,
                amount=1000,
                capital_flow=1000,
                updated_at=now,
            )
        ],
        stocks=[
            StockQuote(
                code="600001",
                name="测试股票",
                board_code="new_test",
                board_name="测试板块",
                price=10,
                change_percent=1,
                volume=100,
                amount=1000,
                capital_flow=1000,
                updated_at=now,
            )
        ],
        trading_status=status,
        data_source="test",
    )
