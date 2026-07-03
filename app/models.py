from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Timeframe(str, Enum):
    realtime = "realtime"
    hour_0930_1030 = "hour_0930_1030"
    hour_1030_1130 = "hour_1030_1130"
    hour_1300_1400 = "hour_1300_1400"
    hour_1400_1500 = "hour_1400_1500"
    morning = "morning"
    afternoon = "afternoon"
    closing = "closing"
    daily = "daily"
    last_trade_day = "last_trade_day"


TIMEFRAME_LABELS: dict[Timeframe, str] = {
    Timeframe.realtime: "实时榜",
    Timeframe.hour_0930_1030: "09:30-10:30",
    Timeframe.hour_1030_1130: "10:30-11:30",
    Timeframe.hour_1300_1400: "13:00-14:00",
    Timeframe.hour_1400_1500: "14:00-15:00",
    Timeframe.morning: "上午榜",
    Timeframe.afternoon: "下午榜",
    Timeframe.closing: "尾盘榜",
    Timeframe.daily: "当日总榜",
    Timeframe.last_trade_day: "最近一个交易日榜",
}


class TradingStatus(BaseModel):
    is_trade_day: bool
    trade_date: str
    last_trade_date: str
    session: str
    message: Optional[str] = None


class IndexQuote(BaseModel):
    name: str
    code: str
    current: float
    change: float
    change_percent: float
    volume: float
    amount: float
    updated_at: datetime
    trading_status: TradingStatus


class StockQuote(BaseModel):
    code: str
    name: str
    board_code: str
    board_name: str
    price: float
    change_percent: float
    volume: float
    amount: float
    capital_flow: float
    updated_at: datetime


class BoardQuote(BaseModel):
    code: str
    name: str
    change_percent: float
    volume: float
    amount: float
    capital_flow: float
    leader_stock_code: Optional[str] = None
    leader_stock_name: Optional[str] = None
    updated_at: datetime


class MarketSnapshot(BaseModel):
    index: IndexQuote
    boards: list[BoardQuote]
    stocks: list[StockQuote]
    trading_status: TradingStatus


class RankingItem(BaseModel):
    rank: int
    board_name: Optional[str] = None
    board_code: Optional[str] = None
    stock_name: Optional[str] = None
    stock_code: Optional[str] = None
    current_price: Optional[float] = None
    change_percent: float
    volume: float
    amount: float
    capital_flow: float
    leader_stock_name: Optional[str] = None
    leader_stock_code: Optional[str] = None
    is_leader: bool = False
    updated_at: datetime


class RankingBlock(BaseModel):
    key: str
    title: str
    metric: str
    items: list[RankingItem] = Field(default_factory=list)


class DashboardResponse(BaseModel):
    timeframe: Timeframe
    timeframe_label: str
    index: IndexQuote
    trading_status: TradingStatus
    board_rankings: list[RankingBlock]
    leader_rankings: list[RankingBlock]


class BoardDetailResponse(BaseModel):
    timeframe: Timeframe
    timeframe_label: str
    board: BoardQuote
    stock_rankings: list[RankingBlock]
