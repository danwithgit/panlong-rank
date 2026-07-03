from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional

from app.models import Timeframe


@dataclass(frozen=True)
class PeriodSpec:
    timeframe: Timeframe
    period_type: str
    label: str
    start: Optional[time]
    end: Optional[time]


PERIODS: dict[Timeframe, PeriodSpec] = {
    Timeframe.realtime: PeriodSpec(Timeframe.realtime, "realtime", "实时榜", None, None),
    Timeframe.hour_0930_1030: PeriodSpec(Timeframe.hour_0930_1030, "hourly", "09:30-10:30", time(9, 30), time(10, 30)),
    Timeframe.hour_1030_1130: PeriodSpec(Timeframe.hour_1030_1130, "hourly", "10:30-11:30", time(10, 30), time(11, 30)),
    Timeframe.hour_1300_1400: PeriodSpec(Timeframe.hour_1300_1400, "hourly", "13:00-14:00", time(13, 0), time(14, 0)),
    Timeframe.hour_1400_1500: PeriodSpec(Timeframe.hour_1400_1500, "hourly", "14:00-15:00", time(14, 0), time(15, 0)),
    Timeframe.morning: PeriodSpec(Timeframe.morning, "morning", "上午榜", time(9, 30), time(11, 30)),
    Timeframe.afternoon: PeriodSpec(Timeframe.afternoon, "afternoon", "下午榜", time(13, 0), time(15, 0)),
    Timeframe.closing: PeriodSpec(Timeframe.closing, "tail", "尾盘榜", time(14, 30), time(15, 0)),
    Timeframe.daily: PeriodSpec(Timeframe.daily, "daily", "当日总榜", None, None),
    Timeframe.last_trade_day: PeriodSpec(Timeframe.last_trade_day, "last_trade_day", "最近一个交易日榜", None, None),
}


def period_for(timeframe: Timeframe) -> PeriodSpec:
    return PERIODS[timeframe]


def combine_trade_time(trade_date: str, value: Optional[time]) -> Optional[datetime]:
    if value is None:
        return None
    return datetime.combine(datetime.strptime(trade_date, "%Y-%m-%d").date(), value)


def period_options() -> list[dict]:
    return [
        {
            "timeframe": spec.timeframe.value,
            "period": spec.period_type,
            "label": spec.label,
            "start": spec.start.strftime("%H:%M") if spec.start else None,
            "end": spec.end.strftime("%H:%M") if spec.end else None,
        }
        for spec in PERIODS.values()
    ]
