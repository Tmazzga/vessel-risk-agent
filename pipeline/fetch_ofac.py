"""Build data/processed/sanctions.csv from the OFAC SDN list (owner: Ty).

    python -m pipeline.fetch_ofac                 # download the live list
    python -m pipeline.fetch_ofac --file sdn.csv  # use a file you already downloaded

The SDN list is public. sdn.csv has no header row; columns are:
ent_num, SDN_Name, SDN_Type, Program, Title, Call_Sign, Vess_type,
Tonnage, GRT, Vess_flag, Vess_owner, Remarks. Empty fields are "-0-".
We keep every vessel entry plus every named entity, so check_sanctions
can match either the ship's IMO number or its registered owner.
"""
import argparse
import csv
import io
import re
import urllib.request
from pathlib import Path

SDN_URL = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV"
OUT = Path(__file__).resolve().parents[1] / "data" / "processed" / "sanctions.csv"

COLS = ["ent_num", "name", "sdn_type", "program", "title", "call_sign",
        "vess_type", "tonnage", "grt", "vess_flag", "vess_owner", "remarks"]
IMO_RE = re.compile(r"IMO\s*(\d{7})")
FIELDS = ["ent_num", "name", "sdn_type", "program", "imo", "vess_flag", "vess_owner", "list"]


def _clean(v: str) -> str:
    v = (v or "").strip()
    return "" if v == "-0-" else v


def parse_sdn(text: str) -> list[dict]:
    rows = []
    for raw in csv.reader(io.StringIO(text)):
        if len(raw) < len(COLS):
            continue  # trailing control line or malformed row
        r = {k: _clean(v) for k, v in zip(COLS, raw)}
        m = IMO_RE.search(r["remarks"])
        rows.append({
            "ent_num": r["ent_num"],
            "name": r["name"],
            "sdn_type": r["sdn_type"].lower() or "entity",
            "program": r["program"],
            "imo": m.group(1) if m else "",
            "vess_flag": r["vess_flag"],
            "vess_owner": r["vess_owner"],
            "list": "OFAC-SDN",
        })
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--file", help="local copy of sdn.csv instead of downloading")
    p.add_argument("--out", default=str(OUT))
    a = p.parse_args()

    if a.file:
        text = Path(a.file).read_text(encoding="latin-1")
    else:
        with urllib.request.urlopen(SDN_URL, timeout=60) as resp:
            text = resp.read().decode("latin-1")

    rows = parse_sdn(text)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    vessels = sum(1 for r in rows if r["imo"])
    print(f"Wrote {len(rows)} SDN entries ({vessels} with an IMO number) to {out}")


if __name__ == "__main__":
    main()
