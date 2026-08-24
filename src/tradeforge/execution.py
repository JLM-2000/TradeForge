"""Execution service: the final independent enforcement boundary."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .broker import BrokerError, BrokerInterface, BrokerSubmission, BrokerSubmissionUncertain
from .controls import ControlCenter
from .domain import (
    Decision,
    ExecutionMode,
    IntentKind,
    OrderRequest,
    OrderType,
    Quote,
    RiskDecision,
    RiskSnapshot,
    Side,
    TradeIntent,
    new_id,
)
from .persistence import SQLiteStore
from .risk import RiskEngine


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    risk_decision: RiskDecision
    submission: BrokerSubmission | None


class ExecutionService:
    """No strategy or model reference is accepted by this service."""

    def __init__(self, risk_engine: RiskEngine, broker: BrokerInterface, controls: ControlCenter, store: SQLiteStore) -> None:
        self.risk_engine = risk_engine
        self.broker = broker
        self.controls = controls
        self.store = store

    def submit_intent(self, intent: TradeIntent, quote: Quote, snapshot: RiskSnapshot) -> ExecutionResult:
        risk_decision = self.risk_engine.evaluate(intent, quote, snapshot)
        self.store.append_event(
            event_type="RISK_DECISION",
            account_id=intent.account_id,
            mode=intent.mode,
            origin=self._origin(),
            payload={
                "intent_id": intent.intent_id,
                "decision": risk_decision.decision.value,
                "approved_notional": risk_decision.approved_notional,
                "reasons": risk_decision.reasons,
                "checks": dict(risk_decision.checks),
            },
        )
        if risk_decision.decision is Decision.REJECT:
            return ExecutionResult(risk_decision, None)

        # The execution gate is intentionally repeated below RiskEngine.
        gate = self.controls.execution_gate(intent.account_id, intent.kind is IntentKind.ENTRY)
        if not gate.allowed:
            denied = self._execution_denial(risk_decision, gate.reason)
            return ExecutionResult(denied, None)
        if intent.mode is ExecutionMode.LIVE:
            denied = self._execution_denial(risk_decision, "LIVE_EXECUTION_DENIED_AT_EXECUTION_BOUNDARY")
            return ExecutionResult(denied, None)
        if self.store.has_idempotency_key(intent.idempotency_key):
            denied = self._execution_denial(risk_decision, "DUPLICATE_IDEMPOTENCY_KEY")
            return ExecutionResult(denied, None)

        instrument = self.risk_engine.instruments[intent.instrument_id]
        price = quote.ask if intent.side is Side.BUY else quote.bid
        quantity = self.risk_engine.quantity_for_notional(
            risk_decision.approved_notional,
            price,
            instrument.quantity_increment,
        )
        if quantity <= Decimal("0"):
            denied = self._execution_denial(risk_decision, "ORDER_REJECTED_MINIMUM_SIZE")
            return ExecutionResult(denied, None)
        request = OrderRequest(
            order_id=new_id("order"),
            intent_id=intent.intent_id,
            account_id=intent.account_id,
            instrument_id=intent.instrument_id,
            side=intent.side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            limit_price=None,
            idempotency_key=intent.idempotency_key,
            mode=intent.mode,
            reduces_position=intent.kind is IntentKind.EXIT,
        )
        self.store.remember_idempotency_key(
            intent.idempotency_key,
            intent.intent_id,
            intent.account_id,
            intent.instrument_id,
            {"order_id": request.order_id, "quantity": quantity, "side": intent.side.value},
        )
        self.store.append_event(
            event_type="ORDER_APPROVED",
            account_id=request.account_id,
            mode=request.mode,
            origin=self._origin(),
            payload={"order_id": request.order_id, "intent_id": request.intent_id, "quantity": quantity},
        )
        try:
            submission = self.broker.submit_order(request, quote)
        except BrokerSubmissionUncertain:
            self.store.append_event(
                event_type="ORDER_UNKNOWN_REQUIRES_RECONCILIATION",
                account_id=request.account_id,
                mode=request.mode,
                origin=self._origin(),
                payload={"order_id": request.order_id, "idempotency_key": request.idempotency_key},
            )
            self.controls.pause("broker submission outcome unknown; reconciliation required")
            raise
        except BrokerError as exc:
            self.store.append_event(
                event_type="BROKER_ORDER_REJECTED",
                account_id=request.account_id,
                mode=request.mode,
                origin=self._origin(),
                payload={"order_id": request.order_id, "message": str(exc)},
            )
            return ExecutionResult(risk_decision, None)

        self.store.append_event(
            event_type="BROKER_ORDER_STATE",
            account_id=request.account_id,
            mode=request.mode,
            origin=self._origin(),
            payload={
                "order_id": request.order_id,
                "broker_order_id": submission.order.broker_order_id,
                "state": submission.order.state.value,
            },
        )
        for execution in submission.executions:
            self.store.append_event(
                event_type="EXECUTION",
                account_id=request.account_id,
                mode=request.mode,
                origin=self._origin(),
                payload={
                    "execution_id": execution.execution_id,
                    "broker_order_id": execution.broker_order_id,
                    "instrument_id": execution.instrument_id,
                    "quantity": execution.quantity,
                    "price": execution.price,
                    "commission": execution.commission,
                    "fees": execution.fees,
                },
            )
        return ExecutionResult(risk_decision, submission)

    @staticmethod
    def _execution_denial(decision: RiskDecision, reason: str) -> RiskDecision:
        return RiskDecision(
            intent_id=decision.intent_id,
            decision=Decision.REJECT,
            approved_notional=Decimal("0"),
            reasons=tuple(dict.fromkeys((*decision.reasons, reason))),
            checks={**dict(decision.checks), "execution_boundary": False},
            created_at=decision.created_at,
            risk_config_version=decision.risk_config_version,
        )

    @staticmethod
    def _origin():
        from .domain import Origin

        return Origin.TRADEFORGE
