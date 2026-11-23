"""Tests for the 50/50 risk score, and that the web form (web/scoring.js)
gives exactly the same answers as the agent's Python tool."""
import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from agent.tools.scoring import config, price_premium, score_risk

ROOT = Path(__file__).resolve().parents[1]
CLEAN = dict(vessel_type="Container Ship", year_built=2022, flag_list="white", iacs_member=True,
             class_status="in_class", psc_inspections=20, psc_deficiencies=5, psc_detentions=0,
             owner_inspections=200, owner_deficiencies=150, owner_detentions=0,
             sanctions_match=False, as_of_year=2026)


def test_halves_add_to_total_and_stay_in_range():
    r = score_risk(**CLEAN)
    assert 0 <= r["vessel_score"] <= 50 and 0 <= r["owner_score"] <= 50
    assert r["total"] == round(r["vessel_score"] + r["owner_score"], 1)
    assert r["recommendation"] == "ACCEPT"


def test_worst_case_hits_both_maximums():
    worst = dict(CLEAN, vessel_type="Ro-Ro", year_built=1990, flag_list="black", iacs_member=False,
                 class_status="suspended", psc_inspections=500, psc_deficiencies=5000, psc_detentions=500,
                 owner_inspections=10000, owner_deficiencies=100000, owner_detentions=10000)
    r = score_risk(**worst)
    assert r["vessel_score"] <= 50 and r["owner_score"] <= 50
    assert r["vessel_score"] > 49 and r["owner_score"] > 49
    assert r["recommendation"] == "DECLINE"


def test_factor_maxes_sum_to_50():
    v = config()["vessel"]
    assert sum(v[k]["max"] for k in ("age", "psc", "flag", "class_society", "class_status", "vessel_type")) == 50
    o = config()["owner"]
    assert o["detention"]["max"] + o["deficiency"]["max"] == 50


def test_sanctions_and_suspended_class_force_decline():
    assert score_risk(**dict(CLEAN, sanctions_match=True))["recommendation"] == "DECLINE"
    r = score_risk(**dict(CLEAN, class_status="suspended"))
    assert r["recommendation"] == "DECLINE" and r["overrides"]


def test_bad_owner_raises_owner_score_only():
    base = score_risk(**CLEAN)
    bad = score_risk(**dict(CLEAN, owner_detentions=30))
    assert bad["owner_score"] > base["owner_score"]
    assert bad["vessel_score"] == base["vessel_score"]


def test_unknowns_are_reported_and_scored_cautiously():
    r = score_risk(vessel_type=None, year_built=None, flag_list=None, iacs_member=None,
                   class_status=None, as_of_year=2026)
    assert set(r["missing"]) >= {"year_built", "flag_list", "iacs_member", "class_status",
                                 "vessel_type", "owner_fleet_record"}
    assert r["vessel"]["factors"]["age"]["points"] == 10
    assert len(r["notes"]) == 2  # thin vessel and owner data


def test_thin_record_leans_on_baseline():
    one_bad = score_risk(**dict(CLEAN, psc_inspections=1, psc_detentions=1))
    many_bad = score_risk(**dict(CLEAN, psc_inspections=40, psc_detentions=40))
    assert one_bad["vessel"]["factors"]["psc"]["points"] < many_bad["vessel"]["factors"]["psc"]["points"]


def _random_case(rng):
    insp = rng.randint(0, 40)
    o_insp = rng.choice([0, rng.randint(1, 400)])
    pick = lambda xs: rng.choice(xs)
    return {
        "vessel_type": pick([None, "Container Ship", "Tanker", "Bulk Carrier", "General Cargo", "Ro-Ro", "Other", "Yacht"]),
        "year_built": pick([None, rng.randint(1975, 2026)]),
        "flag_list": pick([None, "white", "grey", "black", "WHITE"]),
        "iacs_member": pick([None, True, False]),
        "class_status": pick([None, "in_class", "conditions", "overdue_survey", "suspended"]),
        "psc_inspections": insp, "psc_deficiencies": rng.randint(0, 80),
        "psc_detentions": rng.randint(0, insp),
        "owner_inspections": o_insp, "owner_deficiencies": rng.randint(0, 3 * o_insp + 1),
        "owner_detentions": rng.randint(0, o_insp),
        "sanctions_match": rng.random() < 0.1,
        "insured_value_usd": pick([None, rng.randint(1, 80) * 1_000_000]),
        "as_of_year": 2026,
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_web_form_matches_python_exactly(tmp_path):
    rng = random.Random(7)
    cases = [dict(CLEAN, insured_value_usd=25_000_000)] + [_random_case(rng) for _ in range(300)]
    f = tmp_path / "cases.json"
    f.write_text(json.dumps(cases))
    js = json.loads(subprocess.run(["node", str(ROOT / "tests" / "js_parity.mjs"), str(f)],
                                   capture_output=True, text=True, check=True).stdout)
    for case, j in zip(cases, js):
        args = {k: v for k, v in case.items() if k != "insured_value_usd"}
        py = score_risk(**args)
        for key in ("total", "vessel_score", "owner_score", "recommendation", "overrides", "notes", "missing"):
            assert py[key] == j["score"][key], (key, case)
        for part in ("vessel", "owner"):
            for name, fac in py[part]["factors"].items():
                assert fac["points"] == j["score"][part]["factors"][name]["points"], (part, name, case)
        if case["insured_value_usd"] and j["price"]:
            pp = price_premium(py["total"], case["insured_value_usd"])
            for key in ("relativity", "expected_loss_usd", "premium_usd", "rate_on_value_pct"):
                assert pp[key] == j["price"][key], (key, case)
