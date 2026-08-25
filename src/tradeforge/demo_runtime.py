"""Server-side paper operations runtime used by the TradeForge dashboard.

This is a deterministic simulated environment. It intentionally reuses the
same controls, RiskEngine, ExecutionService, PaperBroker, ledger, and
reconciliation services used by the core tests. It never has a live broker
capability.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from .broker import PaperBroker, SimulationConfig
from .config import Settings
from .controls import ControlCenter, ResumeDenied
from .domain import (
    AssetClass,
    BrokerSnapshot,
    Decision,
    ExecutionMode,
    IntentKind,
    Instrument,
    Origin,
    OwnerHardLimits,
    OrderRequest,
    OrderType,
    Quote,
    RiskConfiguration,
    RiskMode,
    ResumeChecks,
    RiskSnapshot,
    Side,
    SizingPolicy,
    TradeIntent,
    new_id,
    utc_now,
)
from .execution import ExecutionService
from .market_data import AssetCandidate, AlpacaAssetUniverseProvider, AlpacaMarketDataProvider, MarketDataError, PolygonMarketDataProvider
from .persistence import SQLiteStore
from .reconciliation import ReconciliationService
from .risk import RiskEngine


def money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


class DemoRuntime:
    """One-owner, PAPER-only runtime for local and hosted demonstrations."""

    def __init__(
        self,
        db_path: str | Path = "artifacts/tradeforge-demo.db",
        auto_interval_seconds: float = 5.0,
        auto_trade_every_ticks: int = 6,
        market_data_mode: str | None = None,
        auto_min_hold_seconds: float = 300.0,
    ) -> None:
        self._lock = threading.RLock()
        if auto_interval_seconds <= 0:
            raise ValueError("auto_interval_seconds must be positive")
        if auto_trade_every_ticks < 1:
            raise ValueError("auto_trade_every_ticks must be positive")
        if auto_min_hold_seconds < 0:
            raise ValueError("auto_min_hold_seconds cannot be negative")
        self._auto_interval_seconds = auto_interval_seconds
        self._auto_trade_every_ticks = auto_trade_every_ticks
        self._auto_min_hold = timedelta(seconds=auto_min_hold_seconds)
        self._auto_take_profit_pct = Decimal("1.5")
        self._auto_stop_loss_pct = Decimal("2.0")
        self._virtual_capital = Decimal(os.getenv("TRADEFORGE_DEMO_CAPITAL_EUR", "1000"))
        if self._virtual_capital <= Decimal("0"):
            raise ValueError("TRADEFORGE_DEMO_CAPITAL_EUR must be positive")
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.store = SQLiteStore(db_path)
        self.settings = Settings(
            mode=ExecutionMode.PAPER,
            bot_account_id="DEMO-BOT",
            personal_investment_account_ids=frozenset({"MYINVESTOR-LONG-TERM"}),
            allowed_instrument_ids=frozenset({"AAPL", "MSFT", "SAP"}),
        )
        self.instruments = {
            "AAPL": Instrument("AAPL", "US0378331005", "AAPL", "XNAS", quantity_increment=Decimal("0.001")),
            "MSFT": Instrument("MSFT", "US5949181045", "MSFT", "XNAS", quantity_increment=Decimal("0.001")),
            "SAP": Instrument("SAP", "DE0007164600", "SAP", "XETR", quantity_increment=Decimal("0.001")),
        }
        self.quotes = {
            "AAPL": Quote("AAPL", Decimal("102.10"), Decimal("102.15"), utc_now(), "demo-feed"),
            "MSFT": Quote("MSFT", Decimal("417.80"), Decimal("418.00"), utc_now(), "demo-feed"),
            "SAP": Quote("SAP", Decimal("188.20"), Decimal("188.35"), utc_now(), "demo-feed"),
        }
        configured_market_mode = (market_data_mode or os.getenv("TRADEFORGE_MARKET_DATA_MODE", "ALPACA_LIVE")).upper()
        self._market_data_live = configured_market_mode in {"LIVE", "ALPACA", "ALPACA_LIVE"}
        provider_name = os.getenv("TRADEFORGE_MARKET_DATA_PROVIDER", "ALPACA").upper()
        if self._market_data_live and provider_name == "POLYGON":
            self._market_data_provider = PolygonMarketDataProvider()
        elif self._market_data_live:
            self._market_data_provider = AlpacaMarketDataProvider(feed=os.getenv("TRADEFORGE_ALPACA_FEED", "iex"))
        else:
            self._market_data_provider = None
        self._market_data_provider_name = provider_name if self._market_data_live else "SYNTHETIC"
        self._max_live_spread_bps = Decimal("100")
        self._unavailable_symbols: set[str] = set()
        self._asset_catalog: tuple[AssetCandidate, ...] = ()
        self._universe_error: str | None = None
        if self._market_data_live and provider_name == "ALPACA":
            try:
                self._asset_catalog = AlpacaAssetUniverseProvider().fetch_assets()
            except MarketDataError as exc:
                self._universe_error = str(exc)
        self._live_quote_max_age = timedelta(seconds=30)
        self._live_data_ready = not self._market_data_live
        self._live_data_error: str | None = None
        if self._market_data_provider is not None:
            try:
                self._accept_live_quotes(self._market_data_provider.fetch_quotes(self.instruments))
                self._live_data_ready = True
                if not self._quotes_fresh():
                    self._live_data_ready = False
                    self._live_data_error = "live quotes are stale; market may be closed"
            except MarketDataError as exc:
                self._live_data_error = str(exc)
        self.owner_limits = OwnerHardLimits(
            version="demo-owner-limits-v1",
            max_total_capital_eur=self._virtual_capital,
            max_position_eur=Decimal("300"),
            max_total_exposure_eur=Decimal("900"),
            max_open_positions=3,
            max_daily_loss_eur=Decimal("25"),
            max_daily_profit_eur=Decimal("50"),
            max_weekly_loss_eur=Decimal("75"),
            max_weekly_profit_eur=None,
            max_monthly_loss_eur=Decimal("150"),
            max_monthly_profit_eur=None,
            max_drawdown_percent=Decimal("10"),
            max_orders_per_day=50,
        )
        self.controls = ControlCenter(self.store, self.settings)
        self.risk_configuration = RiskConfiguration(
            mode=RiskMode.AUTO,
            auto_min_position_eur=Decimal("1"),
        )
        self.risk = RiskEngine(
            self.settings,
            self.owner_limits,
            self.risk_configuration,
            self.instruments,
            self.controls,
            max_quote_age=self._live_quote_max_age if self._market_data_live else timedelta(seconds=5),
        )
        self.broker = PaperBroker(
            self.settings.bot_account_id,
            self._virtual_capital,
            self.instruments,
            self.quotes,
            SimulationConfig(slippage_bps=Decimal("2"), commission_bps=Decimal("8"), fixed_fee=Decimal("0.05")),
        )
        self.execution = ExecutionService(self.risk, self.broker, self.controls, self.store)
        self.reconciliation = ReconciliationService(self.settings, self.controls, self.store)
        self._flags: dict[str, bool] = {
            "broker_healthy": True,
            "market_data_healthy": self._live_data_ready,
            "reconciliation_ok": True,
            "stale_prices": False,
        }
        self._realized_pnl = Decimal("0")
        self._realized_today = Decimal("0")
        self._realized_week = Decimal("0")
        self._realized_month = Decimal("0")
        self._deposits = self._virtual_capital
        self._withdrawals = Decimal("0")
        self._notifications: list[dict[str, Any]] = []
        self._idempotency_keys: set[str] = set()
        self._equity_history = self._seed_equity_history()
        self._auto_running = False
        self._auto_stop = threading.Event()
        self._auto_thread: threading.Thread | None = None
        self._auto_tick = 0
        self._auto_last_action: str | None = None
        self._session_closed = False
        self._orders_today = 0
        self._auto_session_id = new_id("auto-session")
        self._auto_opened_at: dict[str, datetime] = {}
        self._auto_last_trade_at: dict[str, datetime] = {}
        self._price_history: dict[str, list[Decimal]] = {instrument_id: [] for instrument_id in self.instruments}
        self._auto_session_start_equity: Decimal | None = None
        self._seed_if_needed()

    def close(self) -> None:
        self._stop_auto_worker()
        self.store.close()

    def dashboard(self) -> dict[str, Any]:
        with self._lock:
            equity, invested, unrealized, positions = self._portfolio_values()
            control = self.controls.record
            kill_active = control.state.value == "KILL_SWITCH_ACTIVE"
            status = "CRITICAL" if kill_active else "PAUSED" if control.state.value == "PAUSED" else "HEALTHY"
            return {
                "product": "TradeForge",
                "mode": "PAPER",
                "modeLabel": "PAPER - LIVE MARKET DATA" if self._market_data_live else "PAPER - SYNTHETIC MARKET DATA",
                "marketDataMode": "LIVE" if self._market_data_live else "SYNTHETIC",
                "marketDataProvider": self._market_data_provider_name,
                "demo": True,
                "liveExecution": False,
                "system": {
                    "status": status,
                    "bot": "STOPPED" if kill_active else "PAUSED" if control.state.value == "PAUSED" else "RUNNING",
                    "broker": "HEALTHY" if self._flags["broker_healthy"] else "UNAVAILABLE",
                    "market": "LIVE" if self._market_data_live and self._flags["market_data_healthy"] else "STALE" if self._flags["stale_prices"] else "HEALTHY" if self._flags["market_data_healthy"] else "UNAVAILABLE",
                    "risk": "PAUSED" if control.state.value != "RUNNING" else "HEALTHY",
                    "reconciliation": "OK" if self._flags["reconciliation_ok"] else "MISMATCH",
                    "lastUpdate": iso(utc_now()),
                    "marketDataError": self._live_data_error,
                },
                "control": {
                    "state": control.state.value,
                    "reason": control.reason,
                    "killSwitch": kill_active,
                    "activatedAt": iso(control.activated_at),
                    "cancelPendingOnPause": control.cancel_pending_on_pause,
                },
                "automation": {
                    "running": self._auto_running,
                    "strategy": "Demo Trend v1",
                    "intervalSeconds": self._auto_interval_seconds,
                    "tradeEverySeconds": self._auto_interval_seconds * self._auto_trade_every_ticks,
                    "minHoldSeconds": self._auto_min_hold.total_seconds(),
                    "takeProfitPct": str(self._auto_take_profit_pct),
                    "stopLossPct": str(self._auto_stop_loss_pct),
                    "lastAction": self._auto_last_action,
                    "tick": self._auto_tick,
                    "sessionClosed": self._session_closed,
                    "sessionStartEquity": money(self._auto_session_start_equity) if self._auto_session_start_equity is not None else None,
                },
                "universe": {
                    "watchlist": sorted(self.instruments),
                    "catalogAvailable": bool(self._asset_catalog),
                    "candidateCount": len(self._asset_catalog),
                    "error": self._universe_error,
                    "unavailableSymbols": sorted(self._unavailable_symbols),
                },
                "metrics": {
                    "totalEquity": money(equity),
                    "availableCash": money(self.broker.snapshot().cash),
                    "investedCapital": money(invested),
                    "withdrawableCash": money(self.broker.snapshot().withdrawable_cash),
                    "totalDeposits": money(self._deposits),
                    "totalWithdrawals": money(self._withdrawals),
                    "realizedPnl": money(self._realized_pnl),
                    "unrealizedPnl": money(unrealized),
                    "totalPnl": money(self._realized_pnl + unrealized),
                    "todayPnl": money(self._realized_today),
                    "weekPnl": money(self._realized_week),
                    "monthPnl": money(self._realized_month),
                    "yearPnl": money(self._realized_pnl),
                    "allTimePnl": money(self._realized_pnl),
                    "totalReturnPct": f"{(self._realized_pnl + unrealized) / self._deposits * Decimal('100'):.2f}%" if self._deposits else "0.00%",
                    "todayReturnPct": f"{self._realized_today / self._deposits * Decimal('100'):.2f}%" if self._deposits else "0.00%",
                    "autoSessionPnl": money(equity - self._auto_session_start_equity) if self._auto_session_start_equity is not None else "0.00",
                    "autoSessionReturnPct": f"{(equity - self._auto_session_start_equity) / self._auto_session_start_equity * Decimal('100'):.2f}%" if self._auto_session_start_equity else "0.00%",
                    "currentDrawdown": "2.8%",
                    "maxDrawdown": "6.4%",
                    "currentExposure": money(invested),
                    "positions": len(positions),
                    "openOrders": len(self._open_orders()),
                    "fees": money(sum((execution.fees for execution in self.broker.executions()), Decimal("0"))),
                    "winRate": "64.3%",
                    "profitFactor": "1.84",
                },
                "risk": self._risk_view(),
                "charts": self._chart_data(equity, unrealized),
                "positions": [self._position_view(position) for position in positions],
                "orders": [self._order_view(order) for order in reversed(self.broker.orders())],
                "notifications": list(reversed(self._notifications[-8:])),
                "unreadNotifications": sum(1 for item in self._notifications if not item["read"]),
                "audit": self._audit_view(),
                "health": self._health_view(),
                "scenarios": [
                    {"id": "profit-target", "label": "Simulate profit target"},
                    {"id": "daily-loss", "label": "Simulate daily loss"},
                    {"id": "drawdown", "label": "Simulate drawdown"},
                    {"id": "broker-disconnect", "label": "Simulate broker disconnect"},
                    {"id": "market-data-failure", "label": "Simulate market data failure"},
                    {"id": "stale-price", "label": "Simulate stale price"},
                    {"id": "partial-fill", "label": "Simulate partial fill"},
                    {"id": "duplicate-order", "label": "Simulate duplicate order"},
                    {"id": "reconciliation-failure", "label": "Simulate reconciliation failure"},
                    {"id": "manual-trade", "label": "Simulate manual trade"},
                    {"id": "manual-withdrawal", "label": "Simulate manual withdrawal"},
                    {"id": "tax-warning", "label": "Simulate tax warning"},
                    {"id": "kill-switch", "label": "Simulate kill switch"},
                ],
            }

    def search_universe(self, query: str) -> dict[str, Any]:
        with self._lock:
            normalized = query.strip().lower()
            candidates = self._asset_catalog or tuple(
                AssetCandidate(
                    symbol=instrument.ticker,
                    name=instrument.ticker,
                    exchange=instrument.venue,
                    asset_class=instrument.asset_class.value,
                    tradable=instrument.tradable,
                    fractionable=instrument.quantity_increment < Decimal("1"),
                )
                for instrument in self.instruments.values()
            )
            matches = [
                candidate
                for candidate in candidates
                if not normalized or normalized in candidate.symbol.lower() or normalized in candidate.name.lower()
            ][:25]
            return {
                "query": query,
                "liveData": self._market_data_live,
                "matches": [
                    {
                        "symbol": candidate.symbol,
                        "name": candidate.name,
                        "exchange": candidate.exchange,
                        "assetClass": candidate.asset_class,
                        "fractionable": candidate.fractionable,
                        "watchlisted": candidate.symbol in self.instruments,
                    }
                    for candidate in matches
                ],
                "error": self._universe_error,
            }

    def add_to_watchlist(self, symbol: str) -> dict[str, Any]:
        with self._lock:
            symbol = symbol.strip().upper()
            candidate = next((item for item in self._asset_catalog if item.symbol == symbol), None)
            if candidate is None:
                raise ValueError("symbol is not an active official asset candidate")
            if not candidate.tradable:
                raise ValueError("asset is not tradable")
            if symbol not in self.instruments:
                instrument = Instrument(
                    instrument_id=symbol,
                    isin=None,
                    ticker=symbol,
                    venue=candidate.exchange or "UNKNOWN",
                    asset_class=AssetClass.ETF if candidate.asset_class == "us_etf" else AssetClass.STOCK,
                    quantity_increment=Decimal("0.001") if candidate.fractionable else Decimal("1"),
                )
                if self._market_data_provider is None:
                    raise ValueError("a live market-data provider is required to add a watchlist asset")
                self.quotes.update(self._market_data_provider.fetch_quotes({symbol: instrument}))
                self.instruments[symbol] = instrument
                self.settings = replace(self.settings, allowed_instrument_ids=frozenset((*self.settings.allowed_instrument_ids, symbol)))
                self.controls.settings = self.settings
                self.risk.settings = self.settings
                self._price_history[symbol] = []
                self._event("WATCHLIST_ASSET_ADDED", {"symbol": symbol, "exchange": candidate.exchange})
            return self.dashboard()

    def pause(self, reason: str = "Operator paused automated entries") -> dict[str, Any]:
        with self._lock:
            self._stop_auto_worker()
            self.controls.pause(reason)
            self._notify("warning", "Trading paused", reason)
            return self.dashboard()

    def resume(self) -> dict[str, Any]:
        with self._lock:
            checks = self._resume_checks()
            try:
                self.controls.resume(checks)
            except ResumeDenied as exc:
                self._notify("critical", "Resume denied", ", ".join(exc.failures))
                raise
            self._notify("info", "Trading resumed", "All resume checks passed")
            return self.dashboard()

    def stop_everything(self, reason: str = "Operator activated emergency stop") -> dict[str, Any]:
        with self._lock:
            self._stop_auto_worker()
            record = self.controls.stop_everything(reason)
            cancelled = self._cancel_pending_entries()
            self._notify(
                "critical",
                "AUTOMATION STOPPED",
                f"Kill switch active. {cancelled} pending entry order(s) cancelled. Positions were not liquidated.",
            )
            return self.dashboard()

    def start_auto(self) -> dict[str, Any]:
        with self._lock:
            if self._market_data_provider is not None:
                try:
                    self._advance_market()
                    if self._market_data_live and self._live_data_ready and not self.broker.positions():
                        self._seed_if_needed()
                except MarketDataError as exc:
                    self._flags["market_data_healthy"] = False
                    self._live_data_error = str(exc)
                    self._notify("critical", "Automatic trading unavailable", str(exc))
                    raise ResumeDenied(("live_market_data_unavailable",)) from exc
            if self._market_data_live and not self._quotes_fresh():
                self._flags["market_data_healthy"] = False
                self._flags["stale_prices"] = True
                self._live_data_error = "live quotes are stale; market may be closed"
                self._notify("critical", "Automatic trading unavailable", self._live_data_error)
                raise ResumeDenied(("stale_market_data",))
            if self.controls.record.state.value != "RUNNING":
                raise ResumeDenied(("trading_not_running",))
            if self._session_closed:
                raise ResumeDenied(("session_closed",))
            checks = self._resume_checks()
            if not checks.passed:
                raise ResumeDenied(checks.failures())
            if self._auto_running:
                return self.dashboard()
            self._auto_session_start_equity = self._portfolio_values()[0]
            self._auto_stop.clear()
            self._auto_running = True
            self._auto_last_action = "Automatic PAPER trading started"
            self._notify("info", "Automatic paper trading started", "Demo Trend v1 is running inside owner hard limits")
            self._auto_thread = threading.Thread(target=self._auto_loop, name="tradeforge-paper-auto", daemon=True)
            self._auto_thread.start()
            return self.dashboard()

    def pause_auto(self, reason: str = "Owner paused automatic paper trading") -> dict[str, Any]:
        with self._lock:
            self._stop_auto_worker()
            self._auto_last_action = reason
            self._notify("warning", "Automatic paper trading paused", reason)
            return self.dashboard()

    def acknowledge_notifications(self) -> dict[str, Any]:
        with self._lock:
            for notification in self._notifications:
                notification["read"] = True
            return self.dashboard()

    def end_session(self) -> dict[str, Any]:
        """Owner's deliberate end-of-day action: pause and close PAPER positions."""
        with self._lock:
            self._stop_auto_worker()
            if self.controls.record.state.value == "KILL_SWITCH_ACTIVE":
                raise ResumeDenied(("kill_switch_active",))
            self.controls.pause("Owner ended paper trading session")
            closed: list[str] = []
            failures: list[str] = []
            for position in tuple(self.broker.positions()):
                result = self.place_order(
                    position.instrument_id,
                    "SELL",
                    position.market_value,
                    f"session-close-{position.instrument_id}-{new_id('key')}",
                )
                if result["decision"] in {"APPROVE", "RESIZE"} and result["dashboard"]["orders"]:
                    closed.append(position.instrument_id)
                else:
                    failures.extend(result["reasons"])
            self._session_closed = True
            if failures:
                self._notify("critical", "Session close incomplete", ", ".join(dict.fromkeys(failures)))
            else:
                self._notify("info", "Paper session closed", f"Paused and sold {len(closed)} simulated position(s)")
            return self.dashboard()

    def reset_kill_switch(self, owner_confirmed: bool) -> dict[str, Any]:
        with self._lock:
            if not owner_confirmed:
                raise PermissionError("owner confirmation is required")
            self.controls.reset_kill_switch(self._resume_checks(kill_switch_clear=True), True)
            self._notify("warning", "Kill switch reset", "System remains paused until explicit resume")
            return self.dashboard()

    def system_check(self) -> dict[str, Any]:
        with self._lock:
            checks = self._resume_checks(kill_switch_clear=self.controls.record.state.value != "KILL_SWITCH_ACTIVE")
            return {"passed": checks.passed, "failures": list(checks.failures()), "checks": {
                "broker": checks.broker_healthy,
                "marketData": checks.market_data_healthy,
                "cash": checks.cash_known,
                "positions": checks.positions_known,
                "orders": checks.open_orders_known,
                "reconciliation": checks.reconciliation_ok,
                "riskLimits": checks.risk_limits_ok,
                "account": checks.authorized_account,
                "killSwitchClear": checks.kill_switch_clear,
            }}

    def reconcile(self) -> dict[str, Any]:
        with self._lock:
            snapshot = self.broker.snapshot()
            if not self._flags["reconciliation_ok"]:
                broker_snapshot = replace(snapshot, cash=snapshot.cash - Decimal("1"))
            else:
                broker_snapshot = snapshot
            report = self.reconciliation.reconcile(snapshot, broker_snapshot)
            self._flags["reconciliation_ok"] = report.status.value == "MATCHED"
            self._notify(
                "info" if self._flags["reconciliation_ok"] else "critical",
                "Reconciliation completed",
                report.status.value if self._flags["reconciliation_ok"] else ", ".join(report.differences),
            )
            return {"status": report.status.value, "differences": list(report.differences), "dashboard": self.dashboard()}

    def simulate(self, scenario: str) -> dict[str, Any]:
        with self._lock:
            scenario = scenario.lower().replace("_", "-").strip()
            if scenario == "profit-target":
                self._realized_today = self.owner_limits.max_daily_profit_eur or Decimal("20")
                self.controls.pause("Daily profit target reached")
                self._notify("warning", "Profit target reached", "New entries are paused by policy")
            elif scenario == "daily-loss":
                self._realized_today = -self.owner_limits.max_daily_loss_eur - Decimal("0.01")
                self.controls.pause("Daily loss limit reached")
                self._notify("critical", "Daily loss limit reached", "New entries are paused by policy")
            elif scenario == "drawdown":
                self.controls.pause("Drawdown circuit breaker triggered")
                self._notify("critical", "Drawdown circuit breaker", "Trading paused pending review")
            elif scenario == "broker-disconnect":
                self._flags["broker_healthy"] = False
                self.controls.pause("Broker disconnected")
                self._notify("critical", "Broker disconnected", "Execution is unavailable and trading is paused")
            elif scenario == "market-data-failure":
                self._flags["market_data_healthy"] = False
                self.controls.pause("Market data unavailable")
                self._notify("critical", "Market data failure", "Fresh prices are unavailable")
            elif scenario == "stale-price":
                self._flags["stale_prices"] = True
                self.controls.pause("Stale price circuit breaker")
                self._notify("critical", "Stale price detected", "New entries are paused")
            elif scenario == "partial-fill":
                self.broker.set_fill_ratio(Decimal("0.5"))
                result = self.place_order("AAPL", "BUY", Decimal("5"), f"partial-fill-{new_id('key')}")
                self.broker.set_fill_ratio(Decimal("1"))
                self._notify("info", "Partial-fill simulated", f"Paper order result: {result['decision']}")
            elif scenario == "duplicate-order":
                key = f"duplicate-{new_id('key')}"
                first = self.place_order("AAPL", "BUY", Decimal("1"), key)
                second = self.place_order("AAPL", "BUY", Decimal("1"), key)
                self._notify("warning", "Duplicate order rejected", f"First: {first['decision']}; retry: {second['decision']}")
            elif scenario == "reconciliation-failure":
                self._flags["reconciliation_ok"] = False
                self.controls.pause("Reconciliation mismatch")
                self._notify("critical", "Reconciliation mismatch", "Automated trading paused")
            elif scenario == "manual-trade":
                self._manual_trade()
            elif scenario == "manual-withdrawal":
                self._manual_withdrawal()
            elif scenario == "tax-warning":
                self._event("TAX_REVIEW_REQUIRED", {"reason": "Potential homogeneous-security reacquisition"}, Origin.BROKER)
                self._notify("warning", "Tax review required", "Potential homogeneous-security issue detected")
            elif scenario == "kill-switch":
                return self.stop_everything("Simulated kill-switch event")
            else:
                raise ValueError(f"unknown scenario: {scenario}")
            return self.dashboard()

    def place_order(
        self,
        instrument_id: str,
        side: str,
        notional: Decimal,
        idempotency_key: str | None = None,
        strategy_id: str = "dashboard-manual-paper",
        reason_code: str = "OWNER_DEMO_ORDER",
    ) -> dict[str, Any]:
        with self._lock:
            if instrument_id not in self.instruments:
                raise ValueError("instrument is not allowlisted")
            side_value = Side(side.upper())
            kind = IntentKind.EXIT if side_value is Side.SELL else IntentKind.ENTRY
            key = idempotency_key or f"dashboard-{new_id('key')}"
            before_position = next((position for position in self.broker.positions() if position.instrument_id == instrument_id), None)
            quote = self._current_quote(instrument_id)
            intent = TradeIntent(
                intent_id=new_id("intent"),
                strategy_id=strategy_id,
                strategy_version="demo-trend-v1" if strategy_id == "demo-trend-v1" else "demo-v1",
                model_version=None,
                instrument_id=instrument_id,
                side=side_value,
                kind=kind,
                desired_notional=notional,
                confidence=None,
                reason_codes=(reason_code,),
                feature_snapshot_hash="dashboard-manual",
                timestamp=utc_now(),
                account_id=self.settings.bot_account_id,
                mode=ExecutionMode.PAPER,
                idempotency_key=key,
                sizing_policy=SizingPolicy.BOUNDED,
            )
            result = self.execution.submit_intent(intent, quote, self._risk_snapshot(instrument_id))
            self._orders_today += 1
            self._idempotency_keys.add(key)
            if result.submission and result.submission.executions:
                if side_value is Side.SELL and before_position is not None:
                    realized_delta = sum(
                        (execution.price - before_position.average_entry) * execution.quantity - execution.fees
                        for execution in result.submission.executions
                    )
                    self._realized_pnl += realized_delta
                    self._realized_today += realized_delta
                    self._realized_week += realized_delta
                    self._realized_month += realized_delta
                self._notify("info", "Paper order filled", f"{side_value.value} {instrument_id} simulated")
            elif result.risk_decision.decision is Decision.REJECT:
                self._notify("warning", "Paper order rejected", "; ".join(result.risk_decision.reasons))
                if strategy_id == "demo-trend-v1" and "ORDER_RATE_LIMIT" in result.risk_decision.reasons:
                    self._stop_auto_worker()
                    self._notify("critical", "Automatic trading paused", "The owner order-rate limit was reached for this paper session")
                if strategy_id == "demo-trend-v1" and any(
                    reason in result.risk_decision.reasons
                    for reason in ("STALE_OR_FUTURE_QUOTE", "SPREAD_TOO_WIDE")
                ):
                    self._flags["market_data_healthy"] = False
                    self._stop_auto_worker()
                    self.controls.pause("Live market data quality failure")
                    self._notify("critical", "Automatic trading paused", "Live quote freshness or spread failed the safety checks")
            return {"decision": result.risk_decision.decision.value, "reasons": list(result.risk_decision.reasons), "dashboard": self.dashboard()}

    def _seed_if_needed(self) -> None:
        if self._market_data_live and not self._live_data_ready:
            if not self.store.events():
                self._event("LIVE_MARKET_DATA_NOT_READY", {"error": self._live_data_error or "unavailable"})
            return
        had_events = bool(self.store.events())
        seed_quotes = self.quotes if self._market_data_live else {
            "AAPL": replace(self.quotes["AAPL"], bid=Decimal("99.90"), ask=Decimal("100.00")),
            "MSFT": replace(self.quotes["MSFT"], bid=Decimal("399.80"), ask=Decimal("400.00")),
            "SAP": replace(self.quotes["SAP"], bid=Decimal("179.80"), ask=Decimal("180.00")),
        }
        seed_notional = self.owner_limits.max_total_exposure_eur / Decimal("3") * Decimal("0.95")
        seed_orders = tuple(
            (
                instrument_id,
                self.risk.quantity_for_notional(
                    seed_notional,
                    seed_quotes[instrument_id].ask,
                    self.instruments[instrument_id].quantity_increment,
                ),
            )
            for instrument_id in self.instruments
            if instrument_id not in self._unavailable_symbols
        )
        for instrument_id, quantity in seed_orders:
            if quantity <= Decimal("0"):
                continue
            request = OrderRequest(
                order_id=new_id("seed"),
                intent_id="demo-seed",
                account_id=self.settings.bot_account_id,
                instrument_id=instrument_id,
                side=Side.BUY,
                order_type=OrderType.MARKET,
                quantity=quantity,
                limit_price=None,
                idempotency_key=f"seed-{instrument_id}",
                mode=ExecutionMode.PAPER,
            )
            submission = self.broker.submit_order(request, seed_quotes[instrument_id])
            self._event("DEMO_SEED_EXECUTION", {"instrument": instrument_id, "quantity": quantity, "execution": [execution.execution_id for execution in submission.executions]})
        if not had_events:
            self._event("DEMO_RUNTIME_INITIALIZED", {"paper_only": True, "real_money": False})

    def _portfolio_values(self):
        positions = self.broker.positions()
        invested = sum((position.market_value for position in positions), Decimal("0"))
        unrealized = sum((position.unrealized_pnl for position in positions), Decimal("0"))
        equity = self.broker.snapshot().cash + invested
        return equity, invested, unrealized, positions

    def _stop_auto_worker(self) -> None:
        self._auto_running = False
        self._auto_stop.set()
        self._auto_thread = None

    def _auto_loop(self) -> None:
        while not self._auto_stop.wait(self._auto_interval_seconds):
            with self._lock:
                if not self._auto_running:
                    return
                try:
                    self._auto_tick += 1
                    self._advance_market()
                    self._auto_signal()
                except MarketDataError as exc:
                    self._flags["market_data_healthy"] = False
                    self._stop_auto_worker()
                    self.controls.pause("Live market data unavailable")
                    self._notify("critical", "Live market data unavailable", str(exc))
                    return
                except Exception as exc:  # a worker failure must stop automation
                    self._auto_running = False
                    self._auto_last_action = "Automatic trading stopped after worker error"
                    self._notify("critical", "Automatic trading stopped", f"Worker error: {type(exc).__name__}")
                    return

    def _advance_market(self) -> None:
        if self._market_data_provider is not None:
            fresh_quotes = self._market_data_provider.fetch_quotes(self.instruments)
            self._accept_live_quotes(fresh_quotes)
            self._live_data_ready = True
            self._flags["market_data_healthy"] = True
            self._live_data_error = None
            for quote in fresh_quotes.values():
                self.broker.set_quote(quote)
            self._record_prices()
            return
        moves = {
            "AAPL": (Decimal("0.06"), Decimal("-0.03"), Decimal("0.04"), Decimal("-0.05")),
            "MSFT": (Decimal("0.18"), Decimal("-0.12"), Decimal("0.10"), Decimal("-0.08")),
            "SAP": (Decimal("0.09"), Decimal("-0.06"), Decimal("0.12"), Decimal("-0.04")),
        }
        for instrument_id, quote in self.quotes.items():
            if self._flags["stale_prices"]:
                continue
            delta = moves[instrument_id][self._auto_tick % 4]
            updated = replace(
                quote,
                bid=max(Decimal("0.01"), quote.bid + delta),
                ask=max(Decimal("0.02"), quote.ask + delta),
                timestamp=utc_now(),
            )
            self.quotes[instrument_id] = updated
            self.broker.set_quote(updated)
        self._record_prices()

    def _record_prices(self) -> None:
        for instrument_id, quote in self.quotes.items():
            if instrument_id in self._unavailable_symbols:
                continue
            history = self._price_history.setdefault(instrument_id, [])
            history.append(quote.midpoint)
            if len(history) > 12:
                del history[:-12]

    def _accept_live_quotes(self, quotes: dict[str, Quote]) -> None:
        valid = {
            instrument_id: quote
            for instrument_id, quote in quotes.items()
            if quote.spread_bps <= self._max_live_spread_bps
        }
        self._unavailable_symbols = set(self.instruments) - set(valid)
        if not valid:
            raise MarketDataError("all live quotes failed spread validation")
        self.quotes.update(valid)

    def _auto_signal(self) -> None:
        """Bounded momentum paper strategy with a hold period and exit rules."""
        positions = self.broker.positions()
        now = utc_now()
        for position in positions:
            self._auto_opened_at.setdefault(position.instrument_id, now)
        if self._auto_tick % self._auto_trade_every_ticks:
            self._auto_last_action = "Market observation completed"
            return

        # Exits are driven by a meaningful return, never by a timer alone.
        for position in positions:
            opened_at = self._auto_opened_at[position.instrument_id]
            if now - opened_at < self._auto_min_hold:
                continue
            return_pct = position.unrealized_pnl / position.cost_basis * Decimal("100")
            if return_pct >= self._auto_take_profit_pct or return_pct <= -self._auto_stop_loss_pct:
                notional = min(Decimal("25"), position.market_value)
                result = self.place_order(
                    position.instrument_id,
                    "SELL",
                    notional,
                    f"{self._auto_session_id}-exit-{self._auto_tick}-{position.instrument_id}",
                    strategy_id="demo-trend-v1",
                    reason_code="AUTO_TAKE_PROFIT" if return_pct >= self._auto_take_profit_pct else "AUTO_STOP_LOSS",
                )
                self._auto_last_trade_at[position.instrument_id] = now
                self._auto_last_action = f"{position.instrument_id} exit: {result['decision']} ({return_pct:.2f}%)"
                return

        # Entries require a short momentum history and a meaningful notional.
        candidate = self._momentum_candidate(positions)
        if candidate is None or self.broker.snapshot().cash < Decimal("30"):
            self._auto_last_action = "No qualified signal; holding"
            return
        instrument_id, momentum_pct = candidate
        last_trade = self._auto_last_trade_at.get(instrument_id)
        if last_trade is not None and now - last_trade < self._auto_min_hold:
            self._auto_last_action = "Signal cooldown active; holding"
            return
        result = self.place_order(
            instrument_id,
            "BUY",
            Decimal("25"),
            f"{self._auto_session_id}-entry-{self._auto_tick}-{instrument_id}",
            strategy_id="demo-trend-v1",
            reason_code="AUTO_MOMENTUM_SIGNAL",
        )
        self._auto_last_trade_at[instrument_id] = now
        self._auto_opened_at.setdefault(instrument_id, now)
        self._auto_last_action = f"{instrument_id} entry: {result['decision']} (+{momentum_pct:.2f}% momentum)"

    def _momentum_candidate(self, positions) -> tuple[str, Decimal] | None:
        held = {position.instrument_id for position in positions}
        candidates: list[tuple[str, Decimal]] = []
        for instrument_id, history in self._price_history.items():
            if instrument_id in held or len(history) < 4:
                continue
            baseline = history[-4]
            if baseline <= Decimal("0"):
                continue
            momentum = (history[-1] - baseline) / baseline * Decimal("100")
            if momentum >= Decimal("0.20"):
                candidates.append((instrument_id, momentum))
        return max(candidates, key=lambda candidate: candidate[1]) if candidates else None

    def _current_quote(self, instrument_id: str) -> Quote:
        quote = self.quotes[instrument_id]
        if self._market_data_live:
            self.broker.set_quote(quote)
            return quote
        if self._flags["stale_prices"]:
            return replace(quote, timestamp=utc_now() - timedelta(seconds=30))
        quote = replace(quote, timestamp=utc_now())
        self.quotes[instrument_id] = quote
        self.broker.set_quote(quote)
        return quote

    def _quotes_fresh(self) -> bool:
        now = utc_now()
        valid_quotes = {
            instrument_id: quote
            for instrument_id, quote in self.quotes.items()
            if instrument_id not in self._unavailable_symbols
        }
        return bool(valid_quotes) and all(
            quote.timestamp <= now + timedelta(seconds=2) and now - quote.timestamp <= self._live_quote_max_age
            for quote in valid_quotes.values()
        )

    def _risk_snapshot(self, instrument_id: str) -> RiskSnapshot:
        equity, invested, _, positions = self._portfolio_values()
        current = next((position.market_value for position in positions if position.instrument_id == instrument_id), Decimal("0"))
        return RiskSnapshot(
            available_cash=self.broker.snapshot().cash,
            withdrawable_cash=self.broker.snapshot().withdrawable_cash,
            total_equity=equity,
            current_exposure=invested,
            open_positions=len(positions),
            open_orders_today=self._orders_today,
            realized_pnl_today=self._realized_today,
            realized_pnl_week=self._realized_week,
            realized_pnl_month=self._realized_month,
            unrealized_pnl=sum((position.unrealized_pnl for position in positions), Decimal("0")),
            drawdown_percent=Decimal("2.8"),
            broker_healthy=self._flags["broker_healthy"],
            market_data_healthy=self._flags["market_data_healthy"],
            reconciled=self._flags["reconciliation_ok"],
            current_position_notional=current,
            existing_idempotency_keys=frozenset(self._idempotency_keys),
        )

    def _resume_checks(self, kill_switch_clear: bool | None = None):
        return ResumeChecks(
            broker_healthy=self._flags["broker_healthy"],
            market_data_healthy=self._flags["market_data_healthy"] and not self._flags["stale_prices"],
            cash_known=True,
            positions_known=True,
            open_orders_known=True,
            reconciliation_ok=self._flags["reconciliation_ok"],
            risk_limits_ok=True,
            authorized_account=True,
            kill_switch_clear=(kill_switch_clear if kill_switch_clear is not None else self.controls.record.state.value != "KILL_SWITCH_ACTIVE"),
        )

    def _cancel_pending_entries(self) -> int:
        cancelled = 0
        for order in self._open_orders():
            if not order.request.reduces_position:
                self.broker.cancel_order(order.broker_order_id)
                cancelled += 1
        return cancelled

    def _open_orders(self):
        return tuple(order for order in self.broker.orders() if order.state.value in {"SUBMITTED", "ACKNOWLEDGED", "PARTIALLY_FILLED", "CANCEL_PENDING"})

    def _manual_trade(self) -> None:
        before = self.broker.snapshot()
        request = OrderRequest(
            order_id=new_id("manual"),
            intent_id="external-owner-trade",
            account_id=self.settings.bot_account_id,
            instrument_id="AAPL",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.01"),
            limit_price=None,
            idempotency_key=f"external-manual-{new_id('key')}",
            mode=ExecutionMode.PAPER,
            reduces_position=False,
        )
        submission = self.broker.submit_order(request, self.quotes["AAPL"])
        self._event("EXTERNAL_MANUAL_TRADE", {"instrument": "AAPL", "source": "owner", "execution_ids": [execution.execution_id for execution in submission.executions]}, Origin.OWNER_MANUAL)
        self.reconciliation.detect_external_position_change(dict(before.positions), dict(self.broker.snapshot().positions))
        self._notify("warning", "Manual broker trade detected", "Automated trading paused pending reconciliation")

    def _manual_withdrawal(self) -> None:
        current_cash = self.broker.snapshot().cash
        amount = min(Decimal("10"), current_cash)
        self.broker.apply_cash_movement(amount, increase=False)
        self._withdrawals += amount
        self.reconciliation.classify_cash_movement(current_cash, current_cash - amount, current_cash, self.settings.bot_account_id)
        self._notify("info", "Manual withdrawal detected", f"EUR {money(amount)} recorded as cash movement")

    def _risk_view(self) -> dict[str, Any]:
        current_target = min(Decimal("50"), self.owner_limits.max_position_eur)
        return {
            "mode": self.risk_configuration.mode.value,
            "hardLimits": {
                "totalCapital": money(self.owner_limits.max_total_capital_eur),
                "maxPosition": money(self.owner_limits.max_position_eur),
                "maxExposure": money(self.owner_limits.max_total_exposure_eur),
                "maxOpenPositions": self.owner_limits.max_open_positions,
                "dailyLoss": money(self.owner_limits.max_daily_loss_eur),
                "dailyProfit": money(self.owner_limits.max_daily_profit_eur or Decimal("0")),
                "maxDrawdown": f"{self.owner_limits.max_drawdown_percent}%",
            },
            "currentTarget": money(current_target),
            "allowedMin": money(self.risk_configuration.auto_min_position_eur),
            "allowedMax": money(self.owner_limits.max_position_eur),
            "dailyUsed": money(max(Decimal("0"), self._realized_today)),
            "dailyLossBudget": money(self.owner_limits.max_daily_loss_eur),
        }

    def _chart_data(self, equity: Decimal, unrealized: Decimal) -> dict[str, Any]:
        points = [dict(point) for point in self._equity_history]
        points[-1]["value"] = money(equity)
        return {
            "equity": points,
            "pnl": [{"label": "Realized", "value": money(self._realized_pnl), "color": "green"}, {"label": "Unrealized", "value": money(unrealized), "color": "blue"}],
            "drawdown": [{"label": "Current", "value": "2.8"}, {"label": "Maximum", "value": "6.4"}],
        }

    def _position_view(self, position) -> dict[str, Any]:
        instrument = self.instruments[position.instrument_id]
        return {
            "instrument": instrument.ticker,
            "isin": instrument.isin,
            "ticker": instrument.ticker,
            "side": "LONG",
            "quantity": format(position.quantity, "f"),
            "averageEntry": money(position.average_entry),
            "currentPrice": money(position.market_price),
            "marketValue": money(position.market_value),
            "costBasis": money(position.cost_basis),
            "unrealizedPnl": money(position.unrealized_pnl),
            "returnPct": f"{(position.unrealized_pnl / position.cost_basis * Decimal('100')).quantize(Decimal('0.1'))}%" if position.cost_basis else "0.0%",
            "exposure": money(position.market_value),
            "strategy": "Demo Trend v1",
            "openedAt": iso(utc_now() - timedelta(days=12)),
            "riskStatus": "WITHIN LIMIT",
        }

    def _order_view(self, order) -> dict[str, Any]:
        executions = [execution for execution in self.broker.executions() if execution.broker_order_id == order.broker_order_id]
        return {
            "id": order.order_id,
            "brokerId": order.broker_order_id,
            "instrument": order.request.instrument_id,
            "side": order.request.side.value,
            "quantity": format(order.request.quantity, "f"),
            "state": order.state.value,
            "createdAt": iso(order.submitted_at),
            "message": order.message,
            "fills": [{"quantity": format(execution.quantity, "f"), "price": money(execution.price), "fees": money(execution.fees)} for execution in executions],
        }

    def _health_view(self) -> list[dict[str, Any]]:
        return [
            {"name": "Database", "status": "HEALTHY", "latency": "2 ms", "detail": "SQLite ledger available"},
            {"name": "Paper broker", "status": "HEALTHY" if self._flags["broker_healthy"] else "UNAVAILABLE", "latency": "48 ms", "detail": "Simulated execution"},
            {"name": "Market data", "status": "HEALTHY" if self._flags["market_data_healthy"] and not self._flags["stale_prices"] else "DEGRADED", "latency": "82 ms", "detail": "Demo quote feed"},
            {"name": "Risk engine", "status": "HEALTHY", "latency": "0.4 ms", "detail": "Deterministic owner-bounded checks"},
            {"name": "Reconciliation", "status": "HEALTHY" if self._flags["reconciliation_ok"] else "CRITICAL", "latency": "31 ms", "detail": "Cash, positions, orders, fills"},
            {"name": "WebSocket", "status": "HEALTHY", "latency": "12 ms", "detail": "Dashboard stream"},
        ]

    def _audit_view(self) -> list[dict[str, Any]]:
        return [
            {"eventId": event.event_id, "type": event.event_type, "origin": event.origin.value, "time": iso(event.occurred_at), "detail": json.dumps(event.payload, default=str)}
            for event in self.store.events()[-8:][::-1]
        ]

    def _seed_equity_history(self) -> list[dict[str, str]]:
        base = Decimal("100")
        values = ("100.00", "101.80", "99.40", "104.20", "106.10", "105.40", "109.80", "111.20", "109.90", "114.60", "118.30", "116.80", "121.10", "124.70", "125.00")
        start = utc_now() - timedelta(days=len(values) - 1)
        return [{"date": (start + timedelta(days=index)).strftime("%d %b"), "value": value} for index, value in enumerate(values)]

    def _notify(self, severity: str, title: str, detail: str) -> None:
        self._notifications.append({"id": new_id("notification"), "severity": severity, "title": title, "detail": detail, "time": iso(utc_now()), "read": False})

    def _event(self, event_type: str, payload: dict[str, Any], origin: Origin = Origin.TRADEFORGE) -> None:
        self.store.append_event(event_type, self.settings.bot_account_id, ExecutionMode.PAPER, origin, payload)
