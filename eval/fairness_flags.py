"""Does the flag factor treat ships unfairly? (governance, owner: Robert)

    python -m eval.fairness_flags           # ships in the data tools (real or demo)
    python -m eval.fairness_flags --demo    # synthetic cohort, tests the script only

The flag score comes from the Paris MOU list, which rates flag STATES as a
group, not individual ships. So a well-run ship on a grey-list flag is
penalized for other ships' records. This script re-scores every ship as if
it flew a white-list flag and measures:

  - how many points the flag adds, by flag list
  - how many recommendations get worse because of the flag alone
  - how often that happens to ships with a clean record of their own
    (no detentions and enough inspections to trust it)

Writes an HTML report with a chart.
"""
import argparse
from pathlib import Path

from agent.tools.scoring import config, score_risk
from eval import cohort, report

OUT = Path(__file__).resolve().parent / "reports" / "flag_fairness.html"
ORDER = ["ACCEPT", "ACCEPT WITH CONDITIONS", "REFER", "DECLINE"]
LISTS = ["white", "grey", "black"]


def clean_record(inp, z_min):
    n = int(inp.get("psc_inspections") or 0)
    k = config()["vessel"]["psc"]["k"]
    return int(inp.get("psc_detentions") or 0) == 0 and n / (n + k) >= z_min


def analyze(ships):
    z_min = config()["thin_data_z"]
    groups = {fl: [] for fl in LISTS}
    for s in ships:
        fl = str(s["inputs"].get("flag_list") or "").lower()
        if fl not in groups:
            continue
        actual = score_risk(**s["inputs"])
        if "error" in actual:
            continue
        white = score_risk(**{**s["inputs"], "flag_list": "white"})
        groups[fl].append({
            "name": s["name"], "total": actual["total"], "flag_points": actual["vessel"]["factors"]["flag"]["points"],
            "rec": actual["recommendation"], "rec_white": white["recommendation"],
            "worse": ORDER.index(actual["recommendation"]) > ORDER.index(white["recommendation"]),
            "clean": clean_record(s["inputs"], z_min),
        })
    rows = []
    for fl in LISTS:
        g = groups[fl]
        clean = [x for x in g if x["clean"]]
        rows.append({
            "flag_list": fl, "ships": len(g),
            "avg_total": sum(x["total"] for x in g) / len(g) if g else 0.0,
            "avg_flag_points": sum(x["flag_points"] for x in g) / len(g) if g else 0.0,
            "worse": sum(x["worse"] for x in g),
            "worse_pct": 100 * sum(x["worse"] for x in g) / len(g) if g else 0.0,
            "clean": len(clean), "clean_worse": sum(x["worse"] for x in clean),
            "examples": [x for x in clean if x["worse"]][:5],
        })
    return rows


def summary(rows):
    hit = sum(r["worse"] for r in rows)
    clean_hit = sum(r["clean_worse"] for r in rows)
    ships = sum(r["ships"] for r in rows)
    if not hit:
        return f"The flag factor changed no recommendations among {ships} ships."
    return (f"The flag factor alone made the recommendation worse for {hit} of {ships} ships; "
            f"{clean_hit} of those have a clean detention record of their own. "
            f"That is the fairness question: should a ship pay for its flag state's average?")


def build_report(rows, source, synthetic):
    fmt = lambda v, axis=False: f"{v:.0f}%"
    chart_rows = [{"label": f"{r['flag_list'].title()} list ({r['ships']} ships)", "value": r["worse_pct"],
                   "tip": f"{r['flag_list'].title()} list: {r['worse']} of {r['ships']} ships "
                          f"({r['worse_pct']:.0f}%) get a worse recommendation because of the flag"} for r in rows]
    chart = report.column_chart(chart_rows, fmt, "Ships with a worse recommendation due to flag alone",
                                "Share of ships whose recommendation worsens because of their flag list")
    tbl = report.table(["Flag list", "Ships", "Avg total", "Avg flag points", "Worse due to flag",
                        "Clean-record ships", "Clean and worse"],
                       [[r["flag_list"].title(), r["ships"], f"{r['avg_total']:.1f}", f"{r['avg_flag_points']:.1f}",
                         r["worse"], r["clean"], r["clean_worse"]] for r in rows], numeric_cols=(1, 2, 3, 4, 5, 6))
    examples = [x for r in rows for x in r["examples"]][:8]
    ex = ("<ul>" + "".join(f"<li>{report.e(x['name'])}: {report.e(x['rec'])} on its flag, "
                           f"{report.e(x['rec_white'])} on a white-list flag (score {x['total']})</li>"
                           for x in examples) + "</ul>") if examples else "<p>None.</p>"
    body = (f'<div class="card"><h2>Recommendations made worse by the flag factor</h2>'
            f'<p class="lede">{report.e(summary(rows))}</p>{chart}'
            f'<details open><summary>Table view</summary>{tbl}</details>'
            f'<p class="foot">Each ship is re-scored with a white-list flag and nothing else changed. '
            f'"Clean record" = no detentions and enough inspections to trust it (credibility at least '
            f'{config()["thin_data_z"]}).</p></div>'
            f'<div class="card"><h2>Clean-record ships pushed into a worse band</h2>{ex}</div>'
            f'<div class="card"><h2>Options to discuss</h2><ul>'
            f'<li>Keep the flag factor: flag-state oversight does affect risk, and the Paris MOU list is an industry standard.</li>'
            f'<li>Shrink it once a ship has its own trusted record (e.g. scale flag points by 1 − credibility).</li>'
            f'<li>Cap it so the flag alone can never move a ship across a recommendation band.</li></ul></div>')
    return report.page("Flag fairness check", f"Data: {source}.", body,
                       banner="SYNTHETIC DATA: this only tests that the script works. These numbers are not findings."
                       if synthetic else None)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--demo", action="store_true", help="run on a synthetic cohort")
    p.add_argument("--out", default=str(OUT))
    a = p.parse_args()
    if a.demo:
        ships, source = cohort.synthetic(), "synthetic cohort"
    else:
        ships, mode = cohort.real()
        source = "fictional demo ships" if mode == "sample" else "data/processed vessel data"
    rows = analyze(ships)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_report(rows, source, a.demo))
    print(summary(rows))
    print(f"Report: {out}")


if __name__ == "__main__":
    main()
