from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from app.config import Settings
from app.models import TradingStatus

CN_TZ = ZoneInfo("Asia/Shanghai")


def current_session(now: Optional[datetime] = None) -> str:
    now = now.astimezone(CN_TZ) if now else datetime.now(CN_TZ)
    t = now.time()
    if time(9, 30) <= t < time(11, 30):
        return "morning_trading"
    if time(11, 30) <= t < time(13, 0):
        return "lunch_break"
    if time(13, 0) <= t < time(14, 30):
        return "afternoon_trading"
    if time(14, 30) <= t < time(15, 0):
        return "closing_trading"
    if t >= time(15, 0):
        return "closed"
    return "pre_open"


def previous_weekday(value: date) -> date:
    candidate = value - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def get_trading_status(settings: Settings, now: Optional[datetime] = None) -> TradingStatus:
    now = now.astimezone(CN_TZ) if now else datetime.now(CN_TZ)
    today = now.date()

    tushare_status = _get_tushare_status(settings, today)
    if tushare_status is not None:
        is_open, last_trade_date = tushare_status
    else:
        is_open = today.weekday() < 5
        last_trade_date = today if is_open else previous_weekday(today)

    message = None
    if not is_open:
        message = "当前为非交易日，显示最近一个交易日数据。"

    return TradingStatus(
        is_trade_day=is_open,
        trade_date=today.strftime("%Y-%m-%d"),
        last_trade_date=last_trade_date.strftime("%Y-%m-%d"),
        session=current_session(now),
        message=message,
    )


def _get_tushare_status(settings: Settings, today: date) -> Optional[tuple[bool, date]]:
    if not settings.tushare_token:
        return None

    try:
        import tushare as ts
    except Exception:
        return None

    try:
        pro = ts.pro_api(settings.tushare_token)
        today_text = today.strftime("%Y%m%d")
        df = pro.trade_cal(exchange="SSE", start_date=today_text, end_date=today_text)
        if df.empty:
            return None
        row = df.iloc[0]
        is_open = int(row.get("is_open", 0)) == 1
        pretrade = str(row.get("pretrade_date") or today_text)
        last_trade_date = today if is_open else datetime.strptime(pretrade, "%Y%m%d").date()
        return is_open, last_trade_date
    except Exception:
        return None
