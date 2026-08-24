import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tradeforge.domain import BrokerSnapshot, ReconciliationStatus
from tradeforge.persistence import SQLiteStore
from tradeforge.reconciliation import ReconciliationService
from tradeforge.tax import TaxLotEngine, TaxReserveConfig, TaxReserveEstimator
from tradeforge.withdrawals import WithdrawalPlanner

from tests.support import controls, settings


class TaxTests(unittest.TestCase):
    def test_acquisition_and_disposal_fees_adjust_realized_result(self) -> None:
        engine = TaxLotEngine()
        acquired = datetime(2024, 1, 1, tzinfo=UTC)
        disposed = datetime(2024, 6, 1, tzinfo=UTC)
        engine.record_buy("BOT-001", "US0378331005", "AAPL", Decimal("1"), Decimal("5"), Decimal("1"), acquired, "buy")
        result = engine.record_sell("BOT-001", "US0378331005", "AAPL", Decimal("1"), Decimal("8"), Decimal("0"), disposed, "sell")[0]
        self.assertEqual(result.realized_result_eur, Decimal("2"))

        second = TaxLotEngine()
        second.record_buy("BOT-001", "US0378331005", "AAPL", Decimal("1"), Decimal("5"), Decimal("1"), acquired, "buy")
        result_with_sale_fee = second.record_sell("BOT-001", "US0378331005", "AAPL", Decimal("1"), Decimal("8"), Decimal("1"), disposed, "sell")[0]
        self.assertEqual(result_with_sale_fee.realized_result_eur, Decimal("1"))

    def test_fifo_consumes_oldest_lot_first_and_preserves_remaining_fee_basis(self) -> None:
        engine = TaxLotEngine()
        first = datetime(2023, 1, 1, tzinfo=UTC)
        second = datetime(2023, 2, 1, tzinfo=UTC)
        sale = datetime(2024, 1, 1, tzinfo=UTC)
        engine.record_buy("BOT-001", "US0378331005", "AAPL", Decimal("1"), Decimal("5"), Decimal("1"), first, "buy-1")
        engine.record_buy("BOT-001", "US0378331005", "AAPL", Decimal("1"), Decimal("7"), Decimal("1"), second, "buy-2")
        disposal = engine.record_sell("BOT-001", "US0378331005", "AAPL", Decimal("1"), Decimal("8"), Decimal("0"), sale, "sell")[0]
        self.assertEqual(disposal.cost_basis_eur, Decimal("6"))
        remaining = engine.lots("US0378331005")
        self.assertEqual(len(remaining), 2)
        self.assertEqual(remaining[0].remaining_quantity, Decimal("0"))
        self.assertEqual(remaining[1].fees_eur, Decimal("1"))

    def test_tax_reserve_excludes_unrealized_pnl(self) -> None:
        estimate = TaxReserveEstimator(TaxReserveConfig(2024, Decimal("0.20"))).estimate(
            Decimal("500"), unrealized_pnl_eur=Decimal("75")
        )
        self.assertEqual(estimate.reserve_eur, Decimal("100.00"))
        self.assertEqual(estimate.unrealized_excluded_eur, Decimal("75"))
        self.assertIn("ESTIMATE", estimate.label)


class ReconciliationAndWithdrawalTests(unittest.TestCase):
    def test_mismatch_pauses_and_cash_withdrawal_is_not_trading_loss(self) -> None:
        store = SQLiteStore()
        center = controls(store)
        service = ReconciliationService(settings(), center, store)
        matched = BrokerSnapshot("BOT-001", Decimal("100"), Decimal("100"), {}, frozenset(), frozenset(), datetime.now(UTC))
        mismatch = BrokerSnapshot("BOT-001", Decimal("90"), Decimal("90"), {}, frozenset(), frozenset(), datetime.now(UTC))
        report = service.reconcile(matched, mismatch)
        self.assertEqual(report.status, ReconciliationStatus.MISMATCH)
        self.assertEqual(center.record.state.value, "PAUSED")
        movement = service.classify_cash_movement(Decimal("100"), Decimal("90"), Decimal("100"), "BOT-001")
        self.assertIsNotNone(movement)
        assert movement is not None
        self.assertEqual(movement.movement_type, "EXTERNAL_WITHDRAWAL")
        self.assertEqual(movement.amount, Decimal("10"))
        self.assertEqual(store.events()[-1].payload["trading_pnl"], False)

    def test_withdrawal_planner_is_informational_only(self) -> None:
        plan = WithdrawalPlanner().plan(
            total_equity_eur=Decimal("125"),
            net_contributed_capital_eur=Decimal("100"),
            realized_pnl_eur=Decimal("18"),
            unrealized_pnl_eur=Decimal("7"),
            available_cash_eur=Decimal("34"),
            broker_withdrawable_cash_eur=Decimal("34"),
            estimated_tax_reserve_eur=Decimal("5"),
            owner_target_capital_eur=Decimal("100"),
        )
        self.assertEqual(plan.potential_withdrawal_eur, Decimal("25"))
        self.assertTrue(plan.informational_only)
        self.assertEqual(WithdrawalPlanner.open_broker_to_withdraw(), "OPEN_BROKER_TO_WITHDRAW")
        self.assertFalse(hasattr(WithdrawalPlanner, "withdraw"))


if __name__ == "__main__":
    unittest.main()
