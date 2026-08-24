"""Broker/local state comparison and external-operation classification."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .config import Settings
from .controls import ControlCenter
from .domain import (
    BrokerSnapshot,
    CashMovement,
    ExecutionMode,
    Origin,
    ReconciliationReport,
    ReconciliationStatus,
    new_id,
    utc_now,
)
from .persistence import SQLiteStore


@dataclass(frozen=True, slots=True)
class ExternalOperation:
    operation_type: str
    detail: str


class ReconciliationService:
    def __init__(self, settings: Settings, controls: ControlCenter, store: SQLiteStore) -> None:
        self.settings = settings
        self.controls = controls
        self.store = store

    def reconcile(self, local: BrokerSnapshot, broker: BrokerSnapshot) -> ReconciliationReport:
        differences: list[str] = []
        if local.account_id != self.settings.bot_account_id or broker.account_id != self.settings.bot_account_id:
            differences.append("account_not_authorized")
        if local.cash != broker.cash:
            differences.append(f"cash:{local.cash}!={broker.cash}")
        if local.withdrawable_cash != broker.withdrawable_cash:
            differences.append("withdrawable_cash_mismatch")
        for instrument_id in sorted(set(local.positions) | set(broker.positions)):
            local_quantity = local.positions.get(instrument_id, Decimal("0"))
            broker_quantity = broker.positions.get(instrument_id, Decimal("0"))
            if local_quantity != broker_quantity:
                differences.append(f"position:{instrument_id}:{local_quantity}!={broker_quantity}")
        if local.open_order_ids != broker.open_order_ids:
            differences.append("open_orders_mismatch")
        if local.execution_ids != broker.execution_ids:
            differences.append("executions_mismatch")
        status = ReconciliationStatus.MATCHED if not differences else ReconciliationStatus.MISMATCH
        report = ReconciliationReport(
            report_id=new_id("recon"),
            account_id=self.settings.bot_account_id,
            status=status,
            checked_at=utc_now(),
            differences=tuple(differences),
        )
        self.store.append_event(
            event_type="RECONCILIATION_REPORT",
            account_id=self.settings.bot_account_id,
            mode=ExecutionMode.PAPER,
            origin=Origin.TRADEFORGE,
            payload={"report_id": report.report_id, "status": status.value, "differences": differences},
        )
        if status is not ReconciliationStatus.MATCHED:
            self.controls.pause("reconciliation mismatch requires review")
        return report

    def classify_cash_movement(
        self,
        previous_cash: Decimal,
        current_cash: Decimal,
        expected_cash_after_trades: Decimal,
        account_id: str,
    ) -> CashMovement | None:
        if account_id != self.settings.bot_account_id:
            raise ValueError("cash movement account is not the BOT account")
        delta = current_cash - expected_cash_after_trades
        if delta == Decimal("0"):
            return None
        movement_type = "EXTERNAL_DEPOSIT" if delta > Decimal("0") else "EXTERNAL_WITHDRAWAL"
        movement = CashMovement(
            movement_id=new_id("cash"),
            account_id=account_id,
            movement_type=movement_type,
            amount=abs(delta),
            currency="EUR",
            occurred_at=utc_now(),
            origin=Origin.BROKER,
        )
        self.store.append_event(
            event_type=movement_type,
            account_id=account_id,
            mode=ExecutionMode.PAPER,
            origin=Origin.BROKER,
            payload={"movement_id": movement.movement_id, "amount": movement.amount, "trading_pnl": False},
        )
        return movement

    def detect_external_position_change(
        self,
        expected_positions: dict[str, Decimal],
        broker_positions: dict[str, Decimal],
    ) -> ExternalOperation | None:
        if expected_positions == broker_positions:
            return None
        detail = f"expected={expected_positions};broker={broker_positions}"
        operation = ExternalOperation("EXTERNAL_MANUAL_TRADE", detail)
        self.store.append_event(
            event_type=operation.operation_type,
            account_id=self.settings.bot_account_id,
            mode=ExecutionMode.PAPER,
            origin=Origin.OWNER_MANUAL,
            payload={"detail": detail, "requires_reconciliation": True},
        )
        self.controls.pause("external manual position change requires reconciliation")
        return operation
