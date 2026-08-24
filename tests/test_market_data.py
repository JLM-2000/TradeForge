import unittest
from decimal import Decimal

from tradeforge.domain import AssetClass, Instrument
from tradeforge.market_data import AlpacaMarketDataProvider, MarketDataError, PolygonMarketDataProvider


class MarketDataAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.instrument = Instrument(
            instrument_id="AAPL",
            isin="US0378331005",
            ticker="AAPL",
            venue="XNAS",
            asset_class=AssetClass.STOCK,
        )

    def test_parses_official_latest_quote_shape_without_float_math(self) -> None:
        payload = {
            "quotes": {
                "AAPL": {
                    "bp": 199.91,
                    "ap": 200.01,
                    "t": "2026-08-24T20:00:00.000000000Z",
                }
            }
        }
        quotes = AlpacaMarketDataProvider.parse_latest_quotes(payload, {"AAPL": self.instrument}, "iex")
        self.assertEqual(quotes["AAPL"].bid, Decimal("199.91"))
        self.assertEqual(quotes["AAPL"].ask, Decimal("200.01"))
        self.assertEqual(quotes["AAPL"].source, "alpaca-iex")

    def test_missing_symbol_fails_closed(self) -> None:
        with self.assertRaises(MarketDataError):
            AlpacaMarketDataProvider.parse_latest_quotes({"quotes": {}}, {"AAPL": self.instrument}, "iex")

    def test_live_provider_requires_credentials(self) -> None:
        provider = AlpacaMarketDataProvider(api_key="", api_secret="")
        with self.assertRaises(MarketDataError):
            provider.fetch_quotes({"AAPL": self.instrument})

    def test_parses_official_polygon_nbbo_shape(self) -> None:
        payload = {
            "results": {
                "p": "199.91",
                "P": "200.01",
                "t": 1787601600000000000,
            }
        }
        quote = PolygonMarketDataProvider.parse_last_quote(payload, self.instrument, "polygon-nbbo")
        self.assertEqual(quote.bid, Decimal("199.91"))
        self.assertEqual(quote.ask, Decimal("200.01"))

    def test_polygon_provider_requires_credentials_on_fetch(self) -> None:
        provider = PolygonMarketDataProvider(api_key="")
        with self.assertRaises(MarketDataError):
            provider.fetch_quotes({"AAPL": self.instrument})


if __name__ == "__main__":
    unittest.main()
