from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.session import Base
from app.db.tables import JobLog
from app.models import TradingStatus
from app.services import scheduler


def test_scheduled_collect_records_timeout(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(scheduler, "SessionLocal", session_factory)
    monkeypatch.setattr(
        scheduler,
        "get_trading_status",
        lambda settings: TradingStatus(
            is_trade_day=True,
            trade_date="2026-07-07",
            last_trade_date="2026-07-07",
            session="afternoon_trading",
        ),
    )

    class FakeProcess:
        def __init__(self, target, args):
            self.terminated = False

        def start(self):
            pass

        def join(self, timeout):
            pass

        def is_alive(self):
            return not self.terminated

        def terminate(self):
            self.terminated = True

    monkeypatch.setattr(scheduler, "Process", FakeProcess)

    scheduler._scheduled_collect(Settings(collect_timeout_seconds=1))

    db = session_factory()
    try:
        row = db.scalar(select(JobLog).where(JobLog.status == "failed"))
        assert row is not None
        assert "timed out" in row.error_message
    finally:
        db.close()
