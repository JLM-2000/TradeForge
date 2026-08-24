import tempfile
import unittest
from decimal import Decimal

from tradeforge.broker import BrokerSubmissionUncertain, PaperBroker, SimulationConfig
from tradeforge.config import Settings
from tradeforge.controls import ControlCenter
from tradeforge.domain import (
    Decision,
    ExecutionMode,
    IntentKind,
    RiskConfiguration,
    RiskSnapshot,
    Side,
    SizingPolicy,
)
from tradeforge.execution import ExecutionService
from tradeforge.persistence import SQLiteStore
from tradeforge.risk import RiskEngine

from tests.support import INSTRUMENT, engine, intent, limits, quote, settings, snapshot


class RiskTests(unittest.TestCase):
    def test_approved_intent_is_bounded_by_owner_position_ceiling(self) -> None:
        store = SQLiteStore()
        risk = engine(store)
        decision = risk.evaluate(intent(desired_notional=Decimal("20")), quote(), snapshot())
        self.assertEqual(decision.decision, Decision.RESIZE)
        self.assertEqual(decision.approved_notional, Decimal("5"))

    def test_auto_mode_never_increases_owner_ceiling(self) -> None:
        store = SQLiteStore()
        risk = engine(store, RiskConfiguration(mode=__import__("tradeforge.domain", fromlist=["RiskMode"]).RiskMode.AUTO, auto_min_position_eur=Decimal("1")))
        decision = risk.evaluate(intent(desired_notional=Decimal("50")), quote(), snapshot())
        self.assertLessEqual(decision.approved_notional, limits().max_position_eur)

    def test_unauthorized_account_is_rejected(self) -> None:
        store = SQLiteStore()
        decision = engine(store).evaluate(intent(account_id="MYINVESTOR-001"), quote(), snapshot())
        self.assertEqual(decision.decision, Decision.REJECT)
        self.assertIn("UNAUTHORIZED_ACCOUNT", decision.reasons)
        self.assertIn("PERSONAL_INVESTMENT_ACCOUNT_DENIED", decision.reasons)

    def test_stale_quote_is_rejected(self) -> None:
        store = SQLiteStore()
        decision = engine(store).evaluate(intent(), quote(age_seconds=6), snapshot())
        self.assertEqual(decision.decision, Decision.REJECT)
        self.assertIn("STALE_OR_FUTURE_QUOTE", decision.reasons)

    def test_loss_limit_is_rejected(self) -> None:
        store = SQLiteStore()
        decision = engine(store).evaluate(
            intent(), quote(), snapshot(realized_pnl_today=Decimal("-2"))
        )
        self.assertEqual(decision.decision, Decision.REJECT)
        self.assertIn("DAILY_LOSS_LIMIT", decision.reasons)

    def test_unbounded_sizing_policy_is_rejected(self) -> None:
        store = SQLiteStore()
        decision = engine(store).evaluate(
            intent(sizing_policy=SizingPolicy.MARTINGALE), quote(), snapshot()
        )
        self.assertEqual(decision.decision, Decision.REJECT)
        self.assertIn("UNCONTROLLED_SIZING_POLICY", decision.reasons)

    def test_live_mode_is_denied_even_when_requested(self) -> None:
        store = SQLiteStore()
        runtime_settings = settings(ExecutionMode.LIVE)
        risk = RiskEngine(
            runtime_settings,
            limits(),
            RiskConfiguration(),
            {INSTRUMENT.instrument_id: INSTRUMENT},
            ControlCenter(store, runtime_settings),
        )
        decision = risk.evaluate(intent(mode=ExecutionMode.LIVE), quote(), snapshot())
        self.assertEqual(decision.decision, Decision.REJECT)
        self.assertIn("LIVE_EXECUTION_DENIED", decision.reasons)

    def test_initial_build_cannot_enable_live_by_configuration_alone(self) -> None:
        configured = Settings(
            mode=ExecutionMode.LIVE,
            bot_account_id="BOT-001",
            allowed_instrument_ids=frozenset({INSTRUMENT.instrument_id}),
            live_trading_enabled=True,
            live_readiness_approved=True,
            bot_account_validated=True,
            safety_suite_passing=True,
        )
        self.assertFalse(configured.live_execution_allowed)


class ExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SQLiteStore()
        self.runtime_settings = settings()
        self.controls = ControlCenter(self.store, self.runtime_settings)
        self.risk = engine(self.store)
        self.broker = PaperBroker(
            account_id="BOT-001",
            initial_cash=Decimal("100"),
            instruments={INSTRUMENT.instrument_id: INSTRUMENT},
            quotes={INSTRUMENT.instrument_id: quote()},
            config=SimulationConfig(slippage_bps=Decimal("0"), commission_bps=Decimal("0")),
        )
        self.service = ExecutionService(self.risk, self.broker, self.controls, self.store)

    def tearDown(self) -> None:
        self.store.close()

    def test_paper_buy_creates_fill_and_decreases_cash(self) -> None:
        result = self.service.submit_intent(intent(), quote(), snapshot())
        self.assertIsNotNone(result.submission)
        assert result.submission is not None
        self.assertEqual(result.submission.order.state.value, "FILLED")
        self.assertEqual(result.submission.executions[0].price, Decimal("100.00"))
        self.assertEqual(self.broker.snapshot().cash, Decimal("95"))

    def test_pause_blocks_new_entry(self) -> None:
        self.controls.pause("operator pause")
        result = self.service.submit_intent(intent(), quote(), snapshot())
        self.assertEqual(result.risk_decision.decision, Decision.REJECT)
        self.assertIn("TRADING_PAUSED", result.risk_decision.reasons)
        self.assertEqual(self.broker.snapshot().execution_ids, frozenset())

    def test_stop_everything_blocks_and_does_not_liquidate(self) -> None:
        bought = self.service.submit_intent(intent(key="buy-key"), quote(), snapshot())
        self.assertIsNotNone(bought.submission)
        before = self.broker.snapshot()
        self.controls.stop_everything("emergency test")
        result = self.service.submit_intent(
            intent(key="sell-key", kind=IntentKind.EXIT, side=Side.SELL),
            quote(),
            snapshot(current_exposure=Decimal("5"), current_position_notional=Decimal("5"), open_positions=1),
        )
        self.assertEqual(result.risk_decision.decision, Decision.REJECT)
        self.assertIn("KILL_SWITCH_ACTIVE", result.risk_decision.reasons)
        self.assertEqual(self.broker.snapshot().positions, before.positions)

    def test_duplicate_intent_cannot_submit_twice(self) -> None:
        first = self.service.submit_intent(intent(), quote(), snapshot())
        second = self.service.submit_intent(intent(), quote(), snapshot())
        self.assertIsNotNone(first.submission)
        self.assertEqual(second.risk_decision.decision, Decision.REJECT)
        self.assertIn("DUPLICATE_IDEMPOTENCY_KEY", second.risk_decision.reasons)
        self.assertEqual(len(self.broker.executions()), 1)

    def test_uncertain_submission_pauses_without_retry(self) -> None:
        class UncertainPaperBroker(PaperBroker):
            def submit_order(self, request, quote=None):
                raise BrokerSubmissionUncertain("simulated timeout")

        uncertain = UncertainPaperBroker(
            account_id="BOT-001",
            initial_cash=Decimal("100"),
            instruments={INSTRUMENT.instrument_id: INSTRUMENT},
            quotes={INSTRUMENT.instrument_id: quote()},
            config=SimulationConfig(slippage_bps=Decimal("0"), commission_bps=Decimal("0")),
        )
        service = ExecutionService(self.risk, uncertain, self.controls, self.store)
        with self.assertRaises(BrokerSubmissionUncertain):
            service.submit_intent(intent(), quote(), snapshot())
        self.assertEqual(self.controls.record.state.value, "PAUSED")
        self.assertEqual(len(uncertain.executions()), 0)
        self.assertEqual(self.store.events()[-2].event_type, "ORDER_UNKNOWN_REQUIRES_RECONCILIATION")


if __name__ == "__main__":
    unittest.main()
