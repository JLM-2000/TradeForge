from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tradeforge.config import Settings
from tradeforge.controls import ControlCenter
from tradeforge.domain import (
    AssetClass,
    ExecutionMode,
    Instrument,
    IntentKind,
    OwnerHardLimits,
    Quote,
    RiskConfiguration,
    RiskSnapshot,
    Side,
    SizingPolicy,
    TradeIntent,
)
from tradeforge.persistence import SQLiteStore
from tradeforge.risk import RiskEngine


INSTRUMENT = Instrument(
    instrument_id="AAPL",
    isin="US0378331005",
    ticker="AAPL",
    venue="XNAS",
    asset_class=AssetClass.STOCK,
    quantity_increment=Decimal("0.01"),
)


def now() -> datetime:
    return datetime.now(UTC)


def quote(age_seconds: int = 0) -> Quote:
    return Quote(
        instrument_id=INSTRUMENT.instrument_id,
        bid=Decimal("99.90"),
        ask=Decimal("100.00"),
        timestamp=now() - timedelta(seconds=age_seconds),
        source="test-feed",
    )


def limits() -> OwnerHardLimits:
    return OwnerHardLimits(
        version="limits-v1",
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


def settings(mode: ExecutionMode = ExecutionMode.PAPER) -> Settings:
    return Settings(
        mode=mode,
        bot_account_id="BOT-001",
        personal_investment_account_ids=frozenset({"MYINVESTOR-001"}),
        allowed_instrument_ids=frozenset({INSTRUMENT.instrument_id}),
    )


def controls(store: SQLiteStore, mode: ExecutionMode = ExecutionMode.PAPER) -> ControlCenter:
    return ControlCenter(store, settings(mode))


def engine(store: SQLiteStore, risk_config: RiskConfiguration | None = None, mode: ExecutionMode = ExecutionMode.PAPER) -> RiskEngine:
    runtime_settings = settings(mode)
    return RiskEngine(
        settings=runtime_settings,
        owner_limits=limits(),
        risk_configuration=risk_config or RiskConfiguration(),
        instruments={INSTRUMENT.instrument_id: INSTRUMENT},
        controls=ControlCenter(store, runtime_settings),
    )


def snapshot(**overrides: object) -> RiskSnapshot:
    values: dict[str, object] = {
        "available_cash": Decimal("50"),
        "withdrawable_cash": Decimal("50"),
        "total_equity": Decimal("50"),
        "current_exposure": Decimal("0"),
        "open_positions": 0,
        "open_orders_today": 0,
    }
    values.update(overrides)
    return RiskSnapshot(**values)


def intent(
    *,
    desired_notional: Decimal = Decimal("5"),
    account_id: str = "BOT-001",
    side: Side = Side.BUY,
    kind: IntentKind = IntentKind.ENTRY,
    mode: ExecutionMode = ExecutionMode.PAPER,
    key: str = "intent-key-1",
    sizing_policy: SizingPolicy = SizingPolicy.BOUNDED,
) -> TradeIntent:
    return TradeIntent(
        intent_id="intent-1",
        strategy_id="strategy-1",
        strategy_version="strategy-v1",
        model_version="model-v1",
        instrument_id=INSTRUMENT.instrument_id,
        side=side,
        kind=kind,
        desired_notional=desired_notional,
        confidence=Decimal("0.8"),
        reason_codes=("TEST_SIGNAL",),
        feature_snapshot_hash="features-hash",
        timestamp=now(),
        account_id=account_id,
        mode=mode,
        idempotency_key=key,
        sizing_policy=sizing_policy,
    )
