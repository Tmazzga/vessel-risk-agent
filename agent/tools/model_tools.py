"""Model tools (owner: Yuvraj). Deterministic scoring and pricing.

The formulas live in agent/tools/scoring.py and every number lives in
web/risk_config.json (shared with the web form). Calibrate by editing the
config, not the code.
"""
from .scoring import price_premium, score_risk

__all__ = ["score_risk", "price_premium"]
