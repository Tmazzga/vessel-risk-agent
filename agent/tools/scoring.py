"""Risk score: vessel (0-50) + owner (0-50) = total (0-100). Higher = riskier.

Every weight and threshold lives in web/risk_config.json, which web/scoring.js
also reads, so the agent and the web form always give the same answer
(tests/test_scoring.py checks this). Keep the two files in sync: same
formulas, same rounding (half-up), same error messages.

Owner of the numbers in the config: Yuvraj (calibration).
"""
import json
import math
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parents[2] / "web" / "risk_config.json"

COUNT_FIELDS = ["psc_inspections", "psc_deficiencies", "psc_detentions",
                "owner_inspections", "owner_deficiencies", "owner_detentions"]


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


def _whole(v):
    """Parse a whole number. Returns (value, ok). Blank counts as 0."""
    if not _known(v):
        return 0, True
    if isinstance(v, bool):
        return 0, False
    if isinstance(v, str) and not re.fullmatch(r"\s*-?\d+(\.\d+)?\s*", v, re.ASCII):
        return 0, False
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0, False
    if not math.isfinite(f) or f != math.floor(f):
        return 0, False
    return int(f), True


def _truthy(v) -> bool:
    return v is True or v == 1 or (isinstance(v, str) and v.strip().lower() in ("true", "yes", "1"))


def canonical_type(vessel_type):
    """Map a vessel type to a model category. Returns (category, recognized)."""
    vt = config()["vessel"]["vessel_type"]
    if not _known(vessel_type):
        return "Other", False
    t = str(vessel_type).strip()
    if t in vt["points"]:
        return t, True
    hit = vt["aliases"].get(t.lower())
    return (hit, True) if hit else ("Other", False)


def validate_inputs(inp: dict, as_of_year: int) -> list[str]:
    """Impossible inputs. Same checks and messages as validateInputs() in web/scoring.js."""
    errors = []
    counts = {}
    for k in COUNT_FIELDS:
        n, ok = _whole(inp.get(k))
        if not ok:
            errors.append(f"{k} must be a whole number")
        elif n < 0:
            errors.append(f"{k} can't be negative")
        counts[k] = n
    for who in ("psc", "owner"):
        if counts[f"{who}_detentions"] > counts[f"{who}_inspections"]:
            errors.append(f"{who}_detentions can't exceed {who}_inspections")
    yb = inp.get("year_built")
    if _known(yb):
        y, ok = _whole(yb)
        lo = config()["limits"]["min_year_built"]
        if not ok:
            errors.append("year_built must be a whole number")
        elif y < lo or y > as_of_year:
            errors.append(f"year_built must be between {lo} and {as_of_year}")
    return errors


def score_vessel_part(inp: dict, as_of_year: int) -> dict:
    c = config()["vessel"]
    missing, notes, factors = [], [], {}

    # Age
    a = c["age"]
    if _known(inp.get("year_built")):
        age = as_of_year - _whole(inp["year_built"])[0]
        pts = a["max"] * _clamp01((age - a["min_years"]) / (a["full_years"] - a["min_years"]))
        detail = f"{age} years old"
    else:
        pts, detail = a["max"], "year built unknown, scored at max"
        missing.append("year_built")
    factors["age"] = {"label": "Vessel age", "points": r1(pts), "max": a["max"], "detail": detail}

    # PSC record with credibility weighting
    p = c["psc"]
    n = _whole(inp.get("psc_inspections"))[0]
    det = _whole(inp.get("psc_detentions"))[0]
    dfc = _whole(inp.get("psc_deficiencies"))[0]
    if n > 0:
        raw = (p["detention_weight"] * _clamp01((det / n) / p["detention_rate_full"])
               + p["deficiency_weight"] * _clamp01((dfc / n) / p["deficiencies_per_inspection_full"]))
    else:
        raw = 0.0
    z = n / (n + p["k"])
    factors["psc"] = {"label": "Vessel PSC record", "points": r1(p["max"] * (z * raw + (1 - z) * p["peer_index"])),
                      "max": p["max"],
                      "detail": f"{n} inspections, {dfc} deficiencies, {det} detentions; credibility {r2(z)}"}

    # Flag
    f = c["flag"]
    key = str(inp.get("flag_list") or "unknown").strip().lower()
    key = key if key in f["points"] else "unknown"
    if key == "unknown":
        missing.append("flag_list")
    factors["flag"] = {"label": "Flag", "points": f["points"][key], "max": f["max"], "detail": f"{key} list"}

    # Class society
    cs = c["class_society"]
    if not _known(inp.get("iacs_member")):
        key = "unknown"
        missing.append("iacs_member")
    else:
        key = "iacs" if _truthy(inp["iacs_member"]) else "non_iacs"
    factors["class_society"] = {"label": "Class society", "points": cs["points"][key], "max": cs["max"],
                                "detail": {"iacs": "IACS member", "non_iacs": "not IACS", "unknown": "unknown"}[key]}

    # Class status
    st = c["class_status"]
    key = str(inp.get("class_status") or "unknown").strip().lower()
    key = key if key in st["points"] else "unknown"
    if key == "unknown":
        missing.append("class_status")
    factors["class_status"] = {"label": "Class status", "points": st["points"][key], "max": st["max"],
                               "detail": st["labels"][key]}

    # Vessel type
    vt = c["vessel_type"]
    raw_type = inp.get("vessel_type")
    key, recognized = canonical_type(raw_type)
    if not _known(raw_type):
        missing.append("vessel_type")
        detail = "unknown, scored as Other"
    elif not recognized:
        notes.append(f"Vessel type '{str(raw_type).strip()}' is not in the model; scored as Other")
        detail = f"{str(raw_type).strip()}, scored as Other"
    else:
        detail = key
    factors["vessel_type"] = {"label": "Vessel type", "points": vt["points"][key], "max": vt["max"],
                              "detail": detail}

    score = r1(sum(x["points"] for x in factors.values()))
    return {"score": score, "max": c["max"], "factors": factors, "credibility_z": r2(z),
            "missing": missing, "notes": notes}


def score_owner_part(inp: dict) -> dict:
    c = config()["owner"]
    n = _whole(inp.get("owner_inspections"))[0]
    det = _whole(inp.get("owner_detentions"))[0]
    dfc = _whole(inp.get("owner_deficiencies"))[0]
    z = n / (n + c["k"])
    d, f = c["detention"], c["deficiency"]

    det_idx = _clamp01((det / n) / d["rate_full"]) if n else 0.0
    det_base = _clamp01(d["baseline_rate"] / d["rate_full"])
    dfc_idx = _clamp01((dfc / n) / f["per_inspection_full"]) if n else 0.0
    dfc_base = _clamp01(f["baseline_per_inspection"] / f["per_inspection_full"])
    none = "no fleet record, industry baseline"

    factors = {
        "fleet_detentions": {"label": "Owner fleet detentions",
                             "points": r1(d["max"] * (z * det_idx + (1 - z) * det_base)), "max": d["max"],
                             "detail": f"{det} detentions in {n} fleet inspections" if n else none},
        "fleet_deficiencies": {"label": "Owner fleet deficiencies",
                               "points": r1(f["max"] * (z * dfc_idx + (1 - z) * dfc_base)), "max": f["max"],
                               "detail": f"{dfc} deficiencies in {n} fleet inspections" if n else none},
    }
    return {"score": r1(sum(x["points"] for x in factors.values())), "max": c["max"],
            "factors": factors, "credibility_z": r2(z),
            "missing": [] if n else ["owner_fleet_record"]}


def score_risk(vessel_type=None, year_built=None, flag_list=None, iacs_member=None,
               class_status=None, psc_inspections=0, psc_deficiencies=0, psc_detentions=0,
               owner_inspections=0, owner_deficiencies=0, owner_detentions=0,
               sanctions_match=False, sanctions_possible=False, as_of_year=None) -> dict:
    """Full score: vessel part + owner part, recommendation band, and overrides.
    Returns {"error": ..., "errors": [...]} instead if any input is impossible."""
    cfg = config()
    inp = dict(locals())
    as_of_year = as_of_year or date.today().year
    errors = validate_inputs(inp, as_of_year)
    if errors:
        return {"error": "Invalid input: " + "; ".join(errors), "errors": errors}

    v = score_vessel_part(inp, as_of_year)
    o = score_owner_part(inp)
    total = r1(v["score"] + o["score"])

    rec = next(b["label"] for b in cfg["recommendation"]["bands"] if total < b["below"])
    overrides, notes = [], list(v["notes"])
    if _truthy(sanctions_match):
        overrides.append("Sanctions match on vessel or owner: automatic DECLINE")
    if str(class_status or "").strip().lower() == "suspended":
        overrides.append("Class suspended or withdrawn: hull cover requires class, automatic DECLINE")
    if overrides:
        rec = "DECLINE"
    elif _truthy(sanctions_possible) and rec in ("ACCEPT", "ACCEPT WITH CONDITIONS"):
        overrides.append("Possible sanctions match on owner name: a person must confirm, raised to REFER")
        rec = "REFER"
    if v["credibility_z"] < cfg["thin_data_z"]:
        notes.append("Thin vessel PSC record: score leans on the peer baseline")
    if o["credibility_z"] < cfg["thin_data_z"]:
        notes.append("Thin owner fleet record: score leans on the industry baseline")

    return {"total": total, "vessel_score": v["score"], "owner_score": o["score"],
            "vessel": v, "owner": o, "recommendation": rec, "overrides": overrides,
            "notes": notes, "missing": v["missing"] + o["missing"],
            "model_version": cfg["model_version"]}


def find_risk_levers(**inputs) -> dict:
    """Which single actionable change lowers the total score the most.
    Each lever in the config is applied alone; levers on unknown values are skipped."""
    base = score_risk(**inputs)
    if "error" in base:
        return base
    levers = []
    for opt in config()["levers"]["options"]:
        cur = inputs.get(opt["field"])
        if not _known(cur):
            continue
        norm = _truthy(cur) if isinstance(opt["to"], bool) else str(cur).strip().lower()
        if norm in opt["unless"]:
            continue
        r = score_risk(**{**inputs, opt["field"]: opt["to"]})
        cut = r1(base["total"] - r["total"])
        if cut > 0:
            levers.append({"change": opt["label"], "field": opt["field"], "to": opt["to"],
                           "new_total": r["total"], "reduction": cut,
                           "new_recommendation": r["recommendation"]})
    levers.sort(key=lambda x: -x["reduction"])
    return {"current_total": base["total"], "current_recommendation": base["recommendation"],
            "levers": levers, "model_version": base["model_version"]}


def price_premium(score: float, insured_value_usd: float) -> dict:
    p = config()["pricing"]
    value = float(insured_value_usd)
    if not math.isfinite(value) or value <= 0:
        return {"error": "insured_value_usd must be greater than 0"}
    relativity = p["relativity_intercept"] + p["relativity_slope"] * float(score)
    expected_loss = p["base_rate"] * value * relativity
    premium = expected_loss * (1 + p["loading"])
    return {
        "relativity": r2(relativity),
        "expected_loss_usd": r0(expected_loss),
        "premium_usd": r0(premium),
        "rate_on_value_pct": math.floor(100 * premium / value * 1000 + 0.5) / 1000,
        "model_version": config()["model_version"],
    }
