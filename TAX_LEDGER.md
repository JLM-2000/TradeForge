# Spanish-Oriented Tax Ledger

This is a bookkeeping and reconciliation aid for a Spanish tax resident. It is
not tax advice and does not replace AEAT, broker reports, TaxDown, an accountant,
or a lawyer.

## Fees and gain calculation

For a normal onerous disposal, the simplified result is:

```text
taxable disposal result = (sale proceeds - directly related sale expenses)
                          - (purchase cost + directly related purchase expenses)
```

Therefore, if one unit is bought for EUR 5 with a EUR 1 acquisition commission
and sold for EUR 8 with no sale commission, the simplified realized result is
EUR 2. If the sale also has a EUR 1 directly related commission, it is EUR 1.
The lot engine stores both fee sides and allocates them through FIFO.

This is different from a EUR 1 tax payment or withholding. A tax payment is not
automatically a purchase expense or a second capital loss, and the EUR 8 cash
withdrawal is not itself a gain. The disposal event determines the realized
result; cash movement and tax payment are tracked separately. Broker statements
and professional review control the final treatment of a particular charge.

The implementation is informed by Ley 35/2006, Articles 34 and 35, official
BOE consolidated text: https://www.boe.es/buscar/act.php?id=BOE-A-2006-20764#a35
The consolidated text is informational; it does not replace checking the
current law, instrument, broker statement, or tax advice.

## Separation of concepts

- A disposal can create realized market P&L and a tax-lot event.
- An unrealized price change is tracked separately and is not included in the
  default tax reserve.
- A deposit or withdrawal is a cash movement, not trading profit or loss.
- An external manual trade is recorded with `OWNER_MANUAL` origin and does not
  pretend to be TradeForge-initiated.

## Data retained

Each acquisition, disposal, dividend, withholding, fee, FX conversion,
corporate action, deposit, withdrawal, broker identifier, ISIN, quantity,
currency, EUR conversion, and source timestamp is retained as an append-only
event. Corrections reference the source event.

## FIFO and review

Tax lots are consumed FIFO within a homogeneous-security key. Potential
reacquisition/restricted-loss situations are flagged for professional review;
the engine does not assert a final Spanish legal conclusion. Broker average
cost is never treated as the fiscal basis by itself.

## Annual pack

The annual workflow freezes a report snapshot, reconciles broker/TradeForge records,
lists matched/missing/mismatched/review-required items, and exports CSV, JSON,
and XLSX-compatible tabular data in later milestones. The first checkpoint
provides the typed lot and reserve contracts only.

## Tax reserve

The reserve is a transparent configurable estimate based on realized taxable
result, configured rates, dividends, and withholding. It never initiates,
blocks, or moves money and is always labelled `ESTIMATE - PROFESSIONAL REVIEW
REQUIRED`.
