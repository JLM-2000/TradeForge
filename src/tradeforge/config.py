"""Fail-closed configuration and permanent scope restrictions."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from .domain import ExecutionMode


PERSONAL_USE_ONLY = True
REGULATORY_REVIEW_REQUIRED = False
MYINVESTOR_LIVE_EXECUTION = False
TRADEFORGE_WITHDRAWALS_ENABLED = False
LIVE_TRADING_ENABLED = False
LIVE_READINESS_APPROVED = False
LIVE_ADAPTER_AVAILABLE = False
LONG_ONLY = True
LEVERAGE = Decimal("1")
MARGIN = False


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings with safe defaults.

    A live mode can be represented for readiness testing, but the independent
    gates remain false in this checkpoint and therefore cannot execute.
    """

    mode: ExecutionMode = ExecutionMode.PAPER
    bot_account_id: str = "paper-bot"
    personal_investment_account_ids: frozenset[str] = field(default_factory=frozenset)
    allowed_instrument_ids: frozenset[str] = field(default_factory=frozenset)
    live_trading_enabled: bool = LIVE_TRADING_ENABLED
    live_readiness_approved: bool = LIVE_READINESS_APPROVED
    bot_account_validated: bool = False
    broker_healthy: bool = True
    market_data_healthy: bool = True
    risk_engine_healthy: bool = True
    reconciliation_ok: bool = True
    safety_suite_passing: bool = False
    kill_switch: bool = False

    def __post_init__(self) -> None:
        if not self.bot_account_id.strip():
            raise ValueError("BOT_ACCOUNT_ID must be explicit and non-empty")
        if self.bot_account_id in self.personal_investment_account_ids:
            raise ValueError("BOT_ACCOUNT_ID cannot be a personal investment account")
        if self.mode is ExecutionMode.LIVE and not self.live_execution_allowed:
            # Representing live during readiness testing is allowed, executing is not.
            return

    @property
    def live_execution_allowed(self) -> bool:
        return all(
            (
                self.mode is ExecutionMode.LIVE,
                LIVE_TRADING_ENABLED,
                LIVE_ADAPTER_AVAILABLE,
                self.live_trading_enabled,
                self.live_readiness_approved,
                self.bot_account_validated,
                self.broker_healthy,
                self.market_data_healthy,
                self.risk_engine_healthy,
                self.reconciliation_ok,
                not self.kill_switch,
                self.safety_suite_passing,
            )
        )

    @classmethod
    def from_env(cls) -> "Settings":
        """Load non-secret settings; live remains denied unless every gate is explicit."""

        raw_mode = os.getenv("TRADEFORGE_MODE", ExecutionMode.PAPER.value).upper()
        try:
            mode = ExecutionMode(raw_mode)
        except ValueError as exc:
            raise ValueError(f"Unsupported TRADEFORGE_MODE: {raw_mode}") from exc

        accounts = frozenset(
            item.strip()
            for item in os.getenv("TRADEFORGE_PERSONAL_INVESTMENT_ACCOUNTS", "").split(",")
            if item.strip()
        )
        instruments = frozenset(
            item.strip()
            for item in os.getenv("TRADEFORGE_ALLOWED_INSTRUMENTS", "").split(",")
            if item.strip()
        )
        # These environment flags are intentionally opt-in, but settings still
        # cannot create a live path without the future readiness implementation.
        return cls(
            mode=mode,
            bot_account_id=os.getenv("TRADEFORGE_BOT_ACCOUNT_ID", "paper-bot"),
            personal_investment_account_ids=accounts,
            allowed_instrument_ids=instruments,
            live_trading_enabled=os.getenv("TRADEFORGE_LIVE_TRADING_ENABLED", "false").lower() == "true",
            live_readiness_approved=os.getenv("TRADEFORGE_LIVE_READINESS_APPROVED", "false").lower() == "true",
        )
