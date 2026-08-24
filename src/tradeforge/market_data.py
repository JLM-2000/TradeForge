"""Official market-data boundary for PAPER execution."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Callable, Mapping, Protocol
from urllib.parse import urlencode
from urllib.error import HTTPError
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
        self.api_key = api_key if api_key is not None else os.getenv("ALPACA_API_KEY_ID", "")
        self.api_secret = api_secret if api_secret is not None else os.getenv("ALPACA_API_SECRET_KEY", "")
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
        except HTTPError as exc:
            raise MarketDataError(f"official market data request failed: HTTP {exc.code}") from exc
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


class PolygonMarketDataProvider:
    """Official Polygon/Massive latest-NBBO REST adapter.

    It is market-data-only. PaperBroker remains the only executable order
    implementation in TradeForge. The adapter polls the latest bid/ask so the
    existing five-second safety loop can apply freshness checks.
    """

    is_live = True

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 3.0,
        request_opener: Callable[..., object] = urlopen,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY", "")
        self.base_url = (base_url or os.getenv("MASSIVE_API_BASE_URL", "https://api.massive.com")).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._request_opener = request_opener

    def fetch_quotes(self, instruments: Mapping[str, Instrument]) -> dict[str, Quote]:
        if not self.api_key:
            raise MarketDataError("official live market data requires POLYGON_API_KEY")
        result: dict[str, Quote] = {}
        for instrument_id, instrument in instruments.items():
            query = urlencode({"apiKey": self.api_key})
            request = Request(
                f"{self.base_url}/v2/last/nbbo/{instrument.ticker}?{query}",
                headers={"Accept": "application/json"},
                method="GET",
            )
            try:
                response = self._request_opener(request, timeout=self.timeout_seconds)
                payload = json.loads(response.read().decode("utf-8"))
                result[instrument_id] = self.parse_last_quote(payload, instrument, "polygon-nbbo")
            except HTTPError as exc:
                if exc.code == 403:
                    raise MarketDataError(
                        f"Massive denied real-time NBBO for {instrument.ticker}: HTTP 403; "
                        "the account plan or market-data permission does not include this feed"
                    ) from exc
                raise MarketDataError(f"official Polygon quote request failed for {instrument.ticker}: HTTP {exc.code}") from exc
            except MarketDataError:
                raise
            except Exception as exc:
                raise MarketDataError(f"official Polygon quote request failed for {instrument.ticker}: {type(exc).__name__}") from exc
        return result

    @staticmethod
    def parse_last_quote(payload: Mapping[str, object], instrument: Instrument, source: str) -> Quote:
        raw = payload.get("results")
        if not isinstance(raw, Mapping):
            raise MarketDataError(f"official quote response missing results for {instrument.ticker}")
        try:
            timestamp_ns = int(str(raw["t"]))
            timestamp = datetime.fromtimestamp(timestamp_ns // 1_000_000_000, UTC).replace(
                microsecond=(timestamp_ns % 1_000_000_000) // 1_000
            )
            return Quote(
                instrument_id=instrument.instrument_id,
                bid=Decimal(str(raw["p"])),
                ask=Decimal(str(raw["P"])),
                timestamp=timestamp,
                source=source,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MarketDataError(f"invalid official quote for {instrument.ticker}") from exc
