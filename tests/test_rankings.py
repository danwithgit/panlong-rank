from app.models import Timeframe
from app.services.calendar import get_trading_status
from app.config import Settings
from app.services.rankings import (
    build_board_rankings,
    calculate_interval_change_percent,
    calculate_interval_value,
)
from app.services.sample_data import build_sample_snapshot


def test_interval_value_never_negative():
    assert calculate_interval_value(100, 150) == 50
    assert calculate_interval_value(150, 100) == 0


def test_interval_change_percent():
    assert calculate_interval_change_percent(10, 11) == 10
    assert calculate_interval_change_percent(0, 11) == 0


def test_board_rankings_limit_and_tail_blocks():
    status = get_trading_status(Settings(data_provider="sample"))
    snapshot = build_sample_snapshot(status)
    rankings = build_board_rankings(snapshot, Timeframe.closing, 5)

    assert len(rankings) == 6
    assert all(len(block.items) == 5 for block in rankings)
    assert rankings[0].items[0].amount >= rankings[0].items[-1].amount
