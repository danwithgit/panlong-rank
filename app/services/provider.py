from __future__ import annotations

from datetime import datetime
import logging
import re
import signal
import threading
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
    def __init__(
        self,
        sina_detail_board_limit: int = 16,
        call_timeout_seconds: float = 5,
        tencent_batch_size: int = 500,
        tencent_batch_delay_seconds: float = 0.2,
        tencent_request_timeout_seconds: int = 15,
        min_realtime_stock_count: int = 4000,
        min_stock_coverage_ratio: float = 0.9,
        http_get=None,
    ) -> None:
        self.sina_detail_board_limit = max(1, sina_detail_board_limit)
        self.call_timeout_seconds = max(0.1, call_timeout_seconds)
        self.tencent_batch_size = max(1, min(500, tencent_batch_size))
        self.tencent_batch_delay_seconds = max(0, tencent_batch_delay_seconds)
        self.tencent_request_timeout_seconds = max(1, tencent_request_timeout_seconds)
        self.min_realtime_stock_count = max(1, min_realtime_stock_count)
        self.min_stock_coverage_ratio = min(1, max(0.1, min_stock_coverage_ratio))
        self.http_get = http_get or requests.get
        self.stock_universe: dict[str, str] = {}
        self.stock_sector_mappings: dict[str, list[tuple[str, str]]] = {}

    def configure_stock_context(
        self,
        stock_universe: dict[str, str],
        stock_sector_mappings: dict[str, list[tuple[str, str]]],
    ) -> None:
        self.stock_universe = stock_universe
        self.stock_sector_mappings = stock_sector_mappings

    def snapshot(self, trading_status: TradingStatus) -> MarketSnapshot:
        return self._snapshot_once(trading_status)

    def _snapshot_once(self, trading_status: TradingStatus, ak=None) -> MarketSnapshot:
        if ak is None:
            import akshare as ak

        source_parts: list[str] = []
        index = self._first_success(
            "index quote",
            [
                ("akshare_sina", lambda: self._index_quote_sina(ak, trading_status)),
                ("akshare_em", lambda: self._index_quote_em(ak, trading_status)),
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
        if self.stock_universe:
            return [
                ("tencent_realtime", lambda: self._stock_quotes_qq(boards)),
                ("akshare_sina", lambda: self._stock_quotes_sina(ak, boards)),
            ]
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
                    capital_flow=_num(row, ["主力净流入", "资金净流入", "净流入"]),
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
                    capital_flow=0,
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
                        capital_flow=_num(row, ["主力净流入", "资金净流入"]),
                        updated_at=now,
                    )
                )
        return [s for s in stocks if s.code and s.name]

    def _stock_quotes_sina(self, ak, boards: list[BoardQuote]) -> list[StockQuote]:
        now = datetime.now(CN_TZ)
        selected_boards = sorted(boards, key=lambda board: board.amount, reverse=True)[: self.sina_detail_board_limit]
        return self._sina_sector_detail_quotes(ak, selected_boards, now)

    def _stock_quotes_qq(self, boards: list[BoardQuote]) -> list[StockQuote]:
        board_names = {board.code: board.name for board in boards}
        raw_quotes: dict[str, StockQuote] = {}
        codes = list(self.stock_universe)
        for batch_index, batch in enumerate(_chunks(codes, self.tencent_batch_size)):
            symbols = [_quote_symbol(code) for code in batch]
            url = "https://qt.gtimg.cn/q=" + ",".join(symbols)
            last_error = None
            for attempt in range(2):
                try:
                    response = self.http_get(
                        url,
                        timeout=self.tencent_request_timeout_seconds,
                        headers={"Referer": "https://gu.qq.com/", "User-Agent": "PanlongRank/1.0"},
                    )
                    response.raise_for_status()
                    text = response.content.decode("gbk", errors="replace")
                    parsed = _parse_qq_quotes(text, datetime.now(CN_TZ))
                    if not parsed:
                        raise RuntimeError("empty Tencent quote batch")
                    raw_quotes.update({item.code: item for item in parsed})
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt == 0:
                        time.sleep(0.5)
            if last_error is not None:
                raise RuntimeError(f"Tencent quote batch {batch_index + 1} failed: {last_error}") from last_error
            if batch_index + 1 < (len(codes) + self.tencent_batch_size - 1) // self.tencent_batch_size:
                time.sleep(self.tencent_batch_delay_seconds)

        expected = len(codes)
        received = len(raw_quotes)
        required = min(expected, self.min_realtime_stock_count)
        if received < required or received / expected < self.min_stock_coverage_ratio:
            raise RuntimeError(f"Tencent stock coverage too low: {received}/{expected}")

        stocks: list[StockQuote] = []
        stocks_by_board: dict[str, list[StockQuote]] = {}
        for code, quote in raw_quotes.items():
            mappings = [
                (sector_code, board_names[sector_code])
                for sector_code, _ in self.stock_sector_mappings.get(code, [])
                if sector_code in board_names
            ]
            if not mappings:
                stocks.append(quote)
                continue
            primary_sector_code, primary_sector_name = mappings[0]
            stocks.append(
                quote.model_copy(update={"board_code": primary_sector_code, "board_name": primary_sector_name})
            )
            for sector_code, sector_name in mappings:
                mapped = quote.model_copy(update={"board_code": sector_code, "board_name": sector_name})
                stocks_by_board.setdefault(sector_code, []).append(mapped)

        for board in boards:
            candidates = stocks_by_board.get(board.code, [])
            if not candidates:
                continue
            leader = max(candidates, key=lambda stock: (stock.change_percent, stock.amount))
            board.leader_stock_code = leader.code
            board.leader_stock_name = leader.name
        return stocks

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
                df = _call_with_timeout(
                    lambda: ak.stock_sector_detail(sector=board.code),
                    timeout_seconds=self.call_timeout_seconds,
                )
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
        return AkshareMarketDataProvider(
            sina_detail_board_limit=settings.sina_detail_board_limit,
            call_timeout_seconds=settings.provider_call_timeout_seconds,
            tencent_batch_size=settings.tencent_batch_size,
            tencent_batch_delay_seconds=settings.tencent_batch_delay_seconds,
            tencent_request_timeout_seconds=settings.tencent_request_timeout_seconds,
            min_realtime_stock_count=settings.min_realtime_stock_count,
            min_stock_coverage_ratio=settings.min_stock_coverage_ratio,
        )
    raise ValueError(f"Unsupported DATA_PROVIDER: {settings.data_provider}")


def _call_with_timeout(loader, timeout_seconds: int):
    if not hasattr(signal, "SIGALRM") or threading.current_thread() is not threading.main_thread():
        return loader()

    def _raise_timeout(signum, frame):
        raise TimeoutError

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    signal.signal(signal.SIGALRM, _raise_timeout)
    try:
        return loader()
    except TimeoutError as exc:
        raise RuntimeError(f"provider call timed out after {timeout_seconds} seconds") from exc
    finally:
        signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])
        signal.signal(signal.SIGALRM, previous_handler)


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
                capital_flow=0,
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


def _parse_qq_quotes(text: str, now: datetime) -> list[StockQuote]:
    quotes: list[StockQuote] = []
    for payload in re.findall(r'v_[^=]+="([^"]*)"', text):
        values = payload.split("~")
        if len(values) < 38:
            continue
        code = _normalize_code(values[2])
        name = values[1].strip()
        if not code or not name:
            continue
        current = _float(values[3]) or _float(values[4])
        amount_parts = values[35].split("/") if len(values) > 35 else []
        amount = _float(amount_parts[2]) if len(amount_parts) >= 3 else _float(values[37]) * 10000
        quotes.append(
            StockQuote(
                code=code,
                name=name,
                board_code="",
                board_name="",
                price=current,
                change_percent=_float(values[32]),
                volume=_float(values[36]) * 100,
                amount=amount,
                capital_flow=0,
                updated_at=now,
            )
        )
    return quotes


def _quote_symbol(stock_code: str) -> str:
    code = stock_code.strip()
    if code.startswith(("600", "601", "603", "605", "688", "689")):
        return f"sh{code}"
    if code.startswith(("000", "001", "002", "003", "300", "301")):
        return f"sz{code}"
    if code.startswith(("4", "8", "9")):
        return f"bj{code}"
    return code


def _float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _chunks(values: list[str], size: int):
    for index in range(0, len(values), size):
        yield values[index : index + size]
