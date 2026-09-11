"""Monthly 50:50 reseller payout computation.

v1 is manual-settlement: this only writes ResellerPayout / ResellerPayoutLine
rows at status='scheduled'. The owner transfers each reseller's net to their UPI
by hand and marks the row 'paid' with a UTR from the admin UI. No payout-API call
lives here.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from webapp.database import (
    ResellerProfile, ResellerPayout, ResellerPayoutLine,
    Establishment, SubscriptionFee,
)


def _round2(x: float) -> float:
    return round(float(x or 0.0), 2)


def compute_payouts_for_period(db: Session, period_label: str) -> list:
    """period_label is 'YYYY-MM' -- a bookkeeping label for the run. Fee selection
    is by 'paid and not yet on a payout line', so late payments are always caught
    on the next run regardless of which month they land in."""
    already_lined = {
        row[0] for row in db.query(ResellerPayoutLine.subscription_fee_id).all()
        if row[0] is not None
    }
    summary = []

    for prof in db.query(ResellerProfile).filter(ResellerProfile.status == "active").all():
        est_rows = db.query(Establishment).filter(
            Establishment.referred_by_reseller_id == prof.user_id
        ).all()
        if not est_rows:
            continue
        est_by_id = {e.id: e for e in est_rows}

        fees = db.query(SubscriptionFee).filter(
            SubscriptionFee.establishment_id.in_(list(est_by_id.keys())),
            SubscriptionFee.is_paid == True,  # noqa: E712
        ).all()
        new_fees = [f for f in fees if f.id not in already_lined]
        if not new_fees:
            continue

        gross = _round2(sum(f.amount_due for f in new_fees))
        share_gross = _round2(gross / 2)
        tds_rate = (prof.tds_rate or 0.0) if (prof.pan or "").strip() else 0.0
        tds = _round2(share_gross * tds_rate / 100.0)
        share_net = _round2(share_gross - tds)
        owner_share = _round2(gross - share_gross)

        payout = db.query(ResellerPayout).filter(
            ResellerPayout.reseller_id == prof.user_id,
            ResellerPayout.period == period_label,
        ).first()
        if payout is None:
            payout = ResellerPayout(
                reseller_id=prof.user_id, period=period_label,
                gross_collected=gross, reseller_share_gross=share_gross,
                tds_amount=tds, reseller_share_net=share_net, owner_share=owner_share,
                status="scheduled", upi_id=prof.upi_id, run_at=datetime.utcnow(),
            )
            db.add(payout)
            db.flush()
        else:
            payout.gross_collected = _round2(payout.gross_collected + gross)
            payout.reseller_share_gross = _round2(payout.reseller_share_gross + share_gross)
            payout.tds_amount = _round2(payout.tds_amount + tds)
            payout.reseller_share_net = _round2(payout.reseller_share_net + share_net)
            payout.owner_share = _round2(payout.owner_share + owner_share)

        for f in new_fees:
            est = est_by_id.get(f.establishment_id)
            db.add(ResellerPayoutLine(
                payout_id=payout.id, subscription_fee_id=f.id,
                establishment_id=f.establishment_id,
                establishment_name=est.name if est else None,
                financial_year=f.financial_year, month=f.month,
                fee_amount=_round2(f.amount_due), reseller_share=_round2(f.amount_due / 2),
            ))
            already_lined.add(f.id)

        db.commit()
        summary.append({"reseller_id": prof.user_id, "period": period_label,
                        "gross": gross, "net_to_reseller": share_net, "fees": len(new_fees)})

    return summary
