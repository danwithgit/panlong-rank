import pandas as pd

from app.models import TradingStatus
from app.services.provider import AkshareMarketDataProvider


class FakeAkshare:
    def stock_zh_index_spot_em(self):
        raise RuntimeError("eastmoney index unavailable")

    def stock_board_industry_name_em(self):
        raise RuntimeError("eastmoney boards unavailable")

    def stock_board_industry_cons_em(self, symbol):
        raise RuntimeError("eastmoney stocks unavailable")

    def stock_zh_index_spot_sina(self):
        return pd.DataFrame(
            [
                {
                    "代码": "sh000001",
                    "名称": "上证指数",
                    "最新价": 4043.64,
                    "涨跌额": 14.74,
                    "涨跌幅": 0.366,
                    "成交量": 602009738,
                    "成交额": 1465563104854,
                }
            ]
        )

    def stock_sector_spot(self):
        return pd.DataFrame(
            [
                {
                    "label": "new_cbzz",
                    "板块": "船舶制造",
                    "涨跌幅": 5.86,
                    "总成交量": 399973253,
                    "总成交额": 8614537882,
                    "股票代码": "sh600150",
                    "股票名称": "中国船舶",
                }
            ]
        )

    def stock_sector_detail(self, sector):
        assert sector == "new_cbzz"
        return pd.DataFrame(
            [
                {
                    "code": "600150",
                    "name": "中国船舶",
                    "trade": 37.15,
                    "changepercent": 8.12,
                    "volume": 188151453,
                    "amount": 6836128407,
                }
            ]
        )

    def stock_zh_a_spot(self):
        raise AssertionError("Sina full A-share spot is too slow for overseas production collection")


def test_akshare_provider_falls_back_to_sina_sources():
    status = TradingStatus(
        is_trade_day=True,
        trade_date="2026-07-03",
        last_trade_date="2026-07-03",
        session="closed",
    )

    snapshot = AkshareMarketDataProvider()._snapshot_once(status, ak=FakeAkshare())

    assert snapshot.index.current == 4043.64
    assert snapshot.index.code == "000001"
    assert snapshot.boards[0].code == "new_cbzz"
    assert snapshot.boards[0].leader_stock_code == "600150"
    assert snapshot.boards[0].leader_stock_name == "中国船舶"
    assert snapshot.stocks[0].name == "中国船舶"
    assert snapshot.stocks[0].board_code == "new_cbzz"
    assert snapshot.data_source == "akshare_sina"


class FakeAkshareWithWrongSinaLeader(FakeAkshare):
    def stock_sector_spot(self):
        return pd.DataFrame(
            [
                {
                    "label": "new_jdly",
                    "板块": "酒店旅游",
                    "涨跌幅": -2.9,
                    "总成交量": 499816999,
                    "总成交额": 9328295682,
                    "股票代码": "sz002558",
                    "股票名称": "巨人网络",
                }
            ]
        )

    def stock_sector_detail(self, sector):
        assert sector == "new_jdly"
        return pd.DataFrame(
            [
                {
                    "code": "600258",
                    "name": "首旅酒店",
                    "trade": 11.61,
                    "changepercent": -2.025,
                    "volume": 13289860,
                    "amount": 154280498,
                },
                {
                    "code": "600358",
                    "name": "国旅联合",
                    "trade": 5.42,
                    "changepercent": 0.931,
                    "volume": 6050310,
                    "amount": 32952161,
                },
            ]
        )

    def stock_zh_a_spot(self):
        raise AssertionError("Sina full A-share spot should not be used")


def test_akshare_provider_derives_sina_leader_from_sector_detail_not_sector_spot():
    status = TradingStatus(
        is_trade_day=True,
        trade_date="2026-07-03",
        last_trade_date="2026-07-03",
        session="closed",
    )

    snapshot = AkshareMarketDataProvider()._snapshot_once(status, ak=FakeAkshareWithWrongSinaLeader())

    assert snapshot.boards[0].code == "new_jdly"
    assert snapshot.boards[0].leader_stock_code == "600358"
    assert snapshot.boards[0].leader_stock_name == "国旅联合"
    assert {stock.code for stock in snapshot.stocks} == {"600258", "600358"}
    assert all(stock.board_code == "new_jdly" for stock in snapshot.stocks)


class FakeAkshareWithManySinaBoards(FakeAkshare):
    def __init__(self):
        self.detail_calls: list[str] = []

    def stock_sector_spot(self):
        return pd.DataFrame(
            [
                {
                    "label": "new_low",
                    "板块": "低成交板块",
                    "涨跌幅": 1,
                    "总成交量": 100,
                    "总成交额": 1000,
                },
                {
                    "label": "new_high",
                    "板块": "高成交板块",
                    "涨跌幅": 2,
                    "总成交量": 200,
                    "总成交额": 9999,
                },
            ]
        )

    def stock_sector_detail(self, sector):
        self.detail_calls.append(sector)
        return pd.DataFrame(
            [
                {
                    "code": "600001",
                    "name": "核心股票",
                    "trade": 10,
                    "changepercent": 3,
                    "volume": 1000,
                    "amount": 2000,
                }
            ]
        )


def test_akshare_provider_limits_sina_detail_to_high_turnover_boards():
    status = TradingStatus(
        is_trade_day=True,
        trade_date="2026-07-03",
        last_trade_date="2026-07-03",
        session="closed",
    )
    ak = FakeAkshareWithManySinaBoards()

    snapshot = AkshareMarketDataProvider(sina_detail_board_limit=1)._snapshot_once(status, ak=ak)

    assert ak.detail_calls == ["new_high"]
    assert len(snapshot.boards) == 2
    assert snapshot.boards[0].leader_stock_code is None
    assert snapshot.boards[1].leader_stock_code == "600001"
    assert snapshot.stocks[0].board_code == "new_high"


class FakeAkshareWithSinaIndexAndEmBoards(FakeAkshare):
    def stock_sector_spot(self):
        raise RuntimeError("sina boards unavailable")

    def stock_board_industry_name_em(self):
        return pd.DataFrame(
            [
                {
                    "板块代码": "BK1412",
                    "板块名称": "氨纶",
                    "涨跌幅": 6.7,
                    "成交量": 100000,
                    "成交额": 900000000,
                    "领涨股票": "华峰化学",
                }
            ]
        )

    def stock_board_industry_cons_em(self, symbol):
        assert symbol == "氨纶"
        return pd.DataFrame(
            [
                {
                    "代码": "002064",
                    "名称": "华峰化学",
                    "最新价": 11.16,
                    "涨跌幅": 6.794,
                    "成交量": 900000,
                    "成交额": 825615210,
                }
            ]
        )

    def stock_sector_detail(self, sector):
        raise AssertionError("Sina sector detail does not accept Eastmoney BK board codes")


def test_akshare_provider_uses_em_stock_detail_for_em_boards_even_when_index_falls_back_to_sina():
    status = TradingStatus(
        is_trade_day=True,
        trade_date="2026-07-03",
        last_trade_date="2026-07-03",
        session="closed",
    )

    snapshot = AkshareMarketDataProvider()._snapshot_once(status, ak=FakeAkshareWithSinaIndexAndEmBoards())

    assert snapshot.index.current == 4043.64
    assert snapshot.boards[0].code == "BK1412"
    assert snapshot.stocks[0].code == "002064"
    assert snapshot.stocks[0].board_code == "BK1412"
    assert snapshot.data_source == "akshare_sina+akshare_em"


class FakeAkshareWithEmBoardsMissingTurnover(FakeAkshare):
    def stock_zh_index_spot_em(self):
        return pd.DataFrame(
            [
                {
                    "代码": "000001",
                    "名称": "上证指数",
                    "最新价": 4035.96,
                    "昨日收盘": 4043.64,
                    "涨跌幅": -0.19,
                    "成交量": 384808336,
                    "成交额": 956462007671.5,
                }
            ]
        )

    def stock_board_industry_name_em(self):
        return pd.DataFrame(
            [
                {
                    "板块代码": "BK0465",
                    "板块名称": "化学制药",
                    "涨跌幅": 1.6,
                    "总市值": 100000000,
                    "领涨股票": "罗欣药业",
                }
            ]
        )


def test_akshare_provider_prefers_board_source_with_turnover_fields():
    status = TradingStatus(
        is_trade_day=True,
        trade_date="2026-07-03",
        last_trade_date="2026-07-03",
        session="closed",
    )

    snapshot = AkshareMarketDataProvider()._snapshot_once(status, ak=FakeAkshareWithEmBoardsMissingTurnover())

    assert snapshot.boards[0].code == "new_cbzz"
    assert snapshot.boards[0].amount == 8614537882
    assert snapshot.boards[0].volume == 399973253
    assert snapshot.data_source == "akshare_em+akshare_sina"
