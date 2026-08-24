"""Persisted pause, resume, and emergency-stop controls."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .domain import ControlRecord, ControlState, ExecutionMode, Origin, ResumeChecks, utc_now
from .persistence import SQLiteStore


class ControlError(RuntimeError):
    """Base class for unsafe control transitions."""


class ResumeDenied(ControlError):
    def __init__(self, failures: tuple[str, ...]):
        self.failures = failures
        super().__init__(f"resume denied: {', '.join(failures)}")


class OwnerAuthenticationRequired(ControlError):
    pass


@dataclass(frozen=True, slots=True)
class ExecutionGateResult:
    allowed: bool
    reason: str


class ControlCenter:
    """The command-side control state machine.

    The execution service must call ``execution_gate`` independently rather
    than trusting a UI state. Kill-switch state is stored before the command
    returns and is therefore restart durable.
    """

    def __init__(self, store: SQLiteStore, settings: Settings) -> None:
        self.store = store
        self.settings = settings

    @property
    def record(self) -> ControlRecord:
        return self.store.load_control()

    def pause(self, reason: str, cancel_pending_on_pause: bool | None = None) -> ControlRecord:
        current = self.record
        if current.state is ControlState.KILL_SWITCH_ACTIVE:
            return current
        record = ControlRecord(
            state=ControlState.PAUSED,
            reason=reason.strip() or "manual pause",
            activated_at=current.activated_at,
            cancel_pending_on_pause=(
                current.cancel_pending_on_pause
                if cancel_pending_on_pause is None
                else cancel_pending_on_pause
            ),
        )
        self.store.save_control(record)
        self._event("TRADING_PAUSED", {"reason": record.reason})
        return record

    def resume(self, checks: ResumeChecks) -> ControlRecord:
        current = self.record
        failures = list(checks.failures())
        if current.state is ControlState.KILL_SWITCH_ACTIVE:
            failures.append("kill_switch_active")
        if failures:
            raise ResumeDenied(tuple(dict.fromkeys(failures)))
        record = ControlRecord(state=ControlState.RUNNING, cancel_pending_on_pause=current.cancel_pending_on_pause)
        self.store.save_control(record)
        self._event("TRADING_RESUMED", {})
        return record

    def stop_everything(self, reason: str) -> ControlRecord:
        current = self.record
        if current.state is ControlState.KILL_SWITCH_ACTIVE:
            return current
        record = ControlRecord(
            state=ControlState.KILL_SWITCH_ACTIVE,
            reason=reason.strip() or "manual emergency stop",
            activated_at=utc_now(),
            cancel_pending_on_pause=current.cancel_pending_on_pause,
        )
        self.store.save_control(record)
        self._event("KILL_SWITCH_ACTIVATED", {"reason": record.reason, "liquidation": False})
        self._event("SECURITY_KILL_SWITCH", {"reason": record.reason})
        return record

    def reset_kill_switch(self, checks: ResumeChecks, owner_authenticated: bool) -> ControlRecord:
        if not owner_authenticated:
            raise OwnerAuthenticationRequired("owner authentication is required to reset kill switch")
        current = self.record
        if current.state is not ControlState.KILL_SWITCH_ACTIVE:
            return current
        failures = list(checks.failures())
        # A reset is deliberately not a resume. It leaves the system paused.
        if failures:
            raise ResumeDenied(tuple(dict.fromkeys(failures)))
        record = ControlRecord(
            state=ControlState.PAUSED,
            reason="kill switch reset; explicit resume required",
            cancel_pending_on_pause=current.cancel_pending_on_pause,
        )
        self.store.save_control(record)
        self._event("KILL_SWITCH_RESET", {"owner_authenticated": True})
        return record

    def execution_gate(self, account_id: str, is_entry: bool) -> ExecutionGateResult:
        current = self.record
        if account_id != self.settings.bot_account_id:
            self._event("UNAUTHORIZED_ACCOUNT_ORDER_ATTEMPT", {"requested_account_id": account_id})
            return ExecutionGateResult(False, "account_not_authorized")
        if account_id in self.settings.personal_investment_account_ids:
            self._event("PERSONAL_ACCOUNT_ORDER_ATTEMPT", {"requested_account_id": account_id})
            return ExecutionGateResult(False, "personal_investment_account_denied")
        if current.state is ControlState.KILL_SWITCH_ACTIVE:
            return ExecutionGateResult(False, "kill_switch_active")
        if current.state is ControlState.PAUSED and is_entry:
            return ExecutionGateResult(False, "trading_paused")
        return ExecutionGateResult(True, "allowed")

    def _event(self, event_type: str, payload: dict[str, object]) -> None:
        self.store.append_event(
            event_type=event_type,
            account_id=self.settings.bot_account_id,
            mode=ExecutionMode.PAPER,
            origin=Origin.TRADEFORGE,
            payload=payload,
        )
