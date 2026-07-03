from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from app.models import (
    BoardQuote,
    MarketSnapshot,
    RankingBlock,
    RankingItem,
    StockQuote,
    Timeframe,
    TIMEFRAME_LABELS,
)

TAIL_TIMEFRAMES = {Timeframe.closing, Timeframe.hour_1400_1500}


def build_board_rankings(snapshot: MarketSnapshot, timeframe: Timeframe, limit: int) -> list[RankingBlock]:
    boards = _apply_timeframe_to_boards(snapshot.boards, timeframe)
    definitions: list[tuple[str, str, str, Callable[[BoardQuote], float]]] = [
        ("board_amount", "板块成交额排行榜", "amount", lambda item: item.amount),
        ("board_volume", "板块成交量排行榜", "volume", lambda item: item.volume),
        ("board_capital_flow", "板块资金量排行榜", "capital_flow", lambda item: item.capital_flow),
        ("board_change", "板块涨幅排行榜", "change_percent", lambda item: item.change_percent),
    ]
    if timeframe in TAIL_TIMEFRAMES:
        definitions.extend(
            [
                ("board_closing_amount", "板块尾盘成交额排行榜", "amount", lambda item: item.amount),
                ("board_closing_capital_flow", "板块尾盘资金量排行榜", "capital_flow", lambda item: item.capital_flow),
            ]
        )
    return [_rank_boards(key, title, metric, boards, scorer, limit) for key, title, metric, scorer in definitions]


def build_stock_rankings(
    snapshot: MarketSnapshot,
    timeframe: Timeframe,
    limit: int,
    board_code: Optional[str] = None,
) -> list[RankingBlock]:
    stocks = snapshot.stocks
    if board_code:
        stocks = [stock for stock in stocks if stock.board_code == board_code]
    stocks = _apply_timeframe_to_stocks(stocks, timeframe)
    definitions: list[tuple[str, str, str, Callable[[StockQuote], float]]] = [
        ("stock_amount", "个股成交额排行", "amount", lambda item: item.amount),
        ("stock_volume", "个股成交量排行", "volume", lambda item: item.volume),
        ("stock_change", "个股涨幅排行", "change_percent", lambda item: item.change_percent),
        ("stock_capital_flow", "个股资金量排行", "capital_flow", lambda item: item.capital_flow),
    ]
    if timeframe in TAIL_TIMEFRAMES:
        definitions.extend(
            [
                ("stock_closing_amount", "个股尾盘成交额排行", "amount", lambda item: item.amount),
                ("stock_closing_capital_flow", "个股尾盘资金量排行", "capital_flow", lambda item: item.capital_flow),
            ]
        )
    leaders = {board.leader_stock_code for board in snapshot.boards if board.leader_stock_code}
    return [_rank_stocks(key, title, metric, stocks, scorer, limit, leaders) for key, title, metric, scorer in definitions]


def build_leader_rankings(snapshot: MarketSnapshot, timeframe: Timeframe, limit: int) -> list[RankingBlock]:
    leaders_by_board = {board.code: board.leader_stock_code for board in snapshot.boards if board.leader_stock_code}
    leader_stocks = [
        stock for stock in snapshot.stocks if leaders_by_board.get(stock.board_code) == stock.code
    ]
    leader_stocks = _apply_timeframe_to_stocks(leader_stocks, timeframe)
    definitions: list[tuple[str, str, str, Callable[[StockQuote], float]]] = [
        ("leader_volume", "龙头股成交量排行榜", "volume", lambda item: item.volume),
        ("leader_amount", "龙头股成交额排行榜", "amount", lambda item: item.amount),
        ("leader_capital_flow", "龙头股资金量排行榜", "capital_flow", lambda item: item.capital_flow),
        ("leader_change", "龙头股涨幅排行榜", "change_percent", lambda item: item.change_percent),
    ]
    if timeframe in TAIL_TIMEFRAMES:
        definitions.extend(
            [
                ("leader_closing_volume", "龙头股尾盘成交量排行榜", "volume", lambda item: item.volume),
                ("leader_closing_capital_flow", "龙头股尾盘资金量排行榜", "capital_flow", lambda item: item.capital_flow),
            ]
        )
    return [_rank_stocks(key, title, metric, leader_stocks, scorer, limit, set(leaders_by_board.values())) for key, title, metric, scorer in definitions]


def find_board(snapshot: MarketSnapshot, board_code: str) -> Optional[BoardQuote]:
    for board in snapshot.boards:
        if board.code == board_code:
            return board
    return None


def timeframe_label(timeframe: Timeframe) -> str:
    return TIMEFRAME_LABELS[timeframe]


def calculate_interval_value(start_value: float, end_value: float) -> float:
    return max(end_value - start_value, 0)


def calculate_interval_change_percent(start_price: float, end_price: float) -> float:
    if start_price <= 0:
        return 0
    return round((end_price - start_price) / start_price * 100, 4)


def _rank_boards(
    key: str,
    title: str,
    metric: str,
    boards: list[BoardQuote],
    scorer: Callable[[BoardQuote], float],
    limit: int,
) -> RankingBlock:
    items = sorted(boards, key=scorer, reverse=True)[:limit]
    return RankingBlock(
        key=key,
        title=title,
        metric=metric,
        items=[
            RankingItem(
                rank=index,
                board_name=item.name,
                board_code=item.code,
                change_percent=item.change_percent,
                volume=item.volume,
                amount=item.amount,
                capital_flow=item.capital_flow,
                leader_stock_name=item.leader_stock_name,
                leader_stock_code=item.leader_stock_code,
                updated_at=item.updated_at,
            )
            for index, item in enumerate(items, start=1)
        ],
    )


def _rank_stocks(
    key: str,
    title: str,
    metric: str,
    stocks: list[StockQuote],
    scorer: Callable[[StockQuote], float],
    limit: int,
    leaders: set[Optional[str]],
) -> RankingBlock:
    items = sorted(stocks, key=scorer, reverse=True)[:limit]
    return RankingBlock(
        key=key,
        title=title,
        metric=metric,
        items=[
            RankingItem(
                rank=index,
                board_name=item.board_name,
                board_code=item.board_code,
                stock_name=item.name,
                stock_code=item.code,
                current_price=item.price,
                change_percent=item.change_percent,
                volume=item.volume,
                amount=item.amount,
                capital_flow=item.capital_flow,
                is_leader=item.code in leaders,
                updated_at=item.updated_at,
            )
            for index, item in enumerate(items, start=1)
        ],
    )


def _apply_timeframe_to_boards(boards: list[BoardQuote], timeframe: Timeframe) -> list[BoardQuote]:
    scale = _timeframe_scale(timeframe)
    return [
        board.model_copy(
            update={
                "volume": round(board.volume * scale, 2),
                "amount": round(board.amount * scale, 2),
                "capital_flow": round(board.capital_flow * scale, 2),
                "change_percent": round(board.change_percent * _change_scale(timeframe), 2),
            }
        )
        for board in boards
    ]


def _apply_timeframe_to_stocks(stocks: list[StockQuote], timeframe: Timeframe) -> list[StockQuote]:
    scale = _timeframe_scale(timeframe)
    return [
        stock.model_copy(
            update={
                "volume": round(stock.volume * scale, 2),
                "amount": round(stock.amount * scale, 2),
                "capital_flow": round(stock.capital_flow * scale, 2),
                "change_percent": round(stock.change_percent * _change_scale(timeframe), 2),
            }
        )
        for stock in stocks
    ]


def _timeframe_scale(timeframe: Timeframe) -> float:
    return {
        Timeframe.realtime: 1.0,
        Timeframe.hour_0930_1030: 0.26,
        Timeframe.hour_1030_1130: 0.24,
        Timeframe.hour_1300_1400: 0.25,
        Timeframe.hour_1400_1500: 0.25,
        Timeframe.morning: 0.5,
        Timeframe.afternoon: 0.5,
        Timeframe.closing: 0.18,
        Timeframe.daily: 1.0,
        Timeframe.last_trade_day: 1.0,
    }[timeframe]


def _change_scale(timeframe: Timeframe) -> float:
    return {
        Timeframe.realtime: 1.0,
        Timeframe.hour_0930_1030: 0.45,
        Timeframe.hour_1030_1130: 0.4,
        Timeframe.hour_1300_1400: 0.38,
        Timeframe.hour_1400_1500: 0.42,
        Timeframe.morning: 0.65,
        Timeframe.afternoon: 0.65,
        Timeframe.closing: 0.32,
        Timeframe.daily: 1.0,
        Timeframe.last_trade_day: 1.0,
    }[timeframe]
