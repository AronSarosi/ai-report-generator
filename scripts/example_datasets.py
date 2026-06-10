"""Extra rich, believable datasets for the Example Reports gallery.

Each is a *different domain* so the gallery demonstrates that the engine is genuinely
data-agnostic (not hardcoded to sales): SaaS subscription metrics and web/marketing
analytics complement the retail-sales and FP&A budget datasets already in the repo.

Every dataset has a baked-in story so the generated report surfaces real findings.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# SaaS subscription metrics  (monthly · plan · region)
# --------------------------------------------------------------------------- #
SAAS_SEED = 101
_PLANS = {  # plan: (base MRR/customer, base customers, growth_mult start->end)
    "Enterprise": (1800, 60, (1.0, 1.9)),   # the engine of growth
    "Business": (480, 220, (1.0, 1.35)),
    "Starter": (49, 900, (1.0, 1.05)),       # flat
    "Free": (0, 2600, (1.0, 1.2)),           # grows but no MRR (top of funnel)
}
# Per-country demand multiplier (more granular than regions -> a few thousand rows).
_SAAS_COUNTRIES = {
    "United States": 1.35, "Canada": 0.8, "United Kingdom": 1.0, "Germany": 0.95,
    "France": 0.85, "Netherlands": 0.7, "India": 0.9, "Australia": 0.78,
    "Japan": 0.82, "Brazil": 0.65, "Mexico": 0.55, "Singapore": 0.6,
}


def generate_saas() -> pd.DataFrame:
    rng = np.random.default_rng(SAAS_SEED)
    rows = []
    months = [date(2024, 6, 1)]
    for _ in range(23):
        y, m = months[-1].year, months[-1].month
        months.append(date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1))
    n = len(months)
    for i, mo in enumerate(months):
        t = i / (n - 1)
        for plan, (arpu, base_cust, (g0, g1)) in _PLANS.items():
            for region, rmult in _SAAS_COUNTRIES.items():
                grow = g0 + (g1 - g0) * t
                customers = int(base_cust * rmult * grow * float(rng.lognormal(0, 0.05)))
                mrr = round(customers * arpu * float(rng.lognormal(0, 0.04)), 2)
                # churn: Free/Starter leak more; improves slightly over time for paid
                churn_rate = (0.06 if plan in ("Free", "Starter") else 0.025) * (1.1 - 0.3 * t)
                churned_mrr = round(mrr * churn_rate, 2)
                new_mrr = round(mrr * (0.08 + 0.05 * grow), 2)
                rows.append({
                    "month": mo.isoformat(), "plan": plan, "country": region,
                    "active_customers": customers, "mrr": mrr,
                    "new_mrr": new_mrr, "churned_mrr": churned_mrr,
                })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Web / marketing analytics  (monthly · channel)
# --------------------------------------------------------------------------- #
MKT_SEED = 202
_CHANNELS = {  # channel: (base sessions, conv_rate, AOV, spend/session, trend)
    "Organic Search": (42000, 0.021, 78, 0.0, (1.0, 1.45)),   # growing, free
    "Paid Search": (28000, 0.028, 82, 0.95, (1.0, 1.1)),       # expensive
    "Social": (35000, 0.012, 64, 0.35, (1.3, 0.8)),            # declining
    "Email": (16000, 0.045, 90, 0.02, (1.0, 1.25)),            # efficient
    "Referral": (9000, 0.030, 75, 0.0, (1.0, 1.15)),
}


def generate_marketing() -> pd.DataFrame:
    """Daily web/marketing analytics by channel over two years (~thousands of rows)."""
    from datetime import timedelta
    rng = np.random.default_rng(MKT_SEED)
    rows = []
    start, end = date(2024, 6, 1), date(2026, 5, 31)
    n_days = (end - start).days + 1
    annual = {1: 0.9, 2: 0.88, 3: 0.97, 4: 1.0, 5: 1.0, 6: 0.95,
              7: 0.9, 8: 0.92, 9: 1.02, 10: 1.1, 11: 1.35, 12: 1.4}
    weekday = [1.05, 1.08, 1.06, 1.04, 0.98, 0.82, 0.8]  # Mon..Sun (B2B dips on weekends)
    for d in range(n_days):
        day = start + timedelta(days=d)
        t = d / (n_days - 1)
        season = annual[day.month] * weekday[day.weekday()]
        for ch, (base, cvr, aov, cps, (s0, s1)) in _CHANNELS.items():
            trend = s0 + (s1 - s0) * t
            daily_base = base / 30.0
            sessions = int(daily_base * trend * season * float(rng.lognormal(0, 0.12)))
            conversions = int(sessions * cvr * float(rng.lognormal(0, 0.15)))
            revenue = round(conversions * aov * float(rng.lognormal(0, 0.08)), 2)
            ad_spend = round(sessions * cps * float(rng.lognormal(0, 0.08)), 2)
            rows.append({
                "date": day.isoformat(), "channel": ch, "sessions": sessions,
                "conversions": conversions, "revenue": revenue, "ad_spend": ad_spend,
            })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1] / "data" / "out"
    root.mkdir(parents=True, exist_ok=True)
    for name, fn in (("saas_metrics", generate_saas), ("marketing_analytics", generate_marketing)):
        df = fn()
        df.to_csv(root / f"{name}.csv", index=False)
        print(f"{name}: {df.shape[0]} rows x {df.shape[1]} cols -> data/out/{name}.csv")
