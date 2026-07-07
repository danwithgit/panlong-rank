from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.session import Base
from app.db.tables import BackfillTask, StockSectorMap
from app.services.backfill import seed_stock_daily_backfill_tasks


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_seed_backfill_skips_unsupported_stock_codes():
    db = _db()
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

    assert created == 2
    tasks = db.scalars(select(BackfillTask)).all()
    assert {task.target_code for task in tasks} == {"600001"}
