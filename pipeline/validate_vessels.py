"""Check data/processed/vessels.csv before committing it (owner: Ty).

    python -m pipeline.validate_vessels
    python -m pipeline.validate_vessels --file some_other.csv

Catches typos from hand entry: bad IMO numbers (check digit), missing
required fields, impossible values, and duplicates. Exits 1 on errors.
"""
import argparse
import csv
import sys
from datetime import date
from pathlib import Path

DEFAULT = Path(__file__).resolve().parents[1] / "data" / "processed" / "vessels.csv"

COLUMNS = ["imo", "name", "type", "year_built", "flag", "flag_list", "class_society",
           "iacs_member", "gross_tonnage", "owner", "insured_value_usd",
           "psc_inspections", "psc_deficiencies", "psc_detentions", "psc_last_inspection",
           "source", "date_pulled"]
REQUIRED = ["imo", "name", "type", "year_built", "flag", "flag_list", "iacs_member",
            "psc_inspections", "psc_deficiencies", "psc_detentions"]


def imo_valid(imo: str) -> bool:
    """IMO check digit: first 6 digits weighted 7..2; sum's last digit = 7th digit."""
    if len(imo) != 7 or not imo.isdigit():
        return False
    total = sum(int(d) * w for d, w in zip(imo[:6], range(7, 1, -1)))
    return total % 10 == int(imo[6])


def check_row(r: dict) -> list[str]:
    errs = [f"missing {c}" for c in REQUIRED if not (r.get(c) or "").strip()]
    imo = (r.get("imo") or "").strip()
    if imo and not imo_valid(imo):
        errs.append(f"IMO {imo} fails the check digit (typo?)")
    if (r.get("flag_list") or "").strip().lower() not in ("white", "grey", "black", ""):
        errs.append("flag_list must be white, grey, or black")
    if (r.get("iacs_member") or "").strip().lower() not in ("true", "false", "yes", "no", ""):
        errs.append("iacs_member must be true or false")
    try:
        yb = int(r.get("year_built") or 0)
        if yb and not 1950 <= yb <= date.today().year:
            errs.append(f"year_built {yb} looks wrong")
    except ValueError:
        errs.append("year_built is not a number")
    try:
        ins = int(r.get("psc_inspections") or 0)
        det = int(r.get("psc_detentions") or 0)
        int(r.get("psc_deficiencies") or 0)
        if det > ins:
            errs.append("more detentions than inspections")
    except ValueError:
        errs.append("PSC counts must be whole numbers")
    return errs


def validate(path: Path) -> list[str]:
    problems, seen = [], set()
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        missing_cols = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing_cols:
            return [f"header is missing columns: {', '.join(missing_cols)}"]
        for line, r in enumerate(reader, start=2):
            imo = (r.get("imo") or "").strip()
            if imo in seen:
                problems.append(f"line {line}: duplicate IMO {imo}")
            seen.add(imo)
            problems += [f"line {line} ({r.get('name') or imo}): {e}" for e in check_row(r)]
    return problems


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--file", default=str(DEFAULT))
    path = Path(p.parse_args().file)
    if not path.exists():
        sys.exit(f"{path} not found. Copy data/processed/vessels_template.csv to start.")
    problems = validate(path)
    for msg in problems:
        print(msg)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
