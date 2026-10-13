"""Tool registry: JSON schemas the LLM sees, mapped to the Python functions."""
from .data_tools import get_vessel_profile, get_psc_history, check_sanctions
from .model_tools import score_vessel, price_premium

TOOL_FUNCTIONS = {
    "get_vessel_profile": get_vessel_profile,
    "get_psc_history": get_psc_history,
    "check_sanctions": check_sanctions,
    "score_vessel": score_vessel,
    "price_premium": price_premium,
}

_imo = {"imo": {"type": "string", "description": "7-digit IMO number"}}

TOOL_SCHEMAS = [
    {
        "name": "get_vessel_profile",
        "description": "Registry profile for a vessel: name, type, year built, flag, flag list (white/grey/black), class society, IACS membership, owner, insured value.",
        "input_schema": {"type": "object", "properties": _imo, "required": ["imo"]},
    },
    {
        "name": "get_psc_history",
        "description": "Port State Control history: inspection count, deficiency count, detention count, last inspection date.",
        "input_schema": {"type": "object", "properties": _imo, "required": ["imo"]},
    },
    {
        "name": "check_sanctions",
        "description": "Screen the vessel IMO and registered owner name against the sanctions list.",
        "input_schema": {
            "type": "object",
            "properties": {**_imo, "owner_name": {"type": "string"}},
            "required": ["imo", "owner_name"],
        },
    },
    {
        "name": "score_vessel",
        "description": "Deterministic 0-100 risk score (higher = riskier) with per-factor contributions and credibility weight. Always use this for the score; never estimate it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "vessel_type": {"type": "string"},
                "year_built": {"type": "integer"},
                "flag_list": {"type": "string", "enum": ["white", "grey", "black"]},
                "iacs_member": {"type": "boolean"},
                "inspections": {"type": "integer"},
                "deficiencies": {"type": "integer"},
                "detentions": {"type": "integer"},
            },
            "required": ["vessel_type", "year_built", "flag_list", "iacs_member",
                         "inspections", "deficiencies", "detentions"],
        },
    },
    {
        "name": "price_premium",
        "description": "Convert a risk score and insured value into an annual hull & machinery premium. Always use this for any dollar figure.",
        "input_schema": {
            "type": "object",
            "properties": {
                "score": {"type": "number"},
                "insured_value_usd": {"type": "number"},
            },
            "required": ["score", "insured_value_usd"],
        },
    },
]


def run_tool(name: str, args: dict) -> dict:
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return {"error": f"unknown tool {name}"}
    try:
        return fn(**args)
    except Exception as e:  # report failures to the agent instead of crashing
        return {"error": f"{type(e).__name__}: {e}"}
