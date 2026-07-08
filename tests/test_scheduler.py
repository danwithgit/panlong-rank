from datetime import datetime

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


def test_record_timeout_marks_running_job_failed(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(scheduler, "SessionLocal", session_factory)
    db = session_factory()
    try:
        db.add(JobLog(job_name="collect_market_snapshot", status="running", started_at=datetime(2026, 7, 8, 6, 47, 24)))
        db.add(JobLog(job_name="collect_market_snapshot", status="running", started_at=datetime(2026, 7, 8, 6, 48, 24)))
        db.commit()
    finally:
        db.close()

    scheduler._record_timeout(150)

    db = session_factory()
    try:
        rows = db.scalars(select(JobLog)).all()
        assert len(rows) == 2
        assert {row.status for row in rows} == {"failed"}
        assert all("timed out" in row.error_message for row in rows)
    finally:
        db.close()


def test_scheduler_runs_jobs_immediately(monkeypatch):
    scheduler.stop_scheduler()
    added_jobs = []

    class FakeScheduler:
        def __init__(self, timezone):
            self.timezone = timezone

        def add_job(self, func, trigger, **kwargs):
            added_jobs.append((func, trigger, kwargs))

        def start(self):
            pass

        def shutdown(self, wait=False):
            pass

    monkeypatch.setattr(scheduler, "BackgroundScheduler", FakeScheduler)

    scheduler.start_scheduler(Settings(scheduler_enabled=True, backfill_enabled=True))

    try:
        assert len(added_jobs) == 2
        collect_job = next(item for item in added_jobs if item[2]["id"] == "collect_market_snapshot")
        backfill_job = next(item for item in added_jobs if item[2]["id"] == "backfill_daily_history")
        assert collect_job[2].get("next_run_time") is not None
        assert backfill_job[2]["next_run_time"] > collect_job[2]["next_run_time"]
    finally:
        scheduler.stop_scheduler()
