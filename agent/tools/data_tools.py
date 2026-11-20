"""Data tools (owner: Ty). Deterministic lookups the agent calls.

Data comes from data/processed/ when those files exist, otherwise from the
fictional demo set in data/sample/vessels.json:

    data/processed/vessels.csv    hand-built from Equasis + USCG PSIX / Paris MOU
                                  (check it with: python -m pipeline.validate_vessels)
    data/processed/owners.csv     owner fleet PSC record, hand-built from Equasis
    data/processed/sanctions.csv  built by: python -m pipeline.fetch_ofac

Return shapes are fixed by docs/tool-spec.md. Don't change them without
telling the team.
"""
import csv
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_FILE = ROOT / "data" / "sample" / "vessels.json"
VESSELS_CSV = ROOT / "data" / "processed" / "vessels.csv"
SANCTIONS_CSV = ROOT / "data" / "processed" / "sanctions.csv"
OWNERS_CSV = ROOT / "data" / "processed" / "owners.csv"

PROFILE_KEYS = ["name", "type", "year_built", "flag", "flag_list", "class_society",
                "iacs_member", "class_status", "gross_tonnage", "owner", "insured_value_usd"]


def _num(v, kind=int):
    v = (v or "").strip().replace(",", "")
    return kind(v) if v else None


def _row_to_vessel(r: dict) -> dict:
    return {
        "name": r["name"],
        "type": r["type"],
        "year_built": _num(r["year_built"]),
        "flag": r["flag"],
        "flag_list": r["flag_list"].strip().lower(),
        "class_society": r["class_society"],
        "iacs_member": r["iacs_member"].strip().lower() in ("true", "yes", "1"),
        "class_status": (r.get("class_status") or "").strip().lower() or None,
        "gross_tonnage": _num(r["gross_tonnage"]),
        "owner": r["owner"],
        "insured_value_usd": _num(r["insured_value_usd"], float),
        "psc": {
            "inspections": _num(r["psc_inspections"]) or 0,
            "deficiencies": _num(r["psc_deficiencies"]) or 0,
            "detentions": _num(r["psc_detentions"]) or 0,
            "last_inspection": r["psc_last_inspection"] or None,
        },
        "_source": r.get("source") or "processed data",
        "_date_pulled": r.get("date_pulled") or None,
    }


@lru_cache(maxsize=1)
def _vessels() -> tuple[dict, str]:
    if VESSELS_CSV.exists():
        with VESSELS_CSV.open(newline="") as f:
            rows = {r["imo"].strip(): _row_to_vessel(r) for r in csv.DictReader(f) if r.get("imo")}
        if rows:
            return rows, "processed"
    return json.loads(SAMPLE_FILE.read_text())["vessels"], "sample"


@lru_cache(maxsize=1)
def _sanctions() -> tuple[list, str]:
    if SANCTIONS_CSV.exists():
        with SANCTIONS_CSV.open(newline="") as f:
            return list(csv.DictReader(f)), "OFAC SDN list"
    return json.loads(SAMPLE_FILE.read_text())["sanctions_list"], "sample-data"


@lru_cache(maxsize=1)
def _owners() -> tuple[dict, str]:
    if OWNERS_CSV.exists():
        with OWNERS_CSV.open(newline="") as f:
            rows = {_company_key(r["owner"]): {
                "owner": r["owner"],
                "fleet_size": _num(r.get("fleet_size")),
                "inspections": _num(r.get("inspections")) or 0,
                "deficiencies": _num(r.get("deficiencies")) or 0,
                "detentions": _num(r.get("detentions")) or 0,
                "period": r.get("period") or "last 36 months",
                "_source": r.get("source") or "processed data",
                "_date_pulled": r.get("date_pulled") or None,
            } for r in csv.DictReader(f) if r.get("owner")}
        return rows, "processed"
    raw = json.loads(SAMPLE_FILE.read_text()).get("owners", {})
    return {_company_key(k): {"owner": k, **v} for k, v in raw.items()}, "sample"


def data_mode() -> str:
    """'processed' if real vessel data is loaded, else 'sample'."""
    return _vessels()[1]


def _vessel(imo: str) -> dict | None:
    return _vessels()[0].get(str(imo).strip())


def _source(v: dict, default: str) -> str:
    if data_mode() == "sample":
        return default
    s = v.get("_source", "processed data")
    return f"{s} (pulled {v['_date_pulled']})" if v.get("_date_pulled") else s


def get_vessel_profile(imo: str) -> dict:
    v = _vessel(imo)
    if v is None:
        return {"found": False, "imo": imo, "source": data_mode()}
    missing = [k for k in PROFILE_KEYS if v.get(k) in (None, "")]
    out = {"found": True, "imo": imo, **{k: v.get(k) for k in PROFILE_KEYS},
           "source": _source(v, "sample-data")}
    if missing:
        out["missing_fields"] = missing  # agent should report these as data gaps
    return out


def get_psc_history(imo: str) -> dict:
    v = _vessel(imo)
    if v is None:
        return {"found": False, "imo": imo, "source": data_mode()}
    return {"found": True, "imo": imo, **v["psc"],
            "source": _source(v, "sample-data (stand-in for USCG PSIX / Paris MOU)")}


def _norm(name: str) -> str:
    return " ".join("".join(c if c.isalnum() else " " for c in name.lower()).split())


# Legal-form words dropped for loose company matching ("Ocean Star Shipping Co. Ltd" ~ "Ocean Star Shipping").
LEGAL_FORMS = {"ltd", "limited", "inc", "incorporated", "co", "company", "corp", "corporation", "llc",
               "plc", "sa", "s", "a", "gmbh", "ag", "as", "bv", "nv", "spa", "srl", "sarl", "pte",
               "pvt", "private", "the"}


def _company_key(name: str) -> str:
    words = [w for w in _norm(name).split() if w not in LEGAL_FORMS]
    return " ".join(words) or _norm(name)


def check_sanctions(imo: str, owner_name: str = "") -> dict:
    """IMO match or exact owner-name match = hit. A name that only matches once
    legal-form words (Ltd, Co, SA...) are ignored = possible hit for a person to confirm."""
    entries, source = _sanctions()
    owner = _norm(owner_name) if owner_name else ""
    owner_key = _company_key(owner_name) if owner_name else ""
    hits, possible = [], []
    for e in entries:
        e_imo = str(e.get("imo") or "").strip()
        info = {"name": e["name"], "list": e.get("list", "OFAC-SDN"), "program": e.get("program", "")}
        if e_imo and e_imo == str(imo).strip():
            hits.append({**info, "matched_on": "imo"})
        elif owner and _norm(e["name"]) == owner:
            hits.append({**info, "matched_on": "owner_name"})
        elif owner_key and _company_key(e["name"]) == owner_key:
            possible.append({**info, "matched_on": "owner_name_ignoring_legal_form"})
    return {"imo": imo, "match": bool(hits), "hits": hits,
            "possible_match": bool(possible), "possible_hits": possible, "source": source}


def get_owner_record(owner_name: str) -> dict:
    """Fleet-wide PSC record for the registered owner (all ships, last 36 months)."""
    rows, mode = _owners()
    o = rows.get(_company_key(owner_name or ""))
    if o is None:
        return {"found": False, "owner": owner_name, "inspections": 0, "deficiencies": 0,
                "detentions": 0, "source": mode,
                "note": "No fleet record found; owner score will use the industry baseline"}
    src = "sample-data (stand-in for Equasis company PSC record)" if mode == "sample" else (
        f"{o['_source']} (pulled {o['_date_pulled']})" if o.get("_date_pulled") else o["_source"])
    return {"found": True, "owner": o["owner"], "fleet_size": o.get("fleet_size"),
            "inspections": o["inspections"], "deficiencies": o["deficiencies"],
            "detentions": o["detentions"], "period": o.get("period", "last 36 months"),
            "source": src}
