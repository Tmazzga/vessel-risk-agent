"""Do higher risk scores predict more incidents? (validation, owner: Yuvraj)

    python -m eval.validate_scores --outcomes data/processed/outcomes.csv
    python -m eval.validate_scores --demo          # synthetic data, tests the script only

outcomes.csv columns: imo, events, exposure_years
  events          = incidents in the follow-up window AFTER the data was pulled
                    (USCG casualties, or PSC detentions as a more frequent proxy)
  exposure_years  = how long each ship was observed in that window

Splits ships into four equal groups by total score and compares incident
rates, with 95% bootstrap intervals. Writes an HTML report with a chart.
"""
import argparse
import csv
import random
import statistics
import sys
from pathlib import Path

from agent.tools.scoring import score_risk
from eval import cohort, report

OUT = Path(__file__).resolve().parent / "reports" / "validation.html"
B = 2000  # bootstrap resamples


def _rate(ships):
    exp = sum(s["exposure_years"] for s in ships)
    return 100 * sum(s["events"] for s in ships) / exp if exp else 0.0


def _ci(samples):
    s = sorted(samples)
    return s[int(0.025 * len(s))], s[int(0.975 * len(s)) - 1]


def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(xs, ys):
    if len(xs) < 3:
        return float("nan")
    rx, ry = _ranks(xs), _ranks(ys)
    try:
        return statistics.correlation(rx, ry)
    except statistics.StatisticsError:
        return float("nan")


def quartiles(ships):
    s = sorted(ships, key=lambda x: x["score"]["total"])
    n = len(s)
    return [s[round(i * n / 4):round((i + 1) * n / 4)] for i in range(4)]


def analyze(ships, seed=3):
    rng = random.Random(seed)
    groups = quartiles(ships)
    rows = []
    for i, g in enumerate(groups):
        boots = [_rate([rng.choice(g) for _ in g]) for _ in range(B)] if g else [0.0]
        lo, hi = _ci(boots)
        rows.append({"group": f"Q{i + 1}", "ships": len(g), "events": sum(s["events"] for s in g),
                     "exposure": round(sum(s["exposure_years"] for s in g), 1),
                     "score_lo": g[0]["score"]["total"] if g else None,
                     "score_hi": g[-1]["score"]["total"] if g else None,
                     "rate": _rate(g), "lo": lo, "hi": hi})
    q1, q4 = groups[0], groups[-1]
    ratios = []
    for _ in range(B):
        a = _rate([rng.choice(q1) for _ in q1])
        b = _rate([rng.choice(q4) for _ in q4])
        if a > 0:
            ratios.append(b / a)
    point = rows[-1]["rate"] / rows[0]["rate"] if rows[0]["rate"] > 0 else float("inf")
    r_lo, r_hi = _ci(ratios) if len(ratios) > 100 else (float("nan"), float("nan"))
    per_ship = [s["events"] / s["exposure_years"] for s in ships]
    corr = {k: spearman([s["score"][k] for s in ships], per_ship)
            for k in ("total", "vessel_score", "owner_score")}
    return {"rows": rows, "ratio": point, "ratio_ci": (r_lo, r_hi), "spearman": corr,
            "ships": len(ships), "events": sum(s["events"] for s in ships)}


def verdict(a):
    lo = a["ratio_ci"][0]
    if a["events"] < 20:
        return f"Too few incidents ({a['events']}) to judge. Use a longer window or PSC detentions as the outcome."
    if lo == lo and lo > 1:
        return (f"Ships in the highest-score quarter had {a['ratio']:.1f}x the incident rate of the lowest quarter, "
                f"and the 95% interval ({lo:.1f}x to {a['ratio_ci'][1]:.1f}x) stays above 1.")
    return (f"No clear evidence yet: the highest-score quarter's rate is {a['ratio']:.1f}x the lowest, "
            f"but the 95% interval includes 1.")


def load_outcomes(path):
    with open(path, newline="") as f:
        return {r["imo"].strip(): (int(r["events"]), float(r["exposure_years"])) for r in csv.DictReader(f)}


def build_report(a, source, synthetic):
    fmt = lambda v, axis=False: f"{v:.0f}" if axis else f"{v:.1f}"
    rows = [{"label": f"{r['group']}  ({r['score_lo']:.0f}–{r['score_hi']:.0f})", "value": r["rate"],
             "lo": r["lo"], "hi": r["hi"],
             "tip": f"{r['group']}: {r['rate']:.1f} per 100 vessel-years (95% CI {r['lo']:.1f}–{r['hi']:.1f}), "
                    f"{r['events']} incidents, {r['ships']} ships"} for r in a["rows"]]
    chart = report.column_chart(rows, fmt, "Incidents per 100 vessel-years",
                                "Incident rate by risk-score quarter")
    sp = a["spearman"]
    stats = "".join([
        report.stat("Highest vs lowest quarter", f"{a['ratio']:.1f}x",
                    f"95% CI {a['ratio_ci'][0]:.1f}x–{a['ratio_ci'][1]:.1f}x"),
        report.stat("Rank correlation, total", f"{sp['total']:.2f}", "Spearman, score vs incident rate"),
        report.stat("Vessel half alone", f"{sp['vessel_score']:.2f}", "Spearman"),
        report.stat("Owner half alone", f"{sp['owner_score']:.2f}", "Spearman"),
    ])
    tbl = report.table(["Quarter", "Score range", "Ships", "Incidents", "Vessel-years", "Rate /100 yrs", "95% CI"],
                       [[r["group"], f"{r['score_lo']}–{r['score_hi']}", r["ships"], r["events"], r["exposure"],
                         f"{r['rate']:.1f}", f"{r['lo']:.1f}–{r['hi']:.1f}"] for r in a["rows"]],
                       numeric_cols=(2, 3, 4, 5, 6))
    body = (f'<div class="stats">{stats}</div>'
            f'<div class="card"><h2>Incident rate by risk-score quarter</h2>'
            f'<p class="lede">{report.e(verdict(a))}</p>{chart}'
            f'<details open><summary>Table view</summary>{tbl}</details>'
            f'<p class="foot">Quarters are equal-sized groups of ships sorted by total score; Q4 is the riskiest. '
            f'Whiskers are 95% bootstrap intervals ({B} resamples).</p></div>')
    return report.page("Does the risk score predict incidents?",
                       f"{a['ships']} ships, {a['events']} incidents. Data: {source}.", body,
                       banner="SYNTHETIC DATA: this only tests that the script works. These numbers are not findings."
                       if synthetic else None)


def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--outcomes", help="CSV with imo, events, exposure_years")
    g.add_argument("--demo", action="store_true", help="run on a synthetic cohort")
    p.add_argument("--out", default=str(OUT))
    a = p.parse_args()

    if a.demo:
        ships, source = cohort.synthetic(), "synthetic cohort"
    else:
        outcomes = load_outcomes(a.outcomes)
        base, mode = cohort.real()
        ships = []
        for s in base:
            if s["imo"] in outcomes:
                s["events"], s["exposure_years"] = outcomes[s["imo"]]
                ships.append(s)
        source = f"{mode} vessel data + {a.outcomes}"
        print(f"{len(ships)} of {len(base)} ships have outcomes")

    scored, skipped = [], 0
    for s in ships:
        s["score"] = score_risk(**s["inputs"])
        if "error" in s["score"]:
            skipped += 1
        elif s["exposure_years"] > 0:
            scored.append(s)
    if skipped:
        print(f"skipped {skipped} ships with impossible inputs (fix them with pipeline.validate_vessels)")
    if len(scored) < 8:
        sys.exit("Need at least 8 scored ships with outcomes.")

    result = analyze(scored)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_report(result, source, a.demo))
    print(verdict(result))
    print(f"Report: {out}")


if __name__ == "__main__":
    main()
