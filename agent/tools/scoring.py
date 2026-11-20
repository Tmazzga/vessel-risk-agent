"""Risk score: vessel (0-50) + owner (0-50) = total (0-100). Higher = riskier.

Every weight and threshold lives in web/risk_config.json, which web/scoring.js
also reads, so the agent and the web form always give the same answer
(tests/test_scoring.py checks this). Keep the two files in sync: same
formulas, same rounding (half-up to 1 decimal).

Owner of the numbers in the config: Yuvraj (calibration).
"""
import json
import math
from datetime import date
from functools import lru_cache
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parents[2] / "web" / "risk_config.json"


@lru_cache(maxsize=1)
def config() -> dict:
    return json.loads(CONFIG_FILE.read_text())


def r1(x: float) -> float:
    """Round half-up to 1 decimal (matches Math.round in JS; Python's round() is half-even)."""
    return math.floor(x * 10 + 0.5) / 10


def r2(x: float) -> float:
    return math.floor(x * 100 + 0.5) / 100


def r0(x: float) -> int:
    return int(math.floor(x + 0.5))


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _known(v) -> bool:
    return v is not None and v != ""


def score_vessel_part(vessel_type=None, year_built=None, flag_list=None, iacs_member=None,
                      class_status=None, psc_inspections=0, psc_deficiencies=0,
                      psc_detentions=0, as_of_year=None) -> dict:
    c = config()["vessel"]
    as_of_year = as_of_year or date.today().year
    missing, factors = [], {}

    # Age
    a = c["age"]
    if _known(year_built):
        age = as_of_year - int(year_built)
        pts = a["max"] * _clamp01((age - a["min_years"]) / (a["full_years"] - a["min_years"]))
        detail = f"{age} years old"
    else:
        pts, detail = a["max"], "year built unknown, scored at max"
        missing.append("year_built")
    factors["age"] = {"label": "Vessel age", "points": r1(pts), "max": a["max"], "detail": detail}

    # PSC record with credibility weighting
    p = c["psc"]
    n = int(psc_inspections or 0)
    det, dfc = int(psc_detentions or 0), int(psc_deficiencies or 0)
    if n > 0:
        raw = (p["detention_weight"] * _clamp01((det / n) / p["detention_rate_full"])
               + p["deficiency_weight"] * _clamp01((dfc / n) / p["deficiencies_per_inspection_full"]))
    else:
        raw = 0.0
    z = n / (n + p["k"])
    pts = p["max"] * (z * raw + (1 - z) * p["peer_index"])
    factors["psc"] = {"label": "Vessel PSC record", "points": r1(pts), "max": p["max"],
                      "detail": f"{n} inspections, {dfc} deficiencies, {det} detentions; credibility {r2(z)}"}

    # Flag
    f = c["flag"]
    key = (flag_list or "unknown").strip().lower()
    key = key if key in f["points"] else "unknown"
    if key == "unknown":
        missing.append("flag_list")
    factors["flag"] = {"label": "Flag", "points": f["points"][key], "max": f["max"], "detail": f"{key} list"}

    # Class society
    cs = c["class_society"]
    if iacs_member is None or iacs_member == "":
        key = "unknown"
        missing.append("iacs_member")
    else:
        key = "iacs" if iacs_member in (True, "true", "yes", 1) else "non_iacs"
    factors["class_society"] = {"label": "Class society", "points": cs["points"][key], "max": cs["max"],
                                "detail": {"iacs": "IACS member", "non_iacs": "not IACS", "unknown": "unknown"}[key]}

    # Class status
    st = c["class_status"]
    key = (class_status or "unknown").strip().lower()
    key = key if key in st["points"] else "unknown"
    if key == "unknown":
        missing.append("class_status")
    factors["class_status"] = {"label": "Class status", "points": st["points"][key], "max": st["max"], "detail": st["labels"][key]}

    # Vessel type
    vt = c["vessel_type"]
    key = vessel_type if vessel_type in vt["points"] else "Other"
    if not _known(vessel_type):
        missing.append("vessel_type")
    factors["vessel_type"] = {"label": "Vessel type", "points": vt["points"][key], "max": vt["max"], "detail": key}

    score = r1(sum(f["points"] for f in factors.values()))
    return {"score": score, "max": c["max"], "factors": factors,
            "credibility_z": r2(z), "missing": missing}


def score_owner_part(owner_inspections=0, owner_deficiencies=0, owner_detentions=0) -> dict:
    c = config()["owner"]
    n = int(owner_inspections or 0)
    det, dfc = int(owner_detentions or 0), int(owner_deficiencies or 0)
    z = n / (n + c["k"])
    d, f = c["detention"], c["deficiency"]

    det_idx = _clamp01((det / n) / d["rate_full"]) if n else 0.0
    det_base = _clamp01(d["baseline_rate"] / d["rate_full"])
    dfc_idx = _clamp01((dfc / n) / f["per_inspection_full"]) if n else 0.0
    dfc_base = _clamp01(f["baseline_per_inspection"] / f["per_inspection_full"])

    factors = {
        "fleet_detentions": {"label": "Owner fleet detentions", "points": r1(d["max"] * (z * det_idx + (1 - z) * det_base)), "max": d["max"],
                             "detail": f"{det} detentions in {n} fleet inspections" if n else "no fleet record, industry baseline"},
        "fleet_deficiencies": {"label": "Owner fleet deficiencies", "points": r1(f["max"] * (z * dfc_idx + (1 - z) * dfc_base)), "max": f["max"],
                               "detail": f"{dfc} deficiencies in {n} fleet inspections" if n else "no fleet record, industry baseline"},
    }
    return {"score": r1(sum(x["points"] for x in factors.values())), "max": c["max"],
            "factors": factors, "credibility_z": r2(z),
            "missing": [] if n else ["owner_fleet_record"]}


def score_risk(vessel_type=None, year_built=None, flag_list=None, iacs_member=None,
               class_status=None, psc_inspections=0, psc_deficiencies=0, psc_detentions=0,
               owner_inspections=0, owner_deficiencies=0, owner_detentions=0,
               sanctions_match=False, as_of_year=None) -> dict:
    """Full score: vessel part + owner part, recommendation band, and overrides."""
    cfg = config()
    v = score_vessel_part(vessel_type, year_built, flag_list, iacs_member, class_status,
                          psc_inspections, psc_deficiencies, psc_detentions, as_of_year)
    o = score_owner_part(owner_inspections, owner_deficiencies, owner_detentions)
    total = r1(v["score"] + o["score"])

    rec = next(b["label"] for b in cfg["recommendation"]["bands"] if total < b["below"])
    overrides, notes = [], []
    if sanctions_match in (True, "true", 1):
        overrides.append("Sanctions match on vessel or owner: automatic DECLINE")
    if (class_status or "").strip().lower() == "suspended":
        overrides.append("Class suspended or withdrawn: hull cover requires class, automatic DECLINE")
    if overrides:
        rec = "DECLINE"
    if v["credibility_z"] < cfg["thin_data_z"]:
        notes.append("Thin vessel PSC record: score leans on the peer baseline")
    if o["credibility_z"] < cfg["thin_data_z"]:
        notes.append("Thin owner fleet record: score leans on the industry baseline")

    return {"total": total, "vessel_score": v["score"], "owner_score": o["score"],
            "vessel": v, "owner": o, "recommendation": rec, "overrides": overrides,
            "notes": notes, "missing": v["missing"] + o["missing"],
            "model_version": cfg["model_version"]}


def price_premium(score: float, insured_value_usd: float) -> dict:
    p = config()["pricing"]
    relativity = p["relativity_intercept"] + p["relativity_slope"] * float(score)
    expected_loss = p["base_rate"] * float(insured_value_usd) * relativity
    premium = expected_loss * (1 + p["loading"])
    return {
        "relativity": math.floor(relativity * 100 + 0.5) / 100,
        "expected_loss_usd": r0(expected_loss),
        "premium_usd": r0(premium),
        "rate_on_value_pct": math.floor(100 * premium / float(insured_value_usd) * 1000 + 0.5) / 1000,
        "model_version": config()["model_version"],
    }
