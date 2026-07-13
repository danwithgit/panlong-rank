from datetime import datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.db.tables import DailyAggregate, IndexSnapshot, SectorSnapshot, StockSectorMap, StockSnapshot, TradingCalendar, WeeklyAggregate
from app.services.aggregates import rebuild_daily_aggregate, rebuild_recent_weekly_aggregates
from app.services.history_rankings import (
    compare_daily,
    daily_rank,
    recent_daily_options,
    recent_weekly_options,
    summary_report,
    weekly_rank,
)


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False)()


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
    db.flush()
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
    assert weeks == [{"week_start": "2026-06-29", "week_end": "2026-07-03", "label": "2026-06-29 ~ 2026-07-03"}]

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


def test_history_rank_change_metric_orders_by_change_percent_desc():
    db = _db()
    now = datetime(2026, 7, 6, 15, 0, 0)
    daily_rows = [
        ("sector_down", "下跌高成交板块", -3.2, 9000),
        ("sector_up", "上涨低成交板块", 4.8, 1000),
        ("sector_mid", "小涨中成交板块", 1.5, 5000),
    ]
    weekly_rows = [
        ("week_down", "周跌高成交板块", -2.1, 30000),
        ("week_up", "周涨低成交板块", 8.6, 8000),
        ("week_mid", "周小涨中成交板块", 3.4, 16000),
    ]
    for code, name, change_percent, turnover in daily_rows:
        db.add(
            DailyAggregate(
                trade_date="2026-07-06",
                target_type="sector",
                target_code=code,
                target_name=name,
                open_price=0,
                close_price=0,
                high_price=0,
                low_price=0,
                change_percent=change_percent,
                volume=turnover / 10,
                turnover=turnover,
                fund_amount=turnover,
                snapshot_time=now,
                data_source="test",
                data_quality="live",
            )
        )
    for code, name, change_percent, turnover in weekly_rows:
        db.add(
            WeeklyAggregate(
                week_start="2026-07-01",
                week_end="2026-07-07",
                target_type="sector",
                target_code=code,
                target_name=name,
                open_price=0,
                close_price=0,
                high_price=0,
                low_price=0,
                change_percent=change_percent,
                volume=turnover / 10,
                turnover=turnover,
                fund_amount=turnover,
                trading_days=5,
                data_source="test",
                data_quality="live",
            )
        )
    db.commit()

    daily = daily_rank(db, "2026-07-06", "sector", "change", 10)
    weekly = weekly_rank(db, "2026-07-01", "2026-07-07", "sector", "change", 10)

    assert [item["target_code"] for item in daily["items"]] == ["sector_up", "sector_mid", "sector_down"]
    assert [item["change_percent"] for item in daily["items"]] == [4.8, 1.5, -3.2]
    assert [item["target_code"] for item in weekly["items"]] == ["week_up", "week_mid", "week_down"]
    assert [item["change_percent"] for item in weekly["items"]] == [8.6, 3.4, -2.1]


def test_summary_report_uses_latest_complete_trading_days_for_cumulative_metrics():
    db = _db()
    now = datetime(2026, 7, 13, 15, 0, 0)
    complete_dates = ["2026-07-07", "2026-07-08", "2026-07-09", "2026-07-10", "2026-07-13"]
    for index, trade_date in enumerate(complete_dates):
        db.add(
            DailyAggregate(
                trade_date=trade_date,
                target_type="sector",
                target_code="steady",
                target_name="累计量板块",
                open_price=0,
                close_price=0,
                high_price=0,
                low_price=0,
                change_percent=0.5,
                volume=3000,
                turnover=100,
                fund_amount=0,
                snapshot_time=now + timedelta(days=index),
                data_source="test+fallback",
                data_quality="live",
            )
        )
        db.add(
            DailyAggregate(
                trade_date=trade_date,
                target_type="sector",
                target_code="today_hot",
                target_name="今日放量板块",
                open_price=0,
                close_price=0,
                high_price=0,
                low_price=0,
                change_percent=3,
                volume=5000 if trade_date == "2026-07-13" else 10,
                turnover=9000 if trade_date == "2026-07-13" else 10,
                fund_amount=0,
                snapshot_time=now + timedelta(days=index),
                data_source="test",
                data_quality="live",
            )
        )
        db.add(
            DailyAggregate(
                trade_date=trade_date,
                target_type="sector",
                target_code="turnover_week",
                target_name="累计额板块",
                open_price=0,
                close_price=0,
                high_price=0,
                low_price=0,
                change_percent=1,
                volume=100,
                turnover=4000,
                fund_amount=0,
                snapshot_time=now + timedelta(days=index),
                data_source="test",
                data_quality="live",
            )
        )
    for index, trade_date in enumerate(["2026-07-03", "2026-07-06"], start=10):
        db.add(
            DailyAggregate(
                trade_date=trade_date,
                target_type="sector",
                target_code="partial_big",
                target_name="残缺高量板块",
                open_price=0,
                close_price=0,
                high_price=0,
                low_price=0,
                change_percent=10,
                volume=999999,
                turnover=999999,
                fund_amount=0,
                snapshot_time=now + timedelta(days=index),
                data_source="test",
                data_quality="partial",
            )
        )
    db.commit()

    report = summary_report(db, "sector")
    items = {item["key"]: item for item in report["items"]}

    assert report["trade_date"] == "2026-07-13"
    assert report["period"] == "3d"
    assert report["days"] == 3
    assert report["expected_days"] == 3
    assert report["dates"] == ["2026-07-13", "2026-07-10", "2026-07-09"]
    assert "按成交量口径" in report["metric_note"]
    assert items["today_volume"]["item"]["target_code"] == "today_hot"
    assert items["today_turnover"]["item"]["target_code"] == "today_hot"
    assert items["period_volume"]["item"]["target_code"] == "steady"
    assert items["period_volume"]["item"]["volume"] == 9000
    assert items["period_volume"]["item"]["data_source"] == "fallback+test"
    assert items["period_turnover"]["item"]["target_code"] == "turnover_week"
    assert items["period_turnover"]["item"]["turnover"] == 12000

    five_day_report = summary_report(db, "sector", "5d")
    five_day_items = {item["key"]: item for item in five_day_report["items"]}

    assert five_day_report["days"] == 5
    assert five_day_report["dates"] == ["2026-07-13", "2026-07-10", "2026-07-09", "2026-07-08", "2026-07-07"]
    assert five_day_items["period_volume"]["item"]["target_code"] == "steady"
    assert five_day_items["period_volume"]["item"]["volume"] == 15000
    assert five_day_items["period_turnover"]["item"]["target_code"] == "turnover_week"
    assert five_day_items["period_turnover"]["item"]["turnover"] == 20000
    assert "partial_big" not in {item["item"]["target_code"] for item in five_day_report["items"] if item["item"]}


def test_summary_report_week_uses_current_complete_calendar_week():
    db = _db()
    now = datetime(2026, 7, 13, 15, 0, 0)
    for trade_date in ["2026-07-10", "2026-07-13"]:
        for code, name, volume, turnover in [
            ("a", "板块A", 100, 1000),
            ("b", "板块B", 200, 2000),
        ]:
            db.add(
                DailyAggregate(
                    trade_date=trade_date,
                    target_type="sector",
                    target_code=code,
                    target_name=name,
                    open_price=0,
                    close_price=0,
                    high_price=0,
                    low_price=0,
                    change_percent=1,
                    volume=volume,
                    turnover=turnover,
                    fund_amount=0,
                    snapshot_time=now,
                    data_source="test",
                    data_quality="live",
                )
            )
    db.commit()

    report = summary_report(db, "sector", "week")

    assert report["period"] == "week"
    assert report["period_label"] == "本周"
    assert report["dates"] == ["2026-07-13"]
    assert report["days"] == 1


def test_history_api_defaults_to_change_metric():
    import inspect

    from app.main import history_daily_rank, history_weekly_rank

    daily_metric = inspect.signature(history_daily_rank).parameters["metric"].default
    weekly_metric = inspect.signature(history_weekly_rank).parameters["metric"].default

    assert daily_metric.default == "change"
    assert weekly_metric.default == "change"


def test_compare_daily_returns_actual_selected_date_when_requested_date_missing():
    db = _db()
    now = datetime(2026, 7, 10, 15, 0, 0)
    for trade_date, turnover in [("2026-07-10", 1000), ("2026-07-09", 800)]:
        db.add(
            DailyAggregate(
                trade_date=trade_date,
                target_type="sector",
                target_code="sector_test",
                target_name="测试板块",
                open_price=0,
                close_price=0,
                high_price=0,
                low_price=0,
                change_percent=1,
                volume=turnover / 10,
                turnover=turnover,
                fund_amount=0,
                snapshot_time=now,
                data_source="test",
                data_quality="live",
            )
        )
    db.commit()

    result = compare_daily(db, "sector", "sector_test", "2099-01-01", days=2)

    assert result["trade_date"] == "2026-07-10"
    assert [item["trade_date"] for item in result["items"]] == ["2026-07-10", "2026-07-09"]


def test_weekly_sector_change_compounds_daily_change_when_prices_missing():
    db = _db()
    now = datetime(2026, 7, 6, 15, 0, 0)
    rows = [
        ("2026-07-06", "strong_then_small", "先强后小涨", 8.0, 1000),
        ("2026-07-07", "strong_then_small", "先强后小涨", 0.5, 1000),
        ("2026-07-06", "last_day_only", "最后一天大涨", -2.0, 2000),
        ("2026-07-07", "last_day_only", "最后一天大涨", 4.0, 2000),
    ]
    for trade_date, code, name, change_percent, turnover in rows:
        db.add(
            DailyAggregate(
                trade_date=trade_date,
                target_type="sector",
                target_code=code,
                target_name=name,
                open_price=0,
                close_price=0,
                high_price=0,
                low_price=0,
                change_percent=change_percent,
                volume=turnover / 10,
                turnover=turnover,
                fund_amount=turnover,
                snapshot_time=now,
                data_source="test",
                data_quality="live",
            )
        )
    rebuild_recent_weekly_aggregates(db, max_weeks=1)
    db.commit()

    weekly = weekly_rank(db, "2026-07-06", "2026-07-10", "sector", "change", 10)

    assert [item["target_code"] for item in weekly["items"][:2]] == ["strong_then_small", "last_day_only"]
    assert weekly["items"][0]["change_percent"] == 8.54
    assert weekly["items"][1]["change_percent"] == 1.92


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


def test_weekly_quality_is_partial_when_expected_trade_day_missing():
    db = _db()
    for value in ["2026-07-06", "2026-07-07"]:
        db.add(
            TradingCalendar(
                trade_date=value,
                is_open=True,
                pretrade_date="2026-07-03",
            )
        )
    db.add(
        DailyAggregate(
            trade_date="2026-07-06",
            target_type="sector",
            target_code="sector_one_day",
            target_name="只有一天",
            open_price=0,
            close_price=0,
            high_price=0,
            low_price=0,
            change_percent=5,
            volume=100,
            turnover=1000,
            fund_amount=0,
            snapshot_time=datetime(2026, 7, 6, 15, 0, 0),
            data_source="test",
            data_quality="live",
        )
    )

    rebuild_recent_weekly_aggregates(db, max_weeks=1)
    db.commit()

    weekly = weekly_rank(db, "2026-07-06", "2026-07-10", "sector", "change", 10)

    assert weekly["data_quality"] == "partial"
    assert weekly["items"][0]["trading_days"] == 1
    assert weekly["items"][0]["expected_trading_days"] == 2
    assert weekly["items"][0]["missing_trading_days"] == 1
