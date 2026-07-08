import sys
import types

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.session import Base
from app.db.tables import BackfillTask, DailyAggregate, StockSectorMap
from app.services import backfill
from app.services.backfill import run_backfill_batch, seed_stock_daily_backfill_tasks


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_seed_backfill_skips_unsupported_stock_codes(monkeypatch):
    db = _db()
    backfill._akshare_trade_date_set.cache_clear()
    monkeypatch.setattr(backfill, "_akshare_trade_dates", lambda days: ["2026-07-08", "2026-07-07"][:days])
    db.add(
        StockSectorMap(
            stock_code="200152",
            stock_name="山航B退",
            sector_code="new_test",
            sector_name="测试板块",
            sector_type="industry",
        )
    )
    db.add(
        StockSectorMap(
            stock_code="600001",
            stock_name="测试股票",
            sector_code="new_test",
            sector_name="测试板块",
            sector_type="industry",
        )
    )
    db.commit()

    created = seed_stock_daily_backfill_tasks(db, Settings(aggregate_keep_trade_days=2, backfill_batch_size=1))

    assert created == 4
    tasks = db.scalars(select(BackfillTask)).all()
    assert {task.target_code for task in tasks} == {"000001", "600001"}


def test_backfill_skips_non_trade_dates(monkeypatch):
    db = _db()
    backfill._akshare_trade_date_set.cache_clear()
    monkeypatch.setattr(backfill, "_akshare_trade_dates", lambda days: ["2026-07-10"])
    db.add(
        BackfillTask(
            task_type="daily_hist",
            target_type="stock",
            target_code="600001",
            target_name="测试股票",
            sector_code="new_test",
            sector_name="测试板块",
            trade_date="2026-07-11",
            status="pending",
        )
    )
    db.commit()

    result = run_backfill_batch(db, Settings(backfill_batch_size=1))

    task = db.scalar(select(BackfillTask))
    assert result["skipped"] == 1
    assert task.status == "skipped"
    assert "non-trade" in task.last_error


def test_index_backfill_writes_daily_aggregate(monkeypatch):
    db = _db()
    backfill._akshare_trade_date_set.cache_clear()
    monkeypatch.setattr(backfill, "_akshare_trade_dates", lambda days: ["2026-07-08"])
    fake_ak = types.SimpleNamespace(
        stock_zh_index_daily=lambda symbol: pd.DataFrame(
            [
                {
                    "date": "2026-07-08",
                    "open": 4000,
                    "close": 4040,
                    "high": 4050,
                    "low": 3990,
                    "volume": 100,
                    "amount": 200,
                }
            ]
        )
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)
    db.add(
        BackfillTask(
            task_type="daily_hist",
            target_type="index",
            target_code="000001",
            target_name="上证指数",
            trade_date="2026-07-08",
            status="pending",
        )
    )
    db.commit()

    result = run_backfill_batch(db, Settings(backfill_batch_size=1))

    row = db.scalar(select(DailyAggregate).where(DailyAggregate.target_type == "index"))
    assert result["succeeded"] == 1
    assert row is not None
    assert row.close_price == 4040
    assert row.change_percent == 1.0


def test_index_backfill_runs_before_stock_queue(monkeypatch):
    db = _db()
    backfill._akshare_trade_date_set.cache_clear()
    monkeypatch.setattr(backfill, "_akshare_trade_dates", lambda days: ["2026-07-08"])
    fake_ak = types.SimpleNamespace(
        stock_zh_index_daily=lambda symbol: pd.DataFrame(
            [{"date": "2026-07-08", "open": 4000, "close": 4040, "high": 4050, "low": 3990, "volume": 100, "amount": 200}]
        ),
        stock_zh_a_hist=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("stock should not run first")),
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)
    db.add(
        BackfillTask(
            task_type="daily_hist",
            target_type="stock",
            target_code="600001",
            target_name="测试股票",
            sector_code="new_test",
            sector_name="测试板块",
            trade_date="2026-07-08",
            status="pending",
        )
    )
    db.add(
        BackfillTask(
            task_type="daily_hist",
            target_type="index",
            target_code="000001",
            target_name="上证指数",
            trade_date="2026-07-08",
            status="pending",
        )
    )
    db.commit()

    result = run_backfill_batch(db, Settings(backfill_batch_size=1))

    index_task = db.scalar(select(BackfillTask).where(BackfillTask.target_type == "index"))
    stock_task = db.scalar(select(BackfillTask).where(BackfillTask.target_type == "stock"))
    assert result["succeeded"] == 1
    assert index_task.status == "success"
    assert stock_task.status == "pending"


def test_stock_backfill_falls_back_to_sina_history(monkeypatch):
    db = _db()
    backfill._akshare_trade_date_set.cache_clear()
    monkeypatch.setattr(backfill, "_akshare_trade_dates", lambda days: ["2026-07-08"])

    def fail_em(**kwargs):
        raise RuntimeError("eastmoney history unavailable")

    fake_ak = types.SimpleNamespace(
        stock_zh_a_hist=fail_em,
        stock_zh_a_daily=lambda **kwargs: pd.DataFrame(
            [
                {
                    "date": "2026-07-08",
                    "open": 10,
                    "close": 11,
                    "high": 12,
                    "low": 9,
                    "volume": 100,
                    "amount": 2000,
                }
            ]
        ),
        stock_zh_a_hist_tx=lambda **kwargs: (_ for _ in ()).throw(AssertionError("Tencent should not run after Sina succeeds")),
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)
    db.add(
        BackfillTask(
            task_type="daily_hist",
            target_type="stock",
            target_code="600001",
            target_name="测试股票",
            sector_code="new_test",
            sector_name="测试板块",
            trade_date="2026-07-08",
            status="pending",
        )
    )
    db.commit()

    result = run_backfill_batch(db, Settings(backfill_batch_size=1))

    row = db.scalar(select(DailyAggregate).where(DailyAggregate.target_type == "stock"))
    assert result["succeeded"] == 1
    assert row is not None
    assert row.close_price == 11
    assert row.turnover == 2000
    assert row.data_source == "akshare_hist_sina"
