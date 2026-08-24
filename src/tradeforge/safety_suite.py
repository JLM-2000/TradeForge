"""Machine-readable acceptance probes for the capital-safety invariants."""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Callable

from .broker import PaperBroker, SimulationConfig
from .config import Settings
from .controls import ControlCenter
from .domain import Decision, ExecutionMode, IntentKind, ResumeChecks, RiskConfiguration, Side
from .execution import ExecutionService
from .persistence import SQLiteStore
from .risk import RiskEngine
from .tax import TaxLotEngine
from .withdrawals import WithdrawalPlanner


def _fixtures(store: SQLiteStore):
    isin = "US0378331005"
    from .domain import AssetClass, Instrument, Quote, RiskSnapshot, OwnerHardLimits, TradeIntent, SizingPolicy

    instrument = Instrument("AAPL", isin, "AAPL", "XNAS", asset_class=AssetClass.STOCK, quantity_increment=Decimal("0.01"))
    settings = Settings(
        mode=ExecutionMode.PAPER,
        bot_account_id="BOT-001",
        personal_investment_account_ids=frozenset({"MYINVESTOR-001"}),
        allowed_instrument_ids=frozenset({"AAPL"}),
    )
    limits = OwnerHardLimits(
        version="suite-v1",
        max_total_capital_eur=Decimal("100"),
        max_position_eur=Decimal("5"),
        max_total_exposure_eur=Decimal("15"),
        max_open_positions=3,
        max_daily_loss_eur=Decimal("2"),
        max_daily_profit_eur=Decimal("3"),
        max_weekly_loss_eur=Decimal("5"),
        max_weekly_profit_eur=None,
        max_monthly_loss_eur=Decimal("10"),
        max_monthly_profit_eur=None,
        max_drawdown_percent=Decimal("10"),
        max_orders_per_day=10,
    )
    controls = ControlCenter(store, settings)
    risk = RiskEngine(settings, limits, RiskConfiguration(), {"AAPL": instrument}, controls)
    quote = Quote("AAPL", Decimal("99.90"), Decimal("100"), datetime.now(UTC), "suite")
    broker = PaperBroker("BOT-001", Decimal("100"), {"AAPL": instrument}, {"AAPL": quote}, SimulationConfig(slippage_bps=Decimal("0"), commission_bps=Decimal("0")))
    intent = TradeIntent(
        intent_id="suite-intent",
        strategy_id="suite-strategy",
        strategy_version="v1",
        model_version="v1",
        instrument_id="AAPL",
        side=Side.BUY,
        kind=IntentKind.ENTRY,
        desired_notional=Decimal("5"),
        confidence=Decimal("0.5"),
        reason_codes=("SUITE",),
        feature_snapshot_hash="suite-hash",
        timestamp=datetime.now(UTC),
        account_id="BOT-001",
        mode=ExecutionMode.PAPER,
        idempotency_key="suite-key",
        sizing_policy=SizingPolicy.BOUNDED,
    )
    snapshot = RiskSnapshot(Decimal("50"), Decimal("50"), Decimal("50"), Decimal("0"), 0, 0)
    return settings, controls, risk, broker, quote, intent, snapshot, ExecutionService(risk, broker, controls, store)


def _probe(name: str, function: Callable[[], None]) -> dict[str, object]:
    try:
        function()
    except Exception as exc:  # acceptance output should never hide a failed probe
        return {"name": name, "passed": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"name": name, "passed": True, "error": None}


def run() -> list[dict[str, object]]:
    probes: list[tuple[str, Callable[[], None]]] = []

    def stop_blocks_and_does_not_liquidate() -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "suite.db")
            _, controls, _, broker, _, _, _, service = _fixtures(store)
            controls.stop_everything("suite")
            result = service.submit_intent(_fixtures(store)[5], _fixtures(store)[4], _fixtures(store)[6])
            assert result.risk_decision.decision is Decision.REJECT
            assert broker.snapshot().positions == {}

    def stop_survives_restart() -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "suite.db"
            store = SQLiteStore(path)
            _, controls, *_ = _fixtures(store)
            controls.stop_everything("restart")
            store.close()
            reopened = SQLiteStore(path)
            assert reopened.load_control().state.value == "KILL_SWITCH_ACTIVE"
            reopened.close()

    def pause_blocks_entries() -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "suite.db")
            _, controls, _, _, quote, intent, snapshot, service = _fixtures(store)
            controls.pause("suite")
            assert service.submit_intent(intent, quote, snapshot).risk_decision.decision is Decision.REJECT

    def resume_requires_reconciliation() -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "suite.db")
            _, controls, *_ = _fixtures(store)
            controls.pause("suite")
            try:
                controls.resume(ResumeChecks(True, True, True, True, True, False, True, True, True))
            except Exception:
                return
            raise AssertionError("resume unexpectedly succeeded")

    def account_isolation() -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "suite.db")
            _, _, risk, _, quote, intent, snapshot, _ = _fixtures(store)
            assert risk.evaluate(replace(intent, account_id="MYINVESTOR-001"), quote, snapshot).decision is Decision.REJECT

    def auto_cannot_raise_ceiling() -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "suite.db")
            _, _, risk, _, quote, intent, snapshot, _ = _fixtures(store)
            decision = risk.evaluate(replace(intent, desired_notional=Decimal("50")), quote, snapshot)
            assert decision.approved_notional <= Decimal("5")

    def fee_and_fifo() -> None:
        engine = TaxLotEngine()
        when = datetime(2023, 1, 1, tzinfo=UTC)
        engine.record_buy("BOT-001", "US0378331005", "AAPL", Decimal("1"), Decimal("5"), Decimal("1"), when, "buy")
        result = engine.record_sell("BOT-001", "US0378331005", "AAPL", Decimal("1"), Decimal("8"), Decimal("0"), datetime(2024, 1, 1, tzinfo=UTC), "sell")[0]
        assert result.realized_result_eur == Decimal("2")

    def withdrawal_has_no_execution() -> None:
        assert not hasattr(WithdrawalPlanner, "withdraw")
        assert not WithdrawalPlanner.withdrawals_enabled()

    probes.extend(
        [
            ("STOP_BLOCKS_AND_DOES_NOT_LIQUIDATE", stop_blocks_and_does_not_liquidate),
            ("STOP_SURVIVES_RESTART", stop_survives_restart),
            ("PAUSE_BLOCKS_ENTRIES", pause_blocks_entries),
            ("RESUME_REQUIRES_RECONCILIATION", resume_requires_reconciliation),
            ("ACCOUNT_ISOLATION", account_isolation),
            ("AUTO_CANNOT_RAISE_CEILING", auto_cannot_raise_ceiling),
            ("FEES_AFFECT_FIFO_RESULT", fee_and_fifo),
            ("WITHDRAWAL_IS_INFORMATIONAL", withdrawal_has_no_execution),
        ]
    )
    return [_probe(name, function) for name, function in probes]


def main() -> int:
    results = run()
    passed = all(bool(result["passed"]) for result in results)
    report = {"suite": "TradeForge safety acceptance", "passed": passed, "results": results}
    artifacts = Path("artifacts")
    artifacts.mkdir(exist_ok=True)
    (artifacts / "safety-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("TradeForge safety acceptance suite")
    for result in results:
        status = "PASS" if result["passed"] else "FAIL"
        suffix = f" - {result['error']}" if result["error"] else ""
        print(f"{status}: {result['name']}{suffix}")
    print(f"Machine-readable report: {artifacts / 'safety-report.json'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
