"""Typed, broker-neutral domain objects and state machines."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4


ZERO = Decimal("0")
ONE = Decimal("1")
MONEY_QUANTUM = Decimal("0.01")


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _decimal(value: Decimal | int | str, field_name: str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be a Decimal-compatible value") from exc
    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return result


def _positive(value: Decimal | int | str, field_name: str) -> Decimal:
    result = _decimal(value, field_name)
    if result <= ZERO:
        raise ValueError(f"{field_name} must be positive")
    return result


def _non_negative(value: Decimal | int | str, field_name: str) -> Decimal:
    result = _decimal(value, field_name)
    if result < ZERO:
        raise ValueError(f"{field_name} must be non-negative")
    return result


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


class ExecutionMode(str, Enum):
    DEMO = "DEMO"
    PAPER = "PAPER"
    SHADOW = "SHADOW"
    LIVE = "LIVE"


class RiskMode(str, Enum):
    MANUAL = "MANUAL"
    AUTO = "AUTO"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class IntentKind(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


class SizingPolicy(str, Enum):
    BOUNDED = "BOUNDED"
    MARTINGALE = "MARTINGALE"
    ALL_IN = "ALL_IN"
    REVENGE = "REVENGE"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class Decision(str, Enum):
    APPROVE = "APPROVE"
    RESIZE = "RESIZE"
    REJECT = "REJECT"


class OrderState(str, Enum):
    CREATED = "CREATED"
    RISK_REJECTED = "RISK_REJECTED"
    APPROVED = "APPROVED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    BROKER_REJECTED = "BROKER_REJECTED"
    FAILED = "FAILED"
    UNKNOWN_REQUIRES_RECONCILIATION = "UNKNOWN_REQUIRES_RECONCILIATION"


class Origin(str, Enum):
    TRADEFORGE = "TRADEFORGE"
    OWNER_MANUAL = "OWNER_MANUAL"
    BROKER = "BROKER"
    CORRECTION = "CORRECTION"


class AssetClass(str, Enum):
    STOCK = "STOCK"
    ETF = "ETF"
    CFD = "CFD"
    FUTURE = "FUTURE"
    OPTION = "OPTION"
    FOREX = "FOREX"
    CRYPTO = "CRYPTO"
    LEVERAGED_ETF = "LEVERAGED_ETF"
    STRUCTURED = "STRUCTURED"


class Health(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    PAUSED = "PAUSED"
    UNAVAILABLE = "UNAVAILABLE"
    CRITICAL = "CRITICAL"


class ControlState(str, Enum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"


class ReconciliationStatus(str, Enum):
    MATCHED = "MATCHED"
    MISMATCH = "MISMATCH"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class StrategyStatus(str, Enum):
    RESEARCH = "RESEARCH"
    BACKTEST = "BACKTEST"
    VALIDATED = "VALIDATED"
    PAPER = "PAPER"
    SHADOW = "SHADOW"
    APPROVED = "APPROVED"
    DISABLED = "DISABLED"


@dataclass(frozen=True, slots=True)
class Instrument:
    instrument_id: str
    isin: str | None
    ticker: str
    venue: str
    currency: str = "EUR"
    asset_class: AssetClass = AssetClass.STOCK
    tradable: bool = True
    quantity_increment: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if not self.instrument_id.strip() or not self.ticker.strip():
            raise ValueError("instrument_id and ticker are required")
        if self.isin is not None and not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{10}", self.isin):
            raise ValueError("isin must be a 12-character ISO 6166 value")
        if self.currency != self.currency.upper() or len(self.currency) != 3:
            raise ValueError("currency must be a three-letter uppercase code")
        _positive(self.quantity_increment, "quantity_increment")
        if self.asset_class not in {AssetClass.STOCK, AssetClass.ETF}:
            raise ValueError("V1 instrument restrictions exclude leveraged/speculative products")


@dataclass(frozen=True, slots=True)
class Quote:
    instrument_id: str
    bid: Decimal
    ask: Decimal
    timestamp: datetime
    source: str
    sequence: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "bid", _positive(self.bid, "bid"))
        object.__setattr__(self, "ask", _positive(self.ask, "ask"))
        if self.bid > self.ask:
            raise ValueError("bid cannot be greater than ask")
        object.__setattr__(self, "timestamp", _aware(self.timestamp, "timestamp"))
        if not self.source.strip():
            raise ValueError("quote source is required")

    @property
    def midpoint(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    @property
    def spread_bps(self) -> Decimal:
        return (self.ask - self.bid) / self.midpoint * Decimal("10000")


@dataclass(frozen=True, slots=True)
class Candle:
    instrument_id: str
    opened_at: datetime
    closed_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    source: str

    def __post_init__(self) -> None:
        for name in ("open", "high", "low", "close"):
            object.__setattr__(self, name, _positive(getattr(self, name), name))
        object.__setattr__(self, "volume", _non_negative(self.volume, "volume"))
        object.__setattr__(self, "opened_at", _aware(self.opened_at, "opened_at"))
        object.__setattr__(self, "closed_at", _aware(self.closed_at, "closed_at"))
        if self.closed_at <= self.opened_at or self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("invalid candle bounds")


@dataclass(frozen=True, slots=True)
class MarketEvent:
    event_id: str
    instrument_id: str
    event_type: str
    observed_at: datetime
    source: str
    sequence: int
    payload_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        if self.sequence < 0 or not self.payload_hash.strip():
            raise ValueError("market event sequence and payload hash are required")


@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    snapshot_id: str
    instrument_id: str
    captured_at: datetime
    feature_values: tuple[tuple[str, Decimal], ...]
    snapshot_hash: str
    dataset_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "captured_at", _aware(self.captured_at, "captured_at"))
        if not self.snapshot_hash.strip() or not self.dataset_version.strip():
            raise ValueError("feature snapshot hash and dataset version are required")
        for name, value in self.feature_values:
            if not name.strip() or not _decimal(value, name).is_finite():
                raise ValueError("feature values must be named finite decimals")


@dataclass(frozen=True, slots=True)
class Signal:
    signal_id: str
    strategy_id: str
    strategy_version: str
    instrument_id: str
    side: Side
    confidence: Decimal
    reason_codes: tuple[str, ...]
    feature_snapshot_hash: str
    generated_at: datetime

    def __post_init__(self) -> None:
        confidence = _decimal(self.confidence, "confidence")
        if not ZERO <= confidence <= ONE:
            raise ValueError("signal confidence must be between 0 and 1")
        object.__setattr__(self, "generated_at", _aware(self.generated_at, "generated_at"))


@dataclass(frozen=True, slots=True)
class Fee:
    fee_id: str
    amount: Decimal
    currency: str
    fee_type: str
    related_event_id: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _non_negative(self.amount, "amount"))
        object.__setattr__(self, "occurred_at", _aware(self.occurred_at, "occurred_at"))


@dataclass(frozen=True, slots=True)
class Dividend:
    dividend_id: str
    instrument_id: str
    quantity: Decimal
    gross_amount: Decimal
    withholding: Decimal
    currency: str
    payment_at: datetime
    source_event_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", _positive(self.quantity, "quantity"))
        object.__setattr__(self, "gross_amount", _positive(self.gross_amount, "gross_amount"))
        object.__setattr__(self, "withholding", _non_negative(self.withholding, "withholding"))
        object.__setattr__(self, "payment_at", _aware(self.payment_at, "payment_at"))


@dataclass(frozen=True, slots=True)
class FXConversion:
    conversion_id: str
    from_currency: str
    to_currency: str
    from_amount: Decimal
    to_amount: Decimal
    rate: Decimal
    converted_at: datetime
    source_event_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "from_amount", _positive(self.from_amount, "from_amount"))
        object.__setattr__(self, "to_amount", _positive(self.to_amount, "to_amount"))
        object.__setattr__(self, "rate", _positive(self.rate, "rate"))
        object.__setattr__(self, "converted_at", _aware(self.converted_at, "converted_at"))


@dataclass(frozen=True, slots=True)
class CorporateAction:
    action_id: str
    instrument_id: str
    action_type: str
    effective_at: datetime
    source_event_id: str
    details_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "effective_at", _aware(self.effective_at, "effective_at"))
        if not self.details_hash.strip():
            raise ValueError("corporate action details hash is required")


@dataclass(frozen=True, slots=True)
class TradeIntent:
    intent_id: str
    strategy_id: str
    strategy_version: str
    model_version: str | None
    instrument_id: str
    side: Side
    kind: IntentKind
    desired_notional: Decimal
    confidence: Decimal | None
    reason_codes: tuple[str, ...]
    feature_snapshot_hash: str
    timestamp: datetime
    account_id: str
    mode: ExecutionMode
    idempotency_key: str
    sizing_policy: SizingPolicy = SizingPolicy.BOUNDED

    def __post_init__(self) -> None:
        object.__setattr__(self, "desired_notional", _positive(self.desired_notional, "desired_notional"))
        object.__setattr__(self, "timestamp", _aware(self.timestamp, "timestamp"))
        if self.confidence is not None:
            confidence = _decimal(self.confidence, "confidence")
            if not ZERO <= confidence <= ONE:
                raise ValueError("confidence must be between 0 and 1")
            object.__setattr__(self, "confidence", confidence)
        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        if not self.feature_snapshot_hash.strip():
            raise ValueError("feature_snapshot_hash is required")


@dataclass(frozen=True, slots=True)
class OwnerHardLimits:
    """Owner-owned ceilings. Automated code cannot construct replacements in production."""

    version: str
    max_total_capital_eur: Decimal
    max_position_eur: Decimal
    max_total_exposure_eur: Decimal
    max_open_positions: int
    max_daily_loss_eur: Decimal
    max_daily_profit_eur: Decimal | None
    max_weekly_loss_eur: Decimal
    max_weekly_profit_eur: Decimal | None
    max_monthly_loss_eur: Decimal
    max_monthly_profit_eur: Decimal | None
    max_drawdown_percent: Decimal
    max_orders_per_day: int

    def __post_init__(self) -> None:
        _positive(self.max_total_capital_eur, "max_total_capital_eur")
        _positive(self.max_position_eur, "max_position_eur")
        _positive(self.max_total_exposure_eur, "max_total_exposure_eur")
        if self.max_open_positions < 1 or self.max_orders_per_day < 1:
            raise ValueError("position and order ceilings must be positive")
        for name in (
            "max_daily_loss_eur",
            "max_weekly_loss_eur",
            "max_monthly_loss_eur",
        ):
            _positive(getattr(self, name), name)
        for name in (
            "max_daily_profit_eur",
            "max_weekly_profit_eur",
            "max_monthly_profit_eur",
        ):
            value = getattr(self, name)
            if value is not None:
                _positive(value, name)
        drawdown = _positive(self.max_drawdown_percent, "max_drawdown_percent")
        if drawdown > Decimal("100"):
            raise ValueError("max_drawdown_percent cannot exceed 100")


@dataclass(frozen=True, slots=True)
class RiskConfiguration:
    mode: RiskMode = RiskMode.MANUAL
    auto_min_position_eur: Decimal = Decimal("1")
    cancel_pending_on_pause: bool = True
    p_and_l_basis: str = "REALIZED_ONLY"
    stop_new_entries_on_profit: bool = True
    tax_reserve_excluded_from_risk: bool = True

    def __post_init__(self) -> None:
        _positive(self.auto_min_position_eur, "auto_min_position_eur")
        if self.p_and_l_basis not in {"REALIZED_ONLY", "REALIZED_PLUS_UNREALIZED"}:
            raise ValueError("unsupported P&L basis")


@dataclass(frozen=True, slots=True)
class Position:
    instrument_id: str
    quantity: Decimal
    average_entry: Decimal
    market_price: Decimal
    strategy_id: str | None = None

    def __post_init__(self) -> None:
        quantity = _non_negative(self.quantity, "quantity")
        if quantity == ZERO:
            object.__setattr__(self, "average_entry", ZERO)
        else:
            object.__setattr__(self, "average_entry", _positive(self.average_entry, "average_entry"))
        object.__setattr__(self, "market_price", _positive(self.market_price, "market_price"))

    @property
    def market_value(self) -> Decimal:
        return self.quantity * self.market_price

    @property
    def cost_basis(self) -> Decimal:
        return self.quantity * self.average_entry

    @property
    def unrealized_pnl(self) -> Decimal:
        return self.market_value - self.cost_basis


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    snapshot_id: str
    account_id: str
    captured_at: datetime
    total_equity: Decimal
    available_cash: Decimal
    withdrawable_cash: Decimal
    invested_value: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    current_drawdown: Decimal
    max_drawdown: Decimal
    fee_total: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "captured_at", _aware(self.captured_at, "captured_at"))
        for name in (
            "total_equity",
            "available_cash",
            "withdrawable_cash",
            "invested_value",
            "fee_total",
        ):
            object.__setattr__(self, name, _non_negative(getattr(self, name), name))
        object.__setattr__(self, "current_drawdown", _non_negative(self.current_drawdown, "current_drawdown"))
        object.__setattr__(self, "max_drawdown", _non_negative(self.max_drawdown, "max_drawdown"))


@dataclass(frozen=True, slots=True)
class StrategyVersion:
    strategy_id: str
    version: str
    status: StrategyStatus
    parameters_hash: str
    source_revision: str
    allowed_instruments: frozenset[str]
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", _aware(self.created_at, "created_at"))
        if not self.parameters_hash.strip() or not self.source_revision.strip():
            raise ValueError("strategy version hashes are required")
        if self.status is StrategyStatus.APPROVED and not self.allowed_instruments:
            raise ValueError("approved strategies require an instrument allowlist")


@dataclass(frozen=True, slots=True)
class ModelVersion:
    model_id: str
    version: str
    dataset_version: str
    feature_set_version: str
    hyperparameters_hash: str
    created_at: datetime
    promoted_by_owner: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", _aware(self.created_at, "created_at"))
        if not all(value.strip() for value in (self.dataset_version, self.feature_set_version, self.hyperparameters_hash)):
            raise ValueError("model provenance fields are required")


@dataclass(frozen=True, slots=True)
class AuditEvent:
    audit_id: str
    category: str
    actor: str
    action: str
    occurred_at: datetime
    previous_value: str | None
    new_value: str | None
    reason: str
    context_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "occurred_at", _aware(self.occurred_at, "occurred_at"))
        if not self.actor.strip() or not self.action.strip() or not self.reason.strip():
            raise ValueError("audit actor, action, and reason are required")


@dataclass(frozen=True, slots=True)
class RiskSnapshot:
    available_cash: Decimal
    withdrawable_cash: Decimal
    total_equity: Decimal
    current_exposure: Decimal
    open_positions: int
    open_orders_today: int
    realized_pnl_today: Decimal = ZERO
    realized_pnl_week: Decimal = ZERO
    realized_pnl_month: Decimal = ZERO
    unrealized_pnl: Decimal = ZERO
    drawdown_percent: Decimal = ZERO
    broker_healthy: bool = True
    market_data_healthy: bool = True
    reconciled: bool = True
    current_position_notional: Decimal = ZERO
    risk_available_cash: Decimal | None = None
    existing_idempotency_keys: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        for name in (
            "available_cash",
            "withdrawable_cash",
            "total_equity",
            "current_exposure",
            "current_position_notional",
        ):
            _non_negative(getattr(self, name), name)
        if self.risk_available_cash is not None:
            _non_negative(self.risk_available_cash, "risk_available_cash")
        _non_negative(self.drawdown_percent, "drawdown_percent")
        if self.open_positions < 0 or self.open_orders_today < 0:
            raise ValueError("counts cannot be negative")


@dataclass(frozen=True, slots=True)
class RiskDecision:
    intent_id: str
    decision: Decision
    approved_notional: Decimal
    reasons: tuple[str, ...]
    checks: Mapping[str, bool]
    created_at: datetime
    risk_config_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "approved_notional", _non_negative(self.approved_notional, "approved_notional"))
        object.__setattr__(self, "created_at", _aware(self.created_at, "created_at"))
        if self.decision is Decision.REJECT and self.approved_notional != ZERO:
            raise ValueError("rejected risk decisions cannot approve notional")
        if self.decision is not Decision.REJECT and self.approved_notional <= ZERO:
            raise ValueError("approved decisions require positive notional")


@dataclass(frozen=True, slots=True)
class OrderRequest:
    order_id: str
    intent_id: str
    account_id: str
    instrument_id: str
    side: Side
    order_type: OrderType
    quantity: Decimal
    limit_price: Decimal | None
    idempotency_key: str
    mode: ExecutionMode
    reduces_position: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", _positive(self.quantity, "quantity"))
        if self.order_type is OrderType.LIMIT:
            if self.limit_price is None:
                raise ValueError("limit orders require limit_price")
            _positive(self.limit_price, "limit_price")
        elif self.limit_price is not None:
            raise ValueError("market orders cannot have limit_price")
        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key is required")


@dataclass(frozen=True, slots=True)
class BrokerOrder:
    order_id: str
    broker_order_id: str
    request: OrderRequest
    state: OrderState
    submitted_at: datetime
    message: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "submitted_at", _aware(self.submitted_at, "submitted_at"))


@dataclass(frozen=True, slots=True)
class Execution:
    execution_id: str
    broker_order_id: str
    instrument_id: str
    side: Side
    quantity: Decimal
    price: Decimal
    commission: Decimal
    fees: Decimal
    currency: str
    executed_at: datetime
    origin: Origin = Origin.TRADEFORGE

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", _positive(self.quantity, "quantity"))
        object.__setattr__(self, "price", _positive(self.price, "price"))
        object.__setattr__(self, "commission", _non_negative(self.commission, "commission"))
        object.__setattr__(self, "fees", _non_negative(self.fees, "fees"))
        object.__setattr__(self, "executed_at", _aware(self.executed_at, "executed_at"))

    @property
    def gross_amount(self) -> Decimal:
        return self.quantity * self.price


@dataclass(frozen=True, slots=True)
class CashMovement:
    movement_id: str
    account_id: str
    movement_type: str
    amount: Decimal
    currency: str
    occurred_at: datetime
    origin: Origin
    broker_reference: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _positive(self.amount, "amount"))
        object.__setattr__(self, "occurred_at", _aware(self.occurred_at, "occurred_at"))
        if self.movement_type not in {"EXTERNAL_DEPOSIT", "EXTERNAL_WITHDRAWAL"}:
            raise ValueError("unsupported cash movement type")


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    event_id: str
    event_type: str
    occurred_at: datetime
    account_id: str
    mode: ExecutionMode
    origin: Origin
    payload: Mapping[str, Any]
    previous_hash: str
    event_hash: str

    def canonical_payload(self) -> str:
        return json.dumps(self.payload, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True, slots=True)
class ControlRecord:
    state: ControlState = ControlState.RUNNING
    reason: str = ""
    activated_at: datetime | None = None
    cancel_pending_on_pause: bool = True

    def __post_init__(self) -> None:
        if self.activated_at is not None:
            object.__setattr__(self, "activated_at", _aware(self.activated_at, "activated_at"))


@dataclass(frozen=True, slots=True)
class ResumeChecks:
    broker_healthy: bool
    market_data_healthy: bool
    cash_known: bool
    positions_known: bool
    open_orders_known: bool
    reconciliation_ok: bool
    risk_limits_ok: bool
    authorized_account: bool
    kill_switch_clear: bool

    @property
    def passed(self) -> bool:
        return all(
            (
                self.broker_healthy,
                self.market_data_healthy,
                self.cash_known,
                self.positions_known,
                self.open_orders_known,
                self.reconciliation_ok,
                self.risk_limits_ok,
                self.authorized_account,
                self.kill_switch_clear,
            )
        )

    def failures(self) -> tuple[str, ...]:
        values = {
            "broker_healthy": self.broker_healthy,
            "market_data_healthy": self.market_data_healthy,
            "cash_known": self.cash_known,
            "positions_known": self.positions_known,
            "open_orders_known": self.open_orders_known,
            "reconciliation_ok": self.reconciliation_ok,
            "risk_limits_ok": self.risk_limits_ok,
            "authorized_account": self.authorized_account,
            "kill_switch_clear": self.kill_switch_clear,
        }
        return tuple(name for name, passed in values.items() if not passed)


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    report_id: str
    account_id: str
    status: ReconciliationStatus
    checked_at: datetime
    differences: tuple[str, ...]
    external_events: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "checked_at", _aware(self.checked_at, "checked_at"))


def order_transition_allowed(current: OrderState, target: OrderState) -> bool:
    transitions: dict[OrderState, frozenset[OrderState]] = {
        OrderState.CREATED: frozenset({OrderState.RISK_REJECTED, OrderState.APPROVED, OrderState.FAILED}),
        OrderState.RISK_REJECTED: frozenset(),
        OrderState.APPROVED: frozenset({OrderState.SUBMITTED, OrderState.FAILED}),
        OrderState.SUBMITTED: frozenset({OrderState.ACKNOWLEDGED, OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.BROKER_REJECTED, OrderState.UNKNOWN_REQUIRES_RECONCILIATION, OrderState.FAILED}),
        OrderState.ACKNOWLEDGED: frozenset({OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCEL_PENDING, OrderState.EXPIRED, OrderState.UNKNOWN_REQUIRES_RECONCILIATION}),
        OrderState.PARTIALLY_FILLED: frozenset({OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCEL_PENDING, OrderState.UNKNOWN_REQUIRES_RECONCILIATION}),
        OrderState.FILLED: frozenset(),
        OrderState.CANCEL_PENDING: frozenset({OrderState.CANCELLED, OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.UNKNOWN_REQUIRES_RECONCILIATION}),
        OrderState.CANCELLED: frozenset(),
        OrderState.EXPIRED: frozenset(),
        OrderState.BROKER_REJECTED: frozenset(),
        OrderState.FAILED: frozenset(),
        OrderState.UNKNOWN_REQUIRES_RECONCILIATION: frozenset(),
    }
    return target in transitions[current]


def transition_order(order: BrokerOrder, target: OrderState, message: str = "") -> BrokerOrder:
    if not order_transition_allowed(order.state, target):
        raise ValueError(f"invalid order transition {order.state.value} -> {target.value}")
    return BrokerOrder(
        order_id=order.order_id,
        broker_order_id=order.broker_order_id,
        request=order.request,
        state=target,
        submitted_at=order.submitted_at,
        message=message or order.message,
    )


@dataclass(frozen=True, slots=True)
class BrokerSnapshot:
    account_id: str
    cash: Decimal
    withdrawable_cash: Decimal
    positions: Mapping[str, Decimal]
    open_order_ids: frozenset[str]
    execution_ids: frozenset[str]
    captured_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "cash", _non_negative(self.cash, "cash"))
        object.__setattr__(self, "withdrawable_cash", _non_negative(self.withdrawable_cash, "withdrawable_cash"))
        object.__setattr__(self, "captured_at", _aware(self.captured_at, "captured_at"))
