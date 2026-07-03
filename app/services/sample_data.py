from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.models import BoardQuote, IndexQuote, MarketSnapshot, StockQuote, TradingStatus

CN_TZ = ZoneInfo("Asia/Shanghai")


BOARD_NAMES = [
    ("BK0475", "半导体设备"),
    ("BK0428", "证券"),
    ("BK1034", "人工智能"),
    ("BK0737", "新能源车"),
    ("BK0481", "白酒"),
    ("BK0456", "银行"),
    ("BK1027", "机器人"),
    ("BK0958", "算力租赁"),
    ("BK0611", "医药商业"),
    ("BK0538", "有色金属"),
    ("BK0899", "低空经济"),
    ("BK0634", "光伏设备"),
]

STOCK_POOL = {
    "BK0475": [("002371", "北方华创"), ("688012", "中微公司"), ("688072", "拓荆科技")],
    "BK0428": [("600030", "中信证券"), ("600837", "海通证券"), ("601688", "华泰证券")],
    "BK1034": [("688256", "寒武纪"), ("603019", "中科曙光"), ("002230", "科大讯飞")],
    "BK0737": [("002594", "比亚迪"), ("300750", "宁德时代"), ("601633", "长城汽车")],
    "BK0481": [("600519", "贵州茅台"), ("000858", "五粮液"), ("000568", "泸州老窖")],
    "BK0456": [("601398", "工商银行"), ("601939", "建设银行"), ("600036", "招商银行")],
    "BK1027": [("300124", "汇川技术"), ("002747", "埃斯顿"), ("688017", "绿的谐波")],
    "BK0958": [("603019", "中科曙光"), ("000977", "浪潮信息"), ("300308", "中际旭创")],
    "BK0611": [("600998", "九州通"), ("000028", "国药一致"), ("603939", "益丰药房")],
    "BK0538": [("601899", "紫金矿业"), ("603799", "华友钴业"), ("600111", "北方稀土")],
    "BK0899": [("002085", "万丰奥威"), ("600316", "洪都航空"), ("002097", "山河智能")],
    "BK0634": [("601012", "隆基绿能"), ("688599", "天合光能"), ("300274", "阳光电源")],
}


def build_sample_snapshot(trading_status: TradingStatus) -> MarketSnapshot:
    now = datetime.now(CN_TZ)
    stocks: list[StockQuote] = []
    boards: list[BoardQuote] = []

    for board_index, (board_code, board_name) in enumerate(BOARD_NAMES, start=1):
        stock_quotes: list[StockQuote] = []
        for stock_index, (stock_code, stock_name) in enumerate(STOCK_POOL[board_code], start=1):
            seed = board_index * 13 + stock_index * 7
            amount = 850_000_000 + seed * 42_000_000
            volume = 3_500_000 + seed * 210_000
            change_percent = round(((seed % 17) - 5) * 0.48, 2)
            capital_flow = amount * (0.06 + (seed % 9) * 0.012)
            stock_quotes.append(
                StockQuote(
                    code=stock_code,
                    name=stock_name,
                    board_code=board_code,
                    board_name=board_name,
                    price=round(8 + seed * 1.73, 2),
                    change_percent=change_percent,
                    volume=float(volume),
                    amount=float(amount),
                    capital_flow=round(capital_flow, 2),
                    updated_at=now,
                )
            )

        leader = max(
            stock_quotes,
            key=lambda item: item.amount * 0.4 + item.capital_flow * 0.3 + item.change_percent * 1_000_000 * 0.2 + item.volume * 0.1,
        )
        stocks.extend(stock_quotes)
        boards.append(
            BoardQuote(
                code=board_code,
                name=board_name,
                change_percent=round(sum(s.change_percent for s in stock_quotes) / len(stock_quotes), 2),
                volume=sum(s.volume for s in stock_quotes),
                amount=sum(s.amount for s in stock_quotes),
                capital_flow=sum(s.capital_flow for s in stock_quotes),
                leader_stock_code=leader.code,
                leader_stock_name=leader.name,
                updated_at=now,
            )
        )

    return MarketSnapshot(
        index=IndexQuote(
            name="上证指数",
            code="000001",
            current=3128.42,
            change=18.36,
            change_percent=0.59,
            volume=327_500_000,
            amount=412_600_000_000,
            updated_at=now,
            trading_status=trading_status,
        ),
        boards=boards,
        stocks=stocks,
        trading_status=trading_status,
    )
