"""Spanish-oriented tax-lot bookkeeping, deliberately not tax advice."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from .domain import ZERO, new_id, utc_now


def _positive(value: Decimal, name: str) -> Decimal:
    if value <= ZERO:
        raise ValueError(f"{name} must be positive")
    return value


def _non_negative(value: Decimal, name: str) -> Decimal:
    if value < ZERO:
        raise ValueError(f"{name} must be non-negative")
    return value


@dataclass(frozen=True, slots=True)
class TaxLot:
    lot_id: str
    account_id: str
    homogeneous_key: str
    instrument_id: str
    quantity: Decimal
    remaining_quantity: Decimal
    acquisition_price_eur: Decimal
    acquisition_at: datetime
    fees_eur: Decimal
    source_event_id: str

    def __post_init__(self) -> None:
        _positive(self.quantity, "quantity")
        _non_negative(self.remaining_quantity, "remaining_quantity")
        if self.remaining_quantity > self.quantity:
            raise ValueError("remaining quantity cannot exceed original quantity")
        _positive(self.acquisition_price_eur, "acquisition_price_eur")
        _non_negative(self.fees_eur, "fees_eur")
        if self.acquisition_at.tzinfo is None:
            raise ValueError("acquisition_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class TaxDisposal:
    disposal_id: str
    account_id: str
    homogeneous_key: str
    instrument_id: str
    quantity: Decimal
    proceeds_eur: Decimal
    cost_basis_eur: Decimal
    fees_eur: Decimal
    realized_result_eur: Decimal
    tax_year: int
    tax_status: str
    potential_restricted_loss_eur: Decimal
    source_event_id: str


@dataclass(frozen=True, slots=True)
class TaxReviewItem:
    review_id: str
    category: str
    message: str
    instrument_id: str
    source_event_id: str
    status: str = "OPEN"


class TaxLotEngine:
    """FIFO lots by homogeneous-security key with conservative review flags."""

    def __init__(self, reacquisition_review_window: timedelta = timedelta(days=60)) -> None:
        self._lots: dict[str, list[TaxLot]] = {}
        self._acquisitions: list[TaxLot] = []
        self._disposals: list[TaxDisposal] = []
        self._reviews: list[TaxReviewItem] = []
        self._reacquisition_window = reacquisition_review_window

    def record_buy(
        self,
        account_id: str,
        homogeneous_key: str,
        instrument_id: str,
        quantity: Decimal,
        price_eur: Decimal,
        fees_eur: Decimal,
        acquired_at: datetime,
        source_event_id: str,
    ) -> TaxLot:
        acquired_at = acquired_at.astimezone(UTC)
        lot = TaxLot(
            lot_id=new_id("lot"),
            account_id=account_id,
            homogeneous_key=homogeneous_key,
            instrument_id=instrument_id,
            quantity=_positive(quantity, "quantity"),
            remaining_quantity=_positive(quantity, "quantity"),
            acquisition_price_eur=_positive(price_eur, "price_eur"),
            acquisition_at=acquired_at,
            fees_eur=_non_negative(fees_eur, "fees_eur"),
            source_event_id=source_event_id,
        )
        self._lots.setdefault(homogeneous_key, []).append(lot)
        self._acquisitions.append(lot)
        return lot

    def record_sell(
        self,
        account_id: str,
        homogeneous_key: str,
        instrument_id: str,
        quantity: Decimal,
        price_eur: Decimal,
        fees_eur: Decimal,
        disposed_at: datetime,
        source_event_id: str,
    ) -> tuple[TaxDisposal, ...]:
        disposed_at = disposed_at.astimezone(UTC)
        quantity = _positive(quantity, "quantity")
        price_eur = _positive(price_eur, "price_eur")
        lots = self._lots.setdefault(homogeneous_key, [])
        available = sum((lot.remaining_quantity for lot in lots), ZERO)
        if available < quantity:
            raise ValueError("FIFO sale exceeds available tax lots")
        remaining = quantity
        sale_fee_per_unit = _non_negative(fees_eur, "fees_eur") / quantity
        disposals: list[TaxDisposal] = []
        updated: list[TaxLot] = []
        for lot in lots:
            if remaining <= ZERO:
                updated.append(lot)
                continue
            matched = min(lot.remaining_quantity, remaining)
            if matched <= ZERO:
                updated.append(lot)
                continue
            lot_fee_per_unit = lot.fees_eur / lot.quantity
            allocated_cost = matched * lot.acquisition_price_eur + matched * lot_fee_per_unit
            allocated_sale_fees = matched * sale_fee_per_unit
            proceeds = matched * price_eur
            realized = proceeds - allocated_cost - allocated_sale_fees
            potential_restricted = ZERO
            review = "REALIZED"
            if realized < ZERO and self._has_reacquisition(homogeneous_key, disposed_at, matched):
                potential_restricted = abs(realized)
                review = "REVIEW_REQUIRED"
                self._reviews.append(
                    TaxReviewItem(
                        review_id=new_id("tax_review"),
                        category="HOMOGENEOUS_SECURITY_REACQUISITION",
                        message="Potential reacquisition/restricted-loss situation; professional review required",
                        instrument_id=instrument_id,
                        source_event_id=source_event_id,
                    )
                )
            disposal = TaxDisposal(
                disposal_id=new_id("disposal"),
                account_id=account_id,
                homogeneous_key=homogeneous_key,
                instrument_id=instrument_id,
                quantity=matched,
                proceeds_eur=proceeds,
                cost_basis_eur=allocated_cost,
                fees_eur=allocated_sale_fees,
                realized_result_eur=realized,
                tax_year=disposed_at.year,
                tax_status=review,
                potential_restricted_loss_eur=potential_restricted,
                source_event_id=source_event_id,
            )
            disposals.append(disposal)
            remaining_quantity = lot.remaining_quantity - matched
            remaining_fees = lot.fees_eur - matched * lot_fee_per_unit
            updated.append(
                replace(
                    lot,
                    remaining_quantity=remaining_quantity,
                    fees_eur=remaining_fees,
                )
            )
            remaining -= matched
        self._lots[homogeneous_key] = updated
        self._disposals.extend(disposals)
        return tuple(disposals)

    def lots(self, homogeneous_key: str | None = None) -> tuple[TaxLot, ...]:
        if homogeneous_key is not None:
            return tuple(self._lots.get(homogeneous_key, ()))
        return tuple(lot for lots in self._lots.values() for lot in lots)

    def disposals(self, tax_year: int | None = None) -> tuple[TaxDisposal, ...]:
        if tax_year is None:
            return tuple(self._disposals)
        return tuple(item for item in self._disposals if item.tax_year == tax_year)

    def review_items(self) -> tuple[TaxReviewItem, ...]:
        return tuple(self._reviews)

    def realized_result(self, tax_year: int | None = None) -> Decimal:
        return sum((item.realized_result_eur for item in self.disposals(tax_year)), ZERO)

    def _has_reacquisition(self, key: str, disposed_at: datetime, matched: Decimal) -> bool:
        # This is a deliberately broad review detector, not a legal conclusion.
        lower = disposed_at - self._reacquisition_window
        acquired = [
            lot
            for lot in self._acquisitions
            if lot.homogeneous_key == key and lower <= lot.acquisition_at <= disposed_at + self._reacquisition_window
        ]
        return bool(acquired) and matched > ZERO


@dataclass(frozen=True, slots=True)
class TaxReserveConfig:
    tax_year: int
    effective_rate: Decimal
    include_dividends: bool = True

    def __post_init__(self) -> None:
        if not ZERO <= self.effective_rate <= Decimal("1"):
            raise ValueError("effective_rate must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class TaxReserveEstimate:
    tax_year: int
    label: str
    realized_taxable_estimate_eur: Decimal
    dividend_estimate_eur: Decimal
    withholding_eur: Decimal
    reserve_eur: Decimal
    planning_net_realized_eur: Decimal
    unrealized_excluded_eur: Decimal


class TaxReserveEstimator:
    def __init__(self, config: TaxReserveConfig) -> None:
        self.config = config

    def estimate(
        self,
        realized_taxable_estimate_eur: Decimal,
        dividends_eur: Decimal = ZERO,
        withholding_eur: Decimal = ZERO,
        unrealized_pnl_eur: Decimal = ZERO,
    ) -> TaxReserveEstimate:
        realized = realized_taxable_estimate_eur
        dividends = dividends_eur if self.config.include_dividends else ZERO
        withholding = _non_negative(withholding_eur, "withholding_eur")
        taxable_base = max(ZERO, realized + dividends)
        reserve = max(ZERO, taxable_base * self.config.effective_rate - withholding)
        return TaxReserveEstimate(
            tax_year=self.config.tax_year,
            label="ESTIMATE - PROFESSIONAL REVIEW REQUIRED",
            realized_taxable_estimate_eur=realized,
            dividend_estimate_eur=dividends,
            withholding_eur=withholding,
            reserve_eur=reserve,
            planning_net_realized_eur=realized - reserve,
            unrealized_excluded_eur=unrealized_pnl_eur,
        )
