"""Broker-neutral interface and realistic in-memory paper execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from typing import Mapping, Protocol

from .domain import (
    BrokerOrder,
    BrokerSnapshot,
    Execution,
    ExecutionMode,
    Instrument,
    OrderRequest,
    OrderState,
    Position,
    Quote,
    Side,
    new_id,
    transition_order,
    utc_now,
)


class BrokerError(RuntimeError):
    pass


class DuplicateOrder(BrokerError):
    pass


class BrokerSubmissionUncertain(BrokerError):
    """The caller must reconcile; it must not retry."""


@dataclass(frozen=True, slots=True)
class BrokerCapabilities:
    supports_fractional: bool
    supports_market_orders: bool
    supports_limit_orders: bool
    supports_streaming: bool
    supports_paper: bool
    supports_fx: bool
    supports_tax_reports: bool
    supports_official_api: bool
    supports_withdrawals: bool = False


@dataclass(frozen=True, slots=True)
class BrokerSubmission:
    order: BrokerOrder
    executions: tuple[Execution, ...]


class BrokerInterface(Protocol):
    """Only the execution service may depend on this interface."""

    @property
    def capabilities(self) -> BrokerCapabilities: ...

    def submit_order(self, request: OrderRequest, quote: Quote | None = None) -> BrokerSubmission: ...

    def cancel_order(self, broker_order_id: str) -> BrokerOrder: ...

    def snapshot(self) -> BrokerSnapshot: ...

    def orders(self) -> tuple[BrokerOrder, ...]: ...


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    slippage_bps: Decimal = Decimal("5")
    commission_bps: Decimal = Decimal("10")
    fixed_fee: Decimal = Decimal("0")
    fill_ratio: Decimal = Decimal("1")
    latency_ms: int = 50
    market_open_hour_utc: int = 7
    market_close_hour_utc: int = 21

    def __post_init__(self) -> None:
        for name in ("slippage_bps", "commission_bps", "fixed_fee"):
            if getattr(self, name) < Decimal("0"):
                raise ValueError(f"{name} cannot be negative")
        if not Decimal("0") < self.fill_ratio <= Decimal("1"):
            raise ValueError("fill_ratio must be in (0, 1]")
        if self.latency_ms < 0:
            raise ValueError("latency_ms cannot be negative")
        if not 0 <= self.market_open_hour_utc < self.market_close_hour_utc <= 24:
            raise ValueError("unsupported market hours")


class PaperBroker:
    """Deterministic paper broker with spread, slippage, fees and partial fills."""

    def __init__(
        self,
        account_id: str,
        initial_cash: Decimal,
        instruments: Mapping[str, Instrument],
        quotes: Mapping[str, Quote],
        config: SimulationConfig | None = None,
    ) -> None:
        if not account_id.strip():
            raise ValueError("paper broker account_id is required")
        if initial_cash < Decimal("0"):
            raise ValueError("initial_cash cannot be negative")
        self.account_id = account_id
        self._cash = initial_cash
        self._instruments = dict(instruments)
        self._quotes = dict(quotes)
        self._config = config or SimulationConfig()
        self._orders: dict[str, BrokerOrder] = {}
        self._executions: dict[str, Execution] = {}
        self._idempotency: dict[str, str] = {}
        self._positions: dict[str, Position] = {}

    @property
    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            supports_fractional=any(
                instrument.quantity_increment < Decimal("1")
                for instrument in self._instruments.values()
            ),
            supports_market_orders=True,
            supports_limit_orders=True,
            supports_streaming=False,
            supports_paper=True,
            supports_fx=False,
            supports_tax_reports=False,
            supports_official_api=False,
            supports_withdrawals=False,
        )

    def set_quote(self, quote: Quote) -> None:
        self._quotes[quote.instrument_id] = quote

    @property
    def simulation_config(self) -> SimulationConfig:
        return self._config

    def set_fill_ratio(self, fill_ratio: Decimal) -> None:
        """Development-only failure injection for partial-fill scenarios."""
        self._config = SimulationConfig(
            slippage_bps=self._config.slippage_bps,
            commission_bps=self._config.commission_bps,
            fixed_fee=self._config.fixed_fee,
            fill_ratio=fill_ratio,
            latency_ms=self._config.latency_ms,
            market_open_hour_utc=self._config.market_open_hour_utc,
            market_close_hour_utc=self._config.market_close_hour_utc,
        )

    def submit_order(self, request: OrderRequest, quote: Quote | None = None) -> BrokerSubmission:
        if request.account_id != self.account_id:
            raise BrokerError("paper broker account mismatch")
        if request.mode is ExecutionMode.LIVE:
            raise BrokerError("PaperBroker cannot accept LIVE requests")
        if request.idempotency_key in self._idempotency:
            raise DuplicateOrder(request.idempotency_key)
        instrument = self._instruments.get(request.instrument_id)
        if instrument is None or not instrument.tradable:
            return self._rejected(request, "instrument unavailable")
        quote = quote or self._quotes.get(request.instrument_id)
        if quote is None:
            return self._rejected(request, "quote unavailable")
        if request.order_type.value == "LIMIT" and not self._limit_marketable(request, quote):
            order = self._new_order(request, OrderState.ACKNOWLEDGED, "limit not marketable")
            self._remember(order)
            self._idempotency[request.idempotency_key] = order.broker_order_id
            return BrokerSubmission(order, ())

        quantity = self._filled_quantity(request.quantity, instrument.quantity_increment)
        if quantity <= Decimal("0"):
            return self._rejected(request, "quantity below instrument minimum")
        price = self._execution_price(request.side, quote)
        gross = quantity * price
        commission = gross * self._config.commission_bps / Decimal("10000")
        fees = commission + self._config.fixed_fee
        if request.side is Side.BUY and self._cash < gross + fees:
            return self._rejected(request, "insufficient paper cash")
        current = self._positions.get(request.instrument_id)
        if request.side is Side.SELL and (current is None or current.quantity < quantity):
            return self._rejected(request, "insufficient paper position")

        now = utc_now()
        order = self._new_order(request, OrderState.SUBMITTED, "paper order submitted", now)
        execution = Execution(
            execution_id=new_id("exec"),
            broker_order_id=order.broker_order_id,
            instrument_id=request.instrument_id,
            side=request.side,
            quantity=quantity,
            price=price,
            commission=commission,
            fees=fees,
            currency=instrument.currency,
            executed_at=now,
        )
        final_state = OrderState.FILLED if quantity == request.quantity else OrderState.PARTIALLY_FILLED
        order = transition_order(order, final_state, "paper fill")
        self._remember(order)
        self._executions[execution.execution_id] = execution
        self._idempotency[request.idempotency_key] = order.broker_order_id
        self._apply_execution(execution)
        return BrokerSubmission(order, (execution,))

    def cancel_order(self, broker_order_id: str) -> BrokerOrder:
        order = self._find_order(broker_order_id)
        if order.state in {OrderState.FILLED, OrderState.CANCELLED, OrderState.BROKER_REJECTED}:
            return order
        if order.state is OrderState.UNKNOWN_REQUIRES_RECONCILIATION:
            raise BrokerError("unknown order cannot be cancelled before reconciliation")
        if order.state is not OrderState.CANCEL_PENDING:
            order = transition_order(order, OrderState.CANCEL_PENDING, "cancel requested")
        order = transition_order(order, OrderState.CANCELLED, "paper order cancelled")
        self._orders[order.broker_order_id] = order
        return order

    def snapshot(self) -> BrokerSnapshot:
        return BrokerSnapshot(
            account_id=self.account_id,
            cash=self._cash,
            withdrawable_cash=self._cash,
            positions={instrument_id: position.quantity for instrument_id, position in self._positions.items() if position.quantity > Decimal("0")},
            open_order_ids=frozenset(
                broker_id
                for broker_id, order in self._orders.items()
                if order.state in {OrderState.SUBMITTED, OrderState.ACKNOWLEDGED, OrderState.PARTIALLY_FILLED, OrderState.CANCEL_PENDING}
            ),
            execution_ids=frozenset(self._executions),
            captured_at=utc_now(),
        )

    def orders(self) -> tuple[BrokerOrder, ...]:
        return tuple(self._orders.values())

    def executions(self) -> tuple[Execution, ...]:
        return tuple(self._executions.values())

    def positions(self) -> tuple[Position, ...]:
        """Return positions marked to the latest paper quote."""
        marked: list[Position] = []
        for instrument_id, position in self._positions.items():
            if position.quantity <= Decimal("0"):
                continue
            quote = self._quotes.get(instrument_id)
            price = quote.midpoint if quote else position.market_price
            marked.append(
                Position(
                    instrument_id=position.instrument_id,
                    quantity=position.quantity,
                    average_entry=position.average_entry,
                    market_price=price,
                    strategy_id=position.strategy_id,
                )
            )
        return tuple(marked)

    def apply_cash_movement(self, amount: Decimal, increase: bool) -> None:
        """Apply an owner-controlled simulated deposit or withdrawal."""
        if amount <= Decimal("0"):
            raise ValueError("cash movement amount must be positive")
        if not increase and amount > self._cash:
            raise BrokerError("paper withdrawal exceeds available cash")
        self._cash = self._cash + amount if increase else self._cash - amount

    def _filled_quantity(self, quantity: Decimal, increment: Decimal) -> Decimal:
        partial = quantity * self._config.fill_ratio
        return (partial / increment).to_integral_value(rounding=ROUND_DOWN) * increment

    def _execution_price(self, side: Side, quote: Quote) -> Decimal:
        multiplier = Decimal("1") + self._config.slippage_bps / Decimal("10000")
        if side is Side.BUY:
            return quote.ask * multiplier
        return quote.bid / multiplier

    @staticmethod
    def _limit_marketable(request: OrderRequest, quote: Quote) -> bool:
        if request.limit_price is None:
            return False
        return request.limit_price >= quote.ask if request.side is Side.BUY else request.limit_price <= quote.bid

    def _new_order(self, request: OrderRequest, state: OrderState, message: str, submitted_at: datetime | None = None) -> BrokerOrder:
        return BrokerOrder(
            order_id=request.order_id,
            broker_order_id=new_id("paper_order"),
            request=request,
            state=state,
            submitted_at=submitted_at or utc_now(),
            message=message,
        )

    def _remember(self, order: BrokerOrder) -> None:
        self._orders[order.broker_order_id] = order

    def _find_order(self, broker_order_id: str) -> BrokerOrder:
        try:
            return self._orders[broker_order_id]
        except KeyError as exc:
            raise BrokerError("broker order not found") from exc

    def _rejected(self, request: OrderRequest, message: str) -> BrokerSubmission:
        order = self._new_order(request, OrderState.BROKER_REJECTED, message)
        self._remember(order)
        self._idempotency[request.idempotency_key] = order.broker_order_id
        return BrokerSubmission(order, ())

    def _apply_execution(self, execution: Execution) -> None:
        total = execution.gross_amount + execution.fees
        current = self._positions.get(execution.instrument_id)
        if execution.side is Side.BUY:
            self._cash -= total
            if current is None:
                self._positions[execution.instrument_id] = Position(
                    instrument_id=execution.instrument_id,
                    quantity=execution.quantity,
                    average_entry=execution.price,
                    market_price=execution.price,
                )
            else:
                quantity = current.quantity + execution.quantity
                average = (current.cost_basis + execution.gross_amount) / quantity
                self._positions[execution.instrument_id] = Position(
                    instrument_id=execution.instrument_id,
                    quantity=quantity,
                    average_entry=average,
                    market_price=execution.price,
                    strategy_id=current.strategy_id,
                )
        else:
            if current is None or current.quantity < execution.quantity:
                raise BrokerError("paper position invariant violated")
            self._cash += execution.gross_amount - execution.fees
            quantity = current.quantity - execution.quantity
            self._positions[execution.instrument_id] = Position(
                instrument_id=execution.instrument_id,
                quantity=quantity,
                average_entry=current.average_entry if quantity else Decimal("0"),
                market_price=execution.price,
                strategy_id=current.strategy_id,
            )


class MyInvestorAdapterPlaceholder:
    """Non-executable marker for an explicitly unsupported integration."""

    execution_supported = False

    @property
    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(False, False, False, False, False, False, False, False, False)

    def submit_order(self, request: OrderRequest, quote: Quote | None = None) -> BrokerSubmission:
        raise BrokerError("MyInvestor live execution is permanently disabled")

    def cancel_order(self, broker_order_id: str) -> BrokerOrder:
        raise BrokerError("MyInvestor live execution is permanently disabled")

    def snapshot(self) -> BrokerSnapshot:
        raise BrokerError("MyInvestor integration is read-disabled")

    def orders(self) -> tuple[BrokerOrder, ...]:
        raise BrokerError("MyInvestor integration is read-disabled")


class XtbAdapterPlaceholder(MyInvestorAdapterPlaceholder):
    """Non-executable placeholder pending a separate official-API review."""
