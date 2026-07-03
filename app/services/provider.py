from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from app.config import Settings
from app.models import BoardQuote, IndexQuote, MarketSnapshot, StockQuote, TradingStatus
from app.services.sample_data import build_sample_snapshot

CN_TZ = ZoneInfo("Asia/Shanghai")


class MarketDataProvider:
    def snapshot(self, trading_status: TradingStatus) -> MarketSnapshot:
        raise NotImplementedError


class SampleMarketDataProvider(MarketDataProvider):
    def snapshot(self, trading_status: TradingStatus) -> MarketSnapshot:
        return build_sample_snapshot(trading_status)


class AkshareMarketDataProvider(MarketDataProvider):
    def snapshot(self, trading_status: TradingStatus) -> MarketSnapshot:
        try:
            import akshare as ak

            index = self._index_quote(ak, trading_status)
            boards = self._board_quotes(ak)
            stocks = self._stock_quotes(ak, boards)
            if not boards or not stocks:
                raise RuntimeError("AKShare returned incomplete market data")
            return MarketSnapshot(index=index, boards=boards, stocks=stocks, trading_status=trading_status)
        except Exception:
            return build_sample_snapshot(trading_status)

    def _index_quote(self, ak, trading_status: TradingStatus) -> IndexQuote:
        now = datetime.now(CN_TZ)
        df = ak.stock_zh_index_spot_em()
        row = _find_row(df, ["代码", "code"], "000001") or _find_contains(df, ["名称", "name"], "上证")
        if row is None:
            raise RuntimeError("SSE index quote not found")
        current = _num(row, ["最新价", "最新", "price"])
        prev_close = _num(row, ["昨收", "昨日收盘"])
        change = _num(row, ["涨跌额"]) if _has_any(row, ["涨跌额"]) else current - prev_close
        return IndexQuote(
            name=str(_value(row, ["名称", "name"], "上证指数")),
            code=str(_value(row, ["代码", "code"], "000001")),
            current=current,
            change=change,
            change_percent=_num(row, ["涨跌幅", "涨跌幅%"]),
            volume=_num(row, ["成交量"]),
            amount=_num(row, ["成交额"]),
            updated_at=now,
            trading_status=trading_status,
        )

    def _board_quotes(self, ak) -> list[BoardQuote]:
        now = datetime.now(CN_TZ)
        df = ak.stock_board_industry_name_em()
        boards: list[BoardQuote] = []
        for _, row in df.head(40).iterrows():
            boards.append(
                BoardQuote(
                    code=str(_value(row, ["板块代码", "代码"], "")),
                    name=str(_value(row, ["板块名称", "名称"], "")),
                    change_percent=_num(row, ["涨跌幅"]),
                    volume=_num(row, ["成交量"]),
                    amount=_num(row, ["成交额"]),
                    capital_flow=_num(row, ["主力净流入", "资金净流入", "净流入"]) or _num(row, ["成交额"]),
                    leader_stock_code=str(_value(row, ["领涨股票代码", "领涨股代码"], "")) or None,
                    leader_stock_name=str(_value(row, ["领涨股票", "领涨股"], "")) or None,
                    updated_at=now,
                )
            )
        return [b for b in boards if b.code and b.name]

    def _stock_quotes(self, ak, boards: list[BoardQuote]) -> list[StockQuote]:
        now = datetime.now(CN_TZ)
        stocks: list[StockQuote] = []
        selected_boards = boards[:16]
        for board in selected_boards:
            try:
                df = ak.stock_board_industry_cons_em(symbol=board.name)
            except Exception:
                continue
            for _, row in df.head(30).iterrows():
                amount = _num(row, ["成交额"])
                stocks.append(
                    StockQuote(
                        code=str(_value(row, ["代码"], "")),
                        name=str(_value(row, ["名称"], "")),
                        board_code=board.code,
                        board_name=board.name,
                        price=_num(row, ["最新价"]),
                        change_percent=_num(row, ["涨跌幅"]),
                        volume=_num(row, ["成交量"]),
                        amount=amount,
                        capital_flow=_num(row, ["主力净流入", "资金净流入"]) or amount,
                        updated_at=now,
                    )
                )
        return [s for s in stocks if s.code and s.name]


def get_provider(settings: Settings) -> MarketDataProvider:
    provider = settings.data_provider.lower()
    if provider == "sample":
        return SampleMarketDataProvider()
    if provider in {"auto", "akshare"}:
        return AkshareMarketDataProvider()
    return SampleMarketDataProvider()


def _find_row(df: pd.DataFrame, columns: list[str], expected: str):
    for column in columns:
        if column in df.columns:
            matches = df[df[column].astype(str) == expected]
            if not matches.empty:
                return matches.iloc[0]
    return None


def _find_contains(df: pd.DataFrame, columns: list[str], expected: str):
    for column in columns:
        if column in df.columns:
            matches = df[df[column].astype(str).str.contains(expected, na=False)]
            if not matches.empty:
                return matches.iloc[0]
    return None


def _has_any(row, columns: list[str]) -> bool:
    return any(column in row for column in columns)


def _value(row, columns: list[str], default=None):
    for column in columns:
        if column in row and pd.notna(row[column]):
            return row[column]
    return default


def _num(row, columns: list[str]) -> float:
    value = _value(row, columns, 0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
