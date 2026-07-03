from __future__ import annotations

from datetime import datetime
import logging
import time
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from app.config import Settings
from app.models import BoardQuote, IndexQuote, MarketSnapshot, StockQuote, TradingStatus
from app.services.sample_data import build_sample_snapshot

CN_TZ = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger(__name__)


class MarketDataProvider:
    def snapshot(self, trading_status: TradingStatus) -> MarketSnapshot:
        raise NotImplementedError


class SampleMarketDataProvider(MarketDataProvider):
    def snapshot(self, trading_status: TradingStatus) -> MarketSnapshot:
        return build_sample_snapshot(trading_status)


class AkshareMarketDataProvider(MarketDataProvider):
    def snapshot(self, trading_status: TradingStatus) -> MarketSnapshot:
        last_error = None
        for attempt in range(1, 4):
            try:
                return self._snapshot_once(trading_status)
            except Exception as exc:
                last_error = exc
                logger.warning("AKShare snapshot attempt %s failed: %s", attempt, exc)
                time.sleep(0.5 * attempt)
        logger.error("AKShare unavailable, using sample data: %s", last_error)
        return _eastmoney_index_sample_rankings(trading_status)

    def _snapshot_once(self, trading_status: TradingStatus) -> MarketSnapshot:
        try:
            import akshare as ak

            index = self._index_quote(ak, trading_status)
            boards = self._board_quotes(ak)
            stocks = self._stock_quotes(ak, boards)
            if not boards or not stocks:
                raise RuntimeError("AKShare returned incomplete market data")
            return MarketSnapshot(index=index, boards=boards, stocks=stocks, trading_status=trading_status, data_source="akshare")
        except Exception:
            raise

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
            data_source="akshare",
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


def _eastmoney_index_sample_rankings(trading_status: TradingStatus) -> MarketSnapshot:
    snapshot = build_sample_snapshot(trading_status)
    try:
        response = requests.get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            params={
                "secid": "1.000001",
                "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170",
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()["data"]
        index = snapshot.index.model_copy(
            update={
                "name": data.get("f58") or "上证指数",
                "code": data.get("f57") or "000001",
                "current": _scaled(data.get("f43")),
                "change": _scaled(data.get("f169")),
                "change_percent": _scaled(data.get("f170")),
                "volume": float(data.get("f47") or 0),
                "amount": float(data.get("f48") or 0),
                "updated_at": datetime.now(CN_TZ),
                "data_source": "eastmoney",
            }
        )
        return snapshot.model_copy(update={"index": index, "data_source": "eastmoney_index_sample_rankings"})
    except Exception as exc:
        logger.error("Eastmoney index fallback failed, using pure sample data: %s", exc)
        return snapshot.model_copy(update={"data_source": "sample_fallback"})


def _scaled(value) -> float:
    try:
        return round(float(value) / 100, 4)
    except (TypeError, ValueError):
        return 0.0


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
