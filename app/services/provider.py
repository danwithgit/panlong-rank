from __future__ import annotations

from datetime import datetime
import logging
import time
from zoneinfo import ZoneInfo

import pandas as pd

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
        logger.error("AKShare unavailable after retries: %s", last_error)
        raise RuntimeError(f"AKShare unavailable after retries: {last_error}") from last_error

    def _snapshot_once(self, trading_status: TradingStatus, ak=None) -> MarketSnapshot:
        if ak is None:
            import akshare as ak

        source_parts: list[str] = []
        index = self._first_success(
            "index quote",
            [
                ("akshare_em", lambda: self._index_quote_em(ak, trading_status)),
                ("akshare_sina", lambda: self._index_quote_sina(ak, trading_status)),
            ],
            source_parts,
        )
        boards = self._first_success(
            "board quotes",
            [
                ("akshare_sina", lambda: self._board_quotes_sina(ak)),
                ("akshare_em", lambda: self._board_quotes_em(ak)),
            ],
            source_parts,
        )
        stocks = self._first_success(
            "stock quotes",
            self._stock_quote_candidates(ak, boards, source_parts),
            source_parts,
        )
        if not boards or not stocks:
            raise RuntimeError("AKShare returned incomplete market data")
        data_source = "+".join(dict.fromkeys(source_parts)) or "akshare"
        index = index.model_copy(update={"data_source": data_source})
        return MarketSnapshot(index=index, boards=boards, stocks=stocks, trading_status=trading_status, data_source=data_source)

    def _first_success(self, label: str, candidates, source_parts: list[str]):
        errors = []
        for source, loader in candidates:
            try:
                result = loader()
                if not result:
                    raise RuntimeError(f"{source} returned empty {label}")
                source_parts.append(source)
                return result
            except Exception as exc:
                errors.append(f"{source}: {exc}")
                logger.warning("AKShare %s provider %s failed: %s", label, source, exc)
        raise RuntimeError(f"All AKShare {label} providers failed: {'; '.join(errors)}")

    def _stock_quote_candidates(self, ak, boards: list[BoardQuote], source_parts: list[str]):
        has_em_board_codes = any(board.code.startswith("BK") for board in boards)
        if not has_em_board_codes and "akshare_sina" in source_parts:
            return [("akshare_sina", lambda: self._stock_quotes_sina(ak, boards))]
        return [
            ("akshare_em", lambda: self._stock_quotes_em(ak, boards)),
            ("akshare_sina", lambda: self._stock_quotes_sina(ak, boards)),
        ]

    def _index_quote_em(self, ak, trading_status: TradingStatus) -> IndexQuote:
        now = datetime.now(CN_TZ)
        df = ak.stock_zh_index_spot_em()
        row = _find_first(
            _find_row(df, ["代码", "code"], "000001"),
            _find_contains(df, ["名称", "name"], "上证"),
        )
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

    def _index_quote_sina(self, ak, trading_status: TradingStatus) -> IndexQuote:
        now = datetime.now(CN_TZ)
        df = ak.stock_zh_index_spot_sina()
        row = _find_first(
            _find_row(df, ["代码", "code"], "sh000001"),
            _find_row(df, ["代码", "code"], "000001"),
            _find_contains(df, ["名称", "name"], "上证"),
        )
        if row is None:
            raise RuntimeError("Sina SSE index quote not found")
        current = _num(row, ["最新价", "最新", "price"])
        change = _num(row, ["涨跌额", "pricechange"])
        return IndexQuote(
            name=str(_value(row, ["名称", "name"], "上证指数")),
            code=_normalize_code(str(_value(row, ["代码", "code"], "000001"))),
            current=current,
            change=change,
            change_percent=_num(row, ["涨跌幅", "涨跌幅%", "changepercent"]),
            volume=_num(row, ["成交量", "volume"]),
            amount=_num(row, ["成交额", "amount"]),
            updated_at=now,
            trading_status=trading_status,
            data_source="akshare_sina",
        )

    def _board_quotes_em(self, ak) -> list[BoardQuote]:
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

    def _board_quotes_sina(self, ak) -> list[BoardQuote]:
        now = datetime.now(CN_TZ)
        df = ak.stock_sector_spot()
        boards: list[BoardQuote] = []
        for _, row in df.head(49).iterrows():
            code = str(_value(row, ["label", "代码"], ""))
            name = str(_value(row, ["板块", "name"], ""))
            amount = _num(row, ["总成交额", "成交额", "amount"])
            boards.append(
                BoardQuote(
                    code=code,
                    name=name,
                    change_percent=_num(row, ["涨跌幅", "changepercent"]),
                    volume=_num(row, ["总成交量", "成交量", "volume"]),
                    amount=amount,
                    capital_flow=amount,
                    leader_stock_code=None,
                    leader_stock_name=None,
                    updated_at=now,
                )
            )
        return [b for b in boards if b.code and b.name]

    def _stock_quotes_em(self, ak, boards: list[BoardQuote]) -> list[StockQuote]:
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

    def _stock_quotes_sina(self, ak, boards: list[BoardQuote]) -> list[StockQuote]:
        now = datetime.now(CN_TZ)
        selected_boards = boards[:49]
        return self._sina_sector_detail_quotes(ak, selected_boards, now)

    def _sina_sector_detail_quotes(
        self,
        ak,
        boards: list[BoardQuote],
        now: datetime,
    ) -> list[StockQuote]:
        seen: set[tuple[str, str]] = set()
        stocks: list[StockQuote] = []
        for board in boards:
            try:
                df = ak.stock_sector_detail(sector=board.code)
            except Exception as exc:
                logger.warning("AKShare Sina board detail failed for %s %s: %s", board.code, board.name, exc)
                continue
            candidates = _stock_quotes_from_sector_detail(df, board, now)
            if not candidates:
                continue

            leader = max(candidates, key=lambda stock: (stock.change_percent, stock.amount))
            board.leader_stock_code = leader.code
            board.leader_stock_name = leader.name

            ranked = _merge_ranked_stocks(candidates, amount_limit=8, change_limit=5)
            for stock in ranked:
                key = (stock.board_code, stock.code)
                if key in seen:
                    continue
                stocks.append(stock)
                seen.add(key)
        return [stock for stock in stocks if stock.code and stock.name]


def get_provider(settings: Settings) -> MarketDataProvider:
    provider = settings.data_provider.lower()
    if provider == "sample":
        return SampleMarketDataProvider()
    if provider in {"auto", "akshare"}:
        return AkshareMarketDataProvider()
    raise ValueError(f"Unsupported DATA_PROVIDER: {settings.data_provider}")


def _stock_quotes_from_sector_detail(df: pd.DataFrame, board: BoardQuote, now: datetime) -> list[StockQuote]:
    stocks: list[StockQuote] = []
    for _, row in df.iterrows():
        code = _normalize_code(str(_value(row, ["code", "代码", "symbol"], "")))
        name = str(_value(row, ["name", "名称"], ""))
        if not code or not name:
            continue
        amount = _num(row, ["amount", "成交额"])
        stocks.append(
            StockQuote(
                code=code,
                name=name,
                board_code=board.code,
                board_name=board.name,
                price=_num(row, ["trade", "最新价", "price"]),
                change_percent=_num(row, ["changepercent", "涨跌幅"]),
                volume=_num(row, ["volume", "成交量"]),
                amount=amount,
                capital_flow=amount,
                updated_at=now,
            )
        )
    return stocks


def _merge_ranked_stocks(stocks: list[StockQuote], amount_limit: int, change_limit: int) -> list[StockQuote]:
    ranked: list[StockQuote] = []
    seen: set[str] = set()
    groups = [
        sorted(stocks, key=lambda stock: stock.amount, reverse=True)[:amount_limit],
        sorted(stocks, key=lambda stock: stock.change_percent, reverse=True)[:change_limit],
    ]
    for group in groups:
        for stock in group:
            if stock.code in seen:
                continue
            ranked.append(stock)
            seen.add(stock.code)
    return ranked


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


def _find_first(*rows):
    for row in rows:
        if row is not None:
            return row
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


def _normalize_code(value: str) -> str:
    code = value.strip()
    if code.startswith(("sh", "sz", "bj")) and len(code) > 2:
        return code[2:]
    return code
