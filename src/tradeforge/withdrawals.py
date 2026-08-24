"""Read-only capital planning; no withdrawal capability exists."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .config import TRADEFORGE_WITHDRAWALS_ENABLED


@dataclass(frozen=True, slots=True)
class WithdrawalPlan:
    total_equity_eur: Decimal
    net_contributed_capital_eur: Decimal
    total_pnl_eur: Decimal
    realized_pnl_eur: Decimal
    unrealized_pnl_eur: Decimal
    available_cash_eur: Decimal
    broker_withdrawable_cash_eur: Decimal | None
    estimated_tax_reserve_eur: Decimal
    owner_target_capital_eur: Decimal
    potential_withdrawal_eur: Decimal
    informational_only: bool = True
    label: str = "INFORMATIONAL ONLY - WITHDRAW THROUGH OFFICIAL BROKER"


class WithdrawalPlanner:
    """There is intentionally no ``withdraw`` method."""

    def plan(
        self,
        total_equity_eur: Decimal,
        net_contributed_capital_eur: Decimal,
        realized_pnl_eur: Decimal,
        unrealized_pnl_eur: Decimal,
        available_cash_eur: Decimal,
        broker_withdrawable_cash_eur: Decimal | None,
        estimated_tax_reserve_eur: Decimal,
        owner_target_capital_eur: Decimal,
    ) -> WithdrawalPlan:
        values = (
            total_equity_eur,
            net_contributed_capital_eur,
            available_cash_eur,
            estimated_tax_reserve_eur,
            owner_target_capital_eur,
        )
        if any(value < Decimal("0") for value in values):
            raise ValueError("withdrawal planning values cannot be negative")
        if broker_withdrawable_cash_eur is not None and broker_withdrawable_cash_eur < Decimal("0"):
            raise ValueError("broker withdrawable cash cannot be negative")
        total_pnl = realized_pnl_eur + unrealized_pnl_eur
        if broker_withdrawable_cash_eur is None:
            potential = Decimal("0")
        else:
            cash_after_reserve = max(Decimal("0"), min(available_cash_eur, broker_withdrawable_cash_eur) - estimated_tax_reserve_eur)
            equity_above_target = max(Decimal("0"), total_equity_eur - owner_target_capital_eur)
            potential = min(cash_after_reserve, equity_above_target)
        return WithdrawalPlan(
            total_equity_eur=total_equity_eur,
            net_contributed_capital_eur=net_contributed_capital_eur,
            total_pnl_eur=total_pnl,
            realized_pnl_eur=realized_pnl_eur,
            unrealized_pnl_eur=unrealized_pnl_eur,
            available_cash_eur=available_cash_eur,
            broker_withdrawable_cash_eur=broker_withdrawable_cash_eur,
            estimated_tax_reserve_eur=estimated_tax_reserve_eur,
            owner_target_capital_eur=owner_target_capital_eur,
            potential_withdrawal_eur=potential,
            informational_only=True,
        )

    @staticmethod
    def open_broker_to_withdraw() -> str:
        return "OPEN_BROKER_TO_WITHDRAW"

    @staticmethod
    def withdrawals_enabled() -> bool:
        return TRADEFORGE_WITHDRAWALS_ENABLED
