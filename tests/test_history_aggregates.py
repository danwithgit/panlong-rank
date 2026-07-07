from datetime import datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.db.tables import DailyAggregate, IndexSnapshot, SectorSnapshot, StockSectorMap, StockSnapshot, WeeklyAggregate
from app.services.aggregates import rebuild_daily_aggregate, rebuild_recent_weekly_aggregates
from app.services.history_rankings import compare_daily, daily_rank, recent_daily_options, recent_weekly_options, weekly_rank


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _seed_snapshot(db, trade_date: str, offset: int, sector_turnover: float, stock_turnover: float):
    snapshot_time = datetime(2026, 7, 1, 15, 0, 0) + timedelta(days=offset)
    db.add(
        IndexSnapshot(
            index_code="000001",
            index_name="上证指数",
            current_price=4000 + offset,
            change_value=offset,
            change_percent=offset,
            volume=1000 + offset,
            turnover=2000 + offset,
            snapshot_time=snapshot_time,
            trade_date=trade_date,
            data_source="test",
        )
    )
    db.add(
        SectorSnapshot(
            sector_code="new_test",
            sector_name="测试板块",
            change_percent=offset,
            volume=sector_turnover / 10,
            turnover=sector_turnover,
            fund_amount=sector_turnover,
            leader_stock_code="600001",
            leader_stock_name="测试股票",
            snapshot_time=snapshot_time,
            trade_date=trade_date,
            data_source="test",
        )
    )
    if db.scalar(select(StockSectorMap).where(StockSectorMap.stock_code == "600001", StockSectorMap.sector_code == "new_test")) is None:
        db.add(
            StockSectorMap(
                stock_code="600001",
                stock_name="测试股票",
                sector_code="new_test",
                sector_name="测试板块",
                sector_type="industry",
            )
        )
    db.add(
        StockSnapshot(
            stock_code="600001",
            stock_name="测试股票",
            current_price=10 + offset,
            change_percent=offset,
            volume=stock_turnover / 10,
            turnover=stock_turnover,
            fund_amount=stock_turnover,
            high_price=10 + offset,
            low_price=9 + offset,
            open_price=9 + offset,
            previous_close=8 + offset,
            snapshot_time=snapshot_time,
            trade_date=trade_date,
            data_source="test",
        )
    )


def test_daily_weekly_aggregates_and_history_queries():
    db = _db()
    _seed_snapshot(db, "2026-07-01", 0, 1000, 100)
    _seed_snapshot(db, "2026-07-02", 1, 2000, 150)
    _seed_snapshot(db, "2026-07-03", 2, 3000, 300)

    assert rebuild_daily_aggregate(db, "2026-07-01") == 3
    assert rebuild_daily_aggregate(db, "2026-07-02") == 3
    assert rebuild_daily_aggregate(db, "2026-07-03") == 3
    assert rebuild_recent_weekly_aggregates(db) == 3
    db.commit()

    assert [item["trade_date"] for item in recent_daily_options(db, 2)] == ["2026-07-03", "2026-07-02"]
    weeks = recent_weekly_options(db, 1)
    assert weeks == [{"week_start": "2026-07-01", "week_end": "2026-07-03", "label": "2026-07-01 ~ 2026-07-03"}]

    daily = daily_rank(db, None, "sector", "turnover", 10)
    assert daily["trade_date"] == "2026-07-03"
    assert daily["items"][0]["target_code"] == "new_test"
    assert daily["items"][0]["turnover"] == 3000

    weekly = weekly_rank(db, None, None, "stock", "turnover", 10, sector_code="new_test")
    assert weekly["items"][0]["target_code"] == "600001"
    assert weekly["items"][0]["turnover"] == 550

    compare = compare_daily(db, "stock", "600001", "2026-07-03", sector_code="new_test", days=3)
    assert [item["trade_date"] for item in compare["items"]] == ["2026-07-03", "2026-07-02", "2026-07-01"]
    assert compare["items"][0]["turnover_change_percent"] == 100.0
    assert compare["items"][1]["turnover_change_percent"] == 50.0


def test_rebuild_daily_replaces_existing_rows():
    db = _db()
    _seed_snapshot(db, "2026-07-01", 0, 1000, 100)
    rebuild_daily_aggregate(db, "2026-07-01")
    rebuild_daily_aggregate(db, "2026-07-01")
    db.commit()

    rows = db.scalars(select(DailyAggregate).where(DailyAggregate.trade_date == "2026-07-01")).all()
    assert len(rows) == 3


def test_recent_weekly_rebuild_sees_uncommitted_daily_rows():
    db = _db()
    _seed_snapshot(db, "2026-07-01", 0, 1000, 100)

    rebuild_daily_aggregate(db, "2026-07-01")
    rows = rebuild_recent_weekly_aggregates(db)

    assert rows == 3
    assert db.scalar(select(WeeklyAggregate.id)) is not None
