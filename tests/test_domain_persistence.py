import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from tradeforge.domain import (
    Decision,
    ExecutionMode,
    OrderState,
    Origin,
    ResumeChecks,
    order_transition_allowed,
    transition_order,
)
from tradeforge.persistence import SQLiteStore

from tests.support import INSTRUMENT, controls, intent, limits, now, quote, settings


class DomainAndPersistenceTests(unittest.TestCase):
    def test_ledger_is_hash_chained_and_append_only(self) -> None:
        store = SQLiteStore()
        first = store.append_event(
            "DEPOSIT",
            "BOT-001",
            ExecutionMode.PAPER,
            Origin.BROKER,
            {"amount": Decimal("100.00"), "trading_pnl": False},
        )
        second = store.append_event(
            "NOTE",
            "BOT-001",
            ExecutionMode.PAPER,
            Origin.TRADEFORGE,
            {"first": first.event_id},
        )
        self.assertEqual(second.previous_hash, first.event_hash)
        self.assertEqual(store.verify_ledger(), (True, ""))
        with self.assertRaises(sqlite3.IntegrityError):
            store.connection.execute("DELETE FROM ledger_events")
        with self.assertRaises(sqlite3.IntegrityError):
            store.connection.execute("UPDATE ledger_events SET event_type = 'TAMPERED'")
        store.close()

    def test_control_state_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tradeforge.db"
            store = SQLiteStore(path)
            center = controls(store)
            center.stop_everything("test stop")
            store.close()
            reopened = SQLiteStore(path)
            self.assertEqual(reopened.load_control().state.value, "KILL_SWITCH_ACTIVE")
            self.assertEqual(reopened.load_control().reason, "test stop")
            reopened.close()

    def test_resume_requires_every_check(self) -> None:
        store = SQLiteStore()
        center = controls(store)
        center.pause("test")
        checks = ResumeChecks(True, True, True, True, True, False, True, True, True)
        with self.assertRaises(Exception) as context:
            center.resume(checks)
        self.assertIn("reconciliation_ok", str(context.exception))

    def test_order_state_machine_rejects_invalid_transition(self) -> None:
        self.assertTrue(order_transition_allowed(OrderState.SUBMITTED, OrderState.FILLED))
        self.assertFalse(order_transition_allowed(OrderState.FILLED, OrderState.SUBMITTED))

    def test_decimal_and_timezone_invariants_are_enforced(self) -> None:
        with self.assertRaises(ValueError):
            quote().__class__("AAPL", Decimal("1"), Decimal("2"), datetime.now(), "test")
        with self.assertRaises(ValueError):
            INSTRUMENT.__class__("BAD", "not-isin", "BAD", "XNAS")


if __name__ == "__main__":
    unittest.main()
