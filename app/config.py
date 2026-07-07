from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Panlong Rank"
    data_provider: str = "auto"
    database_url: str = "sqlite:///./panlong_rank.sqlite3"
    redis_url: Optional[str] = None
    tushare_token: Optional[str] = None
    rank_limit: int = 10
    cache_ttl_seconds: int = 30
    scheduler_enabled: bool = True
    collect_on_startup: bool = True
    collect_interval_seconds: int = 120
    min_collect_interval_seconds: int = 60
    collect_timeout_seconds: int = 150
    sina_detail_board_limit: int = 16
    max_realtime_snapshot_age_seconds: int = 600
    period_boundary_tolerance_seconds: int = 300
    max_period_snapshot_gap_seconds: int = 600
    complete_day_min_snapshot_time: str = "14:50"
    use_sample_when_provider_fails: bool = False
    snapshot_keep_trade_dates: int = 30
    aggregate_keep_trade_days: int = 30
    backfill_enabled: bool = True
    backfill_interval_seconds: int = 300
    backfill_batch_size: int = 3
    backfill_max_attempts: int = 3

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
