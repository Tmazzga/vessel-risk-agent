"""Tool registry: JSON schemas the LLM sees, mapped to the Python functions."""
from .data_tools import check_sanctions, get_owner_record, get_psc_history, get_vessel_profile
from .model_tools import price_premium, score_risk

TOOL_FUNCTIONS = {
    "get_vessel_profile": get_vessel_profile,
    "get_psc_history": get_psc_history,
    "check_sanctions": check_sanctions,
    "get_owner_record": get_owner_record,
    "score_risk": score_risk,
    "price_premium": price_premium,
}

_imo = {"imo": {"type": "string", "description": "7-digit IMO number"}}

TOOL_SCHEMAS = [
    {
        "name": "get_vessel_profile",
        "description": "Registry profile for a vessel: name, type, year built, flag, flag list (white/grey/black), class society, IACS membership, class status, owner, insured value.",
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
        "name": "get_owner_record",
        "description": "Fleet-wide Port State Control record for the registered owner (all its ships, last 36 months): inspections, deficiencies, detentions. found=false means no record, and the owner score falls back to the industry baseline.",
        "input_schema": {"type": "object", "properties": {"owner_name": {"type": "string"}},
                         "required": ["owner_name"]},
    },
    {
        "name": "score_risk",
        "description": "Deterministic risk score, higher = riskier. Vessel score (0-50) + owner score (0-50) = total (0-100), with per-factor points, a recommendation, and any automatic overrides (sanctions match or suspended class force DECLINE). Always use this for scores and the recommendation band; never estimate or add them up yourself. Pass null for anything unknown.",
        "input_schema": {
            "type": "object",
            "properties": {
                "vessel_type": {"type": ["string", "null"], "description": "Container Ship, Tanker, Bulk Carrier, General Cargo, Ro-Ro, or Other"},
                "year_built": {"type": ["integer", "null"]},
                "flag_list": {"type": ["string", "null"], "enum": ["white", "grey", "black", None]},
                "iacs_member": {"type": ["boolean", "null"]},
                "class_status": {"type": ["string", "null"], "enum": ["in_class", "conditions", "overdue_survey", "suspended", None]},
                "psc_inspections": {"type": "integer"},
                "psc_deficiencies": {"type": "integer"},
                "psc_detentions": {"type": "integer"},
                "owner_inspections": {"type": "integer", "description": "From get_owner_record; 0 if not found"},
                "owner_deficiencies": {"type": "integer"},
                "owner_detentions": {"type": "integer"},
                "sanctions_match": {"type": "boolean", "description": "From check_sanctions"},
            },
            "required": ["vessel_type", "year_built", "flag_list", "iacs_member", "class_status",
                         "psc_inspections", "psc_deficiencies", "psc_detentions",
                         "owner_inspections", "owner_deficiencies", "owner_detentions",
                         "sanctions_match"],
        },
    },
    {
        "name": "price_premium",
        "description": "Convert the total risk score (0-100) and insured value into an annual hull & machinery premium. Always use this for any dollar figure.",
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
