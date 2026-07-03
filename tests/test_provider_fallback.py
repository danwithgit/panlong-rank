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
    assert snapshot.stocks[0].name == "中国船舶"
    assert snapshot.stocks[0].board_code == "new_cbzz"
    assert snapshot.data_source == "akshare_sina"
