"""Model tools (owner: math teammate). Deterministic scoring and pricing.

PLACEHOLDER MATH: every weight, constant and formula below is a stand-in so
the agent and frontend can be built now. Replace with the real model
(credibility weighting, Poisson-fitted weights, priced loss) while keeping
the return shapes in docs/tool-spec.md.
"""
from datetime import date

# Placeholder weights (sum to 1). Replace with fitted values.
WEIGHTS = {"age": 0.25, "psc": 0.40, "flag": 0.20, "class": 0.15}

# Placeholder peer-cohort PSC risk (0-1) and Buhlmann-style k.
COHORT_PSC_RISK = {"Bulk Carrier": 0.35}
CREDIBILITY_K = 5

FLAG_RISK = {"white": 0.1, "grey": 0.6, "black": 1.0}

# Placeholder pricing constants.
BASE_RATE = 0.012          # expected loss as fraction of insured value at average risk
RISK_LOADING = 0.30        # expense + profit + uncertainty loading


def _age_risk(year_built: int) -> float:
    age = date.today().year - year_built
    return min(age / 30, 1.0)


def _psc_raw_risk(inspections: int, deficiencies: int, detentions: int) -> float:
    if inspections == 0:
        return 0.0
    det_rate = detentions / inspections
    def_rate = deficiencies / inspections
    return min(0.7 * min(det_rate / 0.3, 1) + 0.3 * min(def_rate / 5, 1), 1.0)


def score_vessel(vessel_type: str, year_built: int, flag_list: str, iacs_member: bool,
                 inspections: int, deficiencies: int, detentions: int) -> dict:
    """Return a 0-100 risk score (higher = riskier) with factor contributions."""
    cohort = COHORT_PSC_RISK.get(vessel_type, 0.35)
    z = inspections / (inspections + CREDIBILITY_K)
    psc_blended = z * _psc_raw_risk(inspections, deficiencies, detentions) + (1 - z) * cohort

    factors = {
        "age": _age_risk(year_built),
        "psc": psc_blended,
        "flag": FLAG_RISK.get(flag_list, 0.6),
        "class": 0.0 if iacs_member else 1.0,
    }
    contributions = {k: round(100 * WEIGHTS[k] * v, 1) for k, v in factors.items()}
    return {
        "score": round(sum(contributions.values()), 1),
        "contributions": contributions,
        "credibility_z": round(z, 2),
        "cohort_psc_risk": cohort,
        "model_version": "placeholder-0.1",
    }


def price_premium(score: float, insured_value_usd: float) -> dict:
    """Convert a score into an annual H&M premium. Score 50 = average risk."""
    relativity = 0.4 + 0.012 * score       # placeholder curve: 0 -> 0.4x, 50 -> 1.0x, 100 -> 1.6x
    expected_loss = BASE_RATE * insured_value_usd * relativity
    premium = expected_loss * (1 + RISK_LOADING)
    return {
        "relativity": round(relativity, 2),
        "expected_loss_usd": round(expected_loss),
        "premium_usd": round(premium),
        "rate_on_value_pct": round(100 * premium / insured_value_usd, 3),
        "model_version": "placeholder-0.1",
    }
