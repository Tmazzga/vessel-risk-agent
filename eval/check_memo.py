"""Automated memo check (supports the evaluation part, owner: Robert).

Checks two things for every agent memo:
  1. Traceability: every number in the memo appears in the tool trace
     (a tool result, or a tool input such as a what-if value), allowing for
     rounding to the decimals shown and comma/percent/$ formatting.
  2. Citations: every line that states a number cites a tool in [brackets].

    python -m eval.check_memo                  # checks web/demo.json
    python -m eval.check_memo path/to/runs.json --csv eval/auto_check.csv

This catches made-up or mistyped numbers. It does NOT judge whether the
recommendation is sensible; that's still the human rubric (memo_rubric.md).
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

DEFAULT = Path(__file__).resolve().parents[1] / "web" / "demo.json"

# A number: optional $, digits with optional commas, optional decimals, optional %.
NUM_RE = re.compile(r"(?<![\w.])\$?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?%?(?![\w])")
# One or more tool names in brackets: [score_risk], [get_psc_history, score_risk],
# or a tool plus a note: [score_risk input].
CITE_RE = re.compile(r"\[[a-z_]+(?: [a-z ]+)?(?:\s*,\s*[a-z_]+(?: [a-z ]+)?)*\]")


def _collect(obj, out: list):
    """All numeric values anywhere in a tool input/output, including numbers in strings."""
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, str):
        out += [float(m.group(0).replace(",", "")) for m in re.finditer(r"\d[\d,]*\.?\d*", obj)
                if m.group(0).replace(",", "").replace(".", "").isdigit()]
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect(v, out)


def trace_values(events: list) -> list[float]:
    vals = []
    for e in events:
        _collect(e.get("output") if e["event"] == "tool_result" else e.get("input"), vals)
    return vals


def _matches(shown: float, decimals: int, values: list[float]) -> bool:
    return any(round(v, decimals) == shown for v in values)


def numbers_in(line: str):
    # Skip the fixed scales in "RISK SCORE: 62.3/100 (vessel 30.1/50 + owner 32.2/50)".
    line = re.sub(r"/\s*(100|50)\b", "", line)
    for m in NUM_RE.finditer(line):
        whole, dec = m.group(1).replace(",", ""), m.group(2)
        yield m.group(0), float(f"{whole}.{dec}" if dec else whole), len(dec or "")


def check(memo: str, events: list, request: str = "") -> dict:
    values = trace_values(events)
    request_nums = {float(n) for n in re.findall(r"\d+", request)}
    untraced, uncited, total = [], [], 0
    for line in memo.splitlines():
        found = False
        for text, val, dec in numbers_in(line):
            total += 1
            found = True
            if not (_matches(val, dec, values) or val in request_nums):
                untraced.append({"number": text, "line": line.strip()})
        if found and not CITE_RE.search(line):
            uncited.append(line.strip())
    return {"numbers": total, "untraced": untraced, "uncited_lines": uncited,
            "pass": not untraced and not uncited}


def _exchanges(run: dict):
    yield run.get("request", ""), run["events"], run["memo"]
    for f in run.get("followups", []):
        # a follow-up can cite numbers from the first answer too
        yield f["question"], run["events"] + f["events"], f["memo"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("runs", nargs="?", default=str(DEFAULT))
    p.add_argument("--csv", help="also write per-memo results to this CSV")
    a = p.parse_args()

    runs = json.loads(Path(a.runs).read_text())["runs"]
    rows, failed = [], 0
    for run in runs:
        for i, (req, events, memo) in enumerate(_exchanges(run)):
            r = check(memo, events, req)
            label = f"{run['name']} ({run['imo']})" + (f" follow-up {i}" if i else "")
            status = "PASS" if r["pass"] else "FAIL"
            failed += not r["pass"]
            print(f"{status}  {label}: {r['numbers']} numbers, {len(r['untraced'])} untraced, "
                  f"{len(r['uncited_lines'])} uncited lines")
            for u in r["untraced"]:
                print(f"      untraced {u['number']!r} in: {u['line']}")
            for line in r["uncited_lines"]:
                print(f"      no citation: {line}")
            rows.append({"imo": run["imo"], "exchange": i, "mode": run.get("mode", ""),
                         "numbers": r["numbers"], "untraced": len(r["untraced"]),
                         "uncited_lines": len(r["uncited_lines"]), "pass": r["pass"]})

    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    print(f"\n{len(rows) - failed}/{len(rows)} memos passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
