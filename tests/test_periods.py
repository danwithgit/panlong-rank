from app.main import _parse_period
from app.models import Timeframe


def test_parse_period_accepts_document_aliases():
    assert _parse_period("tail") == Timeframe.closing
    assert _parse_period("hourly") == Timeframe.hour_0930_1030
    assert _parse_period("last_trade_day") == Timeframe.last_trade_day
