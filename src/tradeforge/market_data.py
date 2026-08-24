"""Official market-data boundary for PAPER execution."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Callable, Mapping, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .domain import Instrument, Quote


class MarketDataError(RuntimeError):
    """Market data cannot be trusted for a new decision."""


class MarketDataProvider(Protocol):
    is_live: bool

    def fetch_quotes(self, instruments: Mapping[str, Instrument]) -> dict[str, Quote]: ...


class AlpacaMarketDataProvider:
    """Official Alpaca latest-quote REST adapter.

    This adapter only reads market data. It cannot submit, cancel, fund, or
    withdraw orders. The IEX feed is the default documented live feed; a
    different feed requires the owner to configure and license it explicitly.
    """

    is_live = True

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        base_url: str = "https://data.alpaca.markets",
        feed: str = "iex",
        timeout_seconds: float = 3.0,
        request_opener: Callable[..., object] = urlopen,
    ) -> None:
        self.api_key = api_key or os.getenv("ALPACA_API_KEY_ID", "")
        self.api_secret = api_secret or os.getenv("ALPACA_API_SECRET_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.feed = feed
        self.timeout_seconds = timeout_seconds
        self._request_opener = request_opener
    def fetch_quotes(self, instruments: Mapping[str, Instrument]) -> dict[str, Quote]:
        if not self.api_key or not self.api_secret:
            raise MarketDataError("official live market data requires ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY")
        symbols = ",".join(instrument.ticker for instrument in instruments.values())
        query = urlencode({"symbols": symbols, "feed": self.feed})
        request = Request(
            f"{self.base_url}/v2/stocks/quotes/latest?{query}",
            headers={
                "APCA-API-KEY-ID": self.api_key,
                "APCA-API-SECRET-KEY": self.api_secret,
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            response = self._request_opener(request, timeout=self.timeout_seconds)
            payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise MarketDataError(f"official market data request failed: {type(exc).__name__}") from exc
        return self.parse_latest_quotes(payload, instruments, self.feed)

    @staticmethod
    def parse_latest_quotes(
        payload: Mapping[str, object],
        instruments: Mapping[str, Instrument],
        feed: str,
    ) -> dict[str, Quote]:
        raw_quotes = payload.get("quotes")
        if not isinstance(raw_quotes, Mapping):
            raise MarketDataError("official market data response did not contain quotes")
        by_ticker = {instrument.ticker: instrument_id for instrument_id, instrument in instruments.items()}
        parsed: dict[str, Quote] = {}
        for ticker, raw in raw_quotes.items():
            instrument_id = by_ticker.get(str(ticker))
            if instrument_id is None or not isinstance(raw, Mapping):
                continue
            try:
                bid = str(raw["bp"])
                ask = str(raw["ap"])
                timestamp = str(raw["t"]).replace("Z", "+00:00")
                quote = Quote(
                    instrument_id=instrument_id,
                    bid=Decimal(bid),
                    ask=Decimal(ask),
                    timestamp=datetime.fromisoformat(timestamp).astimezone(UTC),
                    source=f"alpaca-{feed}",
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise MarketDataError(f"invalid official quote for {ticker}") from exc
            parsed[instrument_id] = quote
        missing = set(instruments) - set(parsed)
        if missing:
            raise MarketDataError(f"official market data missing symbols: {', '.join(sorted(missing))}")
        return parsed
