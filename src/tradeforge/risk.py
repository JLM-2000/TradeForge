"""Deterministic, owner-bounded risk decisions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_DOWN
from typing import Mapping

from .config import Settings
from .controls import ControlCenter
from .domain import (
    AssetClass,
    Decision,
    ExecutionMode,
    Instrument,
    IntentKind,
    Quote,
    RiskConfiguration,
    RiskDecision,
    RiskSnapshot,
    SizingPolicy,
    Side,
    TradeIntent,
    OwnerHardLimits,
    ZERO,
    utc_now,
)


class RiskEngine:
    """Pure policy evaluation with no broker access and no AI authority."""

    def __init__(
        self,
        settings: Settings,
        owner_limits: OwnerHardLimits,
        risk_configuration: RiskConfiguration,
        instruments: Mapping[str, Instrument],
        controls: ControlCenter,
        max_quote_age: timedelta = timedelta(seconds=5),
        max_spread_bps: Decimal = Decimal("100"),
    ) -> None:
        self.settings = settings
        self.owner_limits = owner_limits
        self.risk_configuration = risk_configuration
        self.instruments = instruments
        self.controls = controls
        self.max_quote_age = max_quote_age
        self.max_spread_bps = max_spread_bps

    def evaluate(
        self,
        intent: TradeIntent,
        quote: Quote,
        snapshot: RiskSnapshot,
        now: datetime | None = None,
    ) -> RiskDecision:
        now = (now or utc_now()).astimezone(UTC)
        checks: dict[str, bool] = {}
        reasons: list[str] = []

        checks["account_authorized"] = intent.account_id == self.settings.bot_account_id
        if not checks["account_authorized"]:
            reasons.append("UNAUTHORIZED_ACCOUNT")
        checks["personal_account_denied"] = intent.account_id not in self.settings.personal_investment_account_ids
        if not checks["personal_account_denied"]:
            reasons.append("PERSONAL_INVESTMENT_ACCOUNT_DENIED")
        checks["mode_matches"] = intent.mode is self.settings.mode
        if not checks["mode_matches"]:
            reasons.append("MODE_MISMATCH")
        checks["live_gate"] = intent.mode is not ExecutionMode.LIVE or self.settings.live_execution_allowed
        if intent.mode is ExecutionMode.LIVE and not self.settings.live_execution_allowed:
            reasons.append("LIVE_EXECUTION_DENIED")

        instrument = self.instruments.get(intent.instrument_id)
        checks["instrument_allowlisted"] = intent.instrument_id in self.settings.allowed_instrument_ids
        if not checks["instrument_allowlisted"]:
            reasons.append("INSTRUMENT_NOT_ALLOWLISTED")
        checks["instrument_known"] = instrument is not None
        if not checks["instrument_known"]:
            reasons.append("INSTRUMENT_UNKNOWN")
        if instrument is not None:
            checks["instrument_tradable"] = instrument.tradable
            checks["v1_asset_class_allowed"] = instrument.asset_class in {AssetClass.STOCK, AssetClass.ETF}
            if not instrument.tradable:
                reasons.append("INSTRUMENT_NOT_TRADABLE")
            if not checks["v1_asset_class_allowed"]:
                reasons.append("ASSET_CLASS_RESTRICTED")
        else:
            checks["instrument_tradable"] = False
            checks["v1_asset_class_allowed"] = False

        checks["bounded_sizing"] = intent.sizing_policy is SizingPolicy.BOUNDED
        if not checks["bounded_sizing"]:
            reasons.append("UNCONTROLLED_SIZING_POLICY")
        checks["quote_fresh"] = self._quote_fresh(quote, now, self.max_quote_age)
        if not checks["quote_fresh"]:
            reasons.append("STALE_OR_FUTURE_QUOTE")
        checks["spread_acceptable"] = quote.spread_bps <= self.max_spread_bps
        if not checks["spread_acceptable"]:
            reasons.append("SPREAD_TOO_WIDE")
        checks["broker_healthy"] = self.settings.broker_healthy and snapshot.broker_healthy
        checks["market_data_healthy"] = self.settings.market_data_healthy and snapshot.market_data_healthy
        checks["reconciliation_ok"] = self.settings.reconciliation_ok and snapshot.reconciled
        for name in ("broker_healthy", "market_data_healthy", "reconciliation_ok"):
            if not checks[name]:
                reasons.append(name.upper())
        gate = self.controls.execution_gate(intent.account_id, intent.kind is IntentKind.ENTRY)
        checks["control_gate"] = gate.allowed
        if not gate.allowed:
            reasons.append(gate.reason.upper())
        checks["duplicate_intent"] = intent.idempotency_key not in snapshot.existing_idempotency_keys
        if not checks["duplicate_intent"]:
            reasons.append("DUPLICATE_IDEMPOTENCY_KEY")

        basis_pnl_day = snapshot.realized_pnl_today
        basis_pnl_week = snapshot.realized_pnl_week
        basis_pnl_month = snapshot.realized_pnl_month
        if self.risk_configuration.p_and_l_basis == "REALIZED_PLUS_UNREALIZED":
            basis_pnl_day += snapshot.unrealized_pnl
            basis_pnl_week += snapshot.unrealized_pnl
            basis_pnl_month += snapshot.unrealized_pnl
        checks["daily_loss_limit"] = basis_pnl_day > -self.owner_limits.max_daily_loss_eur
        checks["weekly_loss_limit"] = basis_pnl_week > -self.owner_limits.max_weekly_loss_eur
        checks["monthly_loss_limit"] = basis_pnl_month > -self.owner_limits.max_monthly_loss_eur
        if not checks["daily_loss_limit"]:
            reasons.append("DAILY_LOSS_LIMIT")
        if not checks["weekly_loss_limit"]:
            reasons.append("WEEKLY_LOSS_LIMIT")
        if not checks["monthly_loss_limit"]:
            reasons.append("MONTHLY_LOSS_LIMIT")
        checks["daily_profit_policy"] = not (
            intent.kind is IntentKind.ENTRY
            and self.risk_configuration.stop_new_entries_on_profit
            and self.owner_limits.max_daily_profit_eur is not None
            and basis_pnl_day >= self.owner_limits.max_daily_profit_eur
        )
        if not checks["daily_profit_policy"]:
            reasons.append("DAILY_PROFIT_TARGET")
        checks["drawdown_limit"] = snapshot.drawdown_percent < self.owner_limits.max_drawdown_percent
        if not checks["drawdown_limit"]:
            reasons.append("DRAWDOWN_LIMIT")
        checks["order_rate"] = snapshot.open_orders_today < self.owner_limits.max_orders_per_day
        if not checks["order_rate"]:
            reasons.append("ORDER_RATE_LIMIT")

        if intent.kind is IntentKind.ENTRY and intent.side is Side.SELL:
            checks["long_only_entry"] = False
            reasons.append("SHORT_SELLING_DISABLED")
        else:
            checks["long_only_entry"] = True
        if intent.kind is IntentKind.EXIT and snapshot.current_position_notional <= ZERO:
            checks["position_exists_for_exit"] = False
            reasons.append("NO_POSITION_TO_EXIT")
        else:
            checks["position_exists_for_exit"] = True

        hard_failure = bool(reasons)
        if hard_failure:
            return RiskDecision(
                intent_id=intent.intent_id,
                decision=Decision.REJECT,
                approved_notional=ZERO,
                reasons=tuple(dict.fromkeys(reasons)),
                checks=checks,
                created_at=now,
                risk_config_version=self.owner_limits.version,
            )

        requested = intent.desired_notional
        approved = requested
        if intent.kind is IntentKind.ENTRY:
            if intent.side is Side.BUY:
                risk_cash = snapshot.risk_available_cash if snapshot.risk_available_cash is not None else snapshot.available_cash
                available_position = self.owner_limits.max_position_eur - snapshot.current_position_notional
                available_exposure = self.owner_limits.max_total_exposure_eur - snapshot.current_exposure
                available_capital = self.owner_limits.max_total_capital_eur - snapshot.current_exposure
                approved = min(approved, risk_cash, available_position, available_exposure, available_capital)
            if snapshot.open_positions >= self.owner_limits.max_open_positions and snapshot.current_position_notional == ZERO:
                return self._reject(intent, checks, now, "OPEN_POSITION_LIMIT")
        else:
            approved = min(approved, snapshot.current_position_notional)

        if approved <= ZERO:
            return self._reject(intent, checks, now, "NO_RISK_CAPACITY")
        if self.risk_configuration.mode.value == "AUTO" and approved < self.risk_configuration.auto_min_position_eur:
            return self._reject(intent, checks, now, "AUTO_MINIMUM_EXCEEDS_RISK_CAPACITY")
        decision = Decision.RESIZE if approved < requested else Decision.APPROVE
        if decision is Decision.RESIZE:
            reasons.append("RESIZED_TO_OWNER_HARD_LIMIT")
        return RiskDecision(
            intent_id=intent.intent_id,
            decision=decision,
            approved_notional=approved,
            reasons=tuple(reasons),
            checks=checks,
            created_at=now,
            risk_config_version=self.owner_limits.version,
        )

    @staticmethod
    def _quote_fresh(quote: Quote, now: datetime, max_age: timedelta) -> bool:
        # Provider clocks can lead the application clock by a small amount.
        # Reject materially future data, but do not reject a valid quote for a
        # sub-second clock skew.
        return quote.timestamp <= now + timedelta(seconds=2) and now - quote.timestamp <= max_age

    def _reject(self, intent: TradeIntent, checks: dict[str, bool], now: datetime, reason: str) -> RiskDecision:
        return RiskDecision(
            intent_id=intent.intent_id,
            decision=Decision.REJECT,
            approved_notional=ZERO,
            reasons=(reason,),
            checks=checks,
            created_at=now,
            risk_config_version=self.owner_limits.version,
        )

    @staticmethod
    def quantity_for_notional(notional: Decimal, price: Decimal, increment: Decimal) -> Decimal:
        raw = notional / price
        units = (raw / increment).to_integral_value(rounding=ROUND_DOWN)
        return units * increment
