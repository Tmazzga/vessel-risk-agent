"""Data tools (owner: Ty). Deterministic lookups the agent calls.

STUB: reads data/sample/vessels.json. Replace internals with the real
pipeline (USCG PSIX, Paris MOU THETIS, Equasis manual pulls, OFAC SDN)
without changing the return shapes in docs/tool-spec.md.
"""
import json
from functools import lru_cache
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "sample" / "vessels.json"


@lru_cache(maxsize=1)
def _db() -> dict:
    return json.loads(DATA_FILE.read_text())


def _vessel(imo: str) -> dict | None:
    return _db()["vessels"].get(str(imo).strip())


def get_vessel_profile(imo: str) -> dict:
    v = _vessel(imo)
    if v is None:
        return {"found": False, "imo": imo, "source": "sample-data"}
    keys = ["name", "type", "year_built", "flag", "flag_list", "class_society",
            "iacs_member", "gross_tonnage", "owner", "insured_value_usd"]
    return {"found": True, "imo": imo, **{k: v[k] for k in keys}, "source": "sample-data"}


def get_psc_history(imo: str) -> dict:
    v = _vessel(imo)
    if v is None:
        return {"found": False, "imo": imo, "source": "sample-data"}
    return {"found": True, "imo": imo, **v["psc"], "source": "sample-data (stand-in for USCG PSIX / Paris MOU)"}


def check_sanctions(imo: str, owner_name: str = "") -> dict:
    hits = []
    for entry in _db()["sanctions_list"]:
        if entry.get("imo") and str(entry["imo"]) == str(imo):
            hits.append({**entry, "matched_on": "imo"})
        elif owner_name and entry["name"].lower() == owner_name.strip().lower():
            hits.append({**entry, "matched_on": "owner_name"})
    return {"imo": imo, "match": bool(hits), "hits": hits,
            "source": "sample-data (stand-in for OFAC SDN list)"}
