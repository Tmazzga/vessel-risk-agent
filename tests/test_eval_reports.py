"""Tests for the validation and flag-fairness scripts (synthetic data only)."""
from eval import cohort, fairness_flags, validate_scores
from eval.report import _axis


def test_spearman_basics():
    assert validate_scores.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert validate_scores.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0


def test_validation_quartiles_cover_every_ship():
    ships = cohort.synthetic(n=120)
    for s in ships:
        s["score"] = validate_scores.score_risk(**s["inputs"])
    ships = [s for s in ships if "error" not in s["score"]]
    a = validate_scores.analyze(ships)
    assert sum(r["ships"] for r in a["rows"]) == len(ships)
    assert all(r["lo"] <= r["rate"] <= r["hi"] for r in a["rows"])
    scores = [r["score_lo"] for r in a["rows"]]
    assert scores == sorted(scores)
    html = validate_scores.build_report(a, "synthetic", synthetic=True)
    assert "SYNTHETIC DATA" in html and "<svg" in html and "<table>" in html


def test_verdict_refuses_to_judge_tiny_samples():
    a = {"events": 5, "ratio": 3.0, "ratio_ci": (1.5, 6.0)}
    assert validate_scores.verdict(a).startswith("Too few incidents")


def test_fairness_white_flags_never_penalized():
    rows = fairness_flags.analyze(cohort.synthetic(n=200))
    white = next(r for r in rows if r["flag_list"] == "white")
    assert white["worse"] == 0 and white["avg_flag_points"] == 0
    assert all(r["clean_worse"] <= r["worse"] <= r["ships"] for r in rows)
    html = fairness_flags.build_report(rows, "synthetic", synthetic=True)
    assert "SYNTHETIC DATA" in html and "Table view" in html


def test_axis_ticks_are_clean():
    top, ticks = _axis(27.3)
    assert top >= 27.3 and ticks[0] == 0 and len(ticks) <= 6
