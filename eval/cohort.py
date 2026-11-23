"""Build score_risk inputs for a whole cohort of ships (shared by the
validation and fairness scripts).

- real():      every ship the data tools can see (data/processed/*.csv, or the
               9 fictional demo ships when no real data exists yet)
- synthetic(): a made-up cohort for testing the scripts end to end. Its
               outcomes are SIMULATED, so results on it prove nothing about
               the model; they only show the pipeline works.
"""
import math
import random

from agent.tools import data_tools

TYPES = ["Container Ship", "Tanker", "Bulk Carrier", "General Cargo", "Ro-Ro"]


def real() -> tuple[list[dict], str]:
    ships = []
    for imo in data_tools._vessels()[0]:
        prof = data_tools.get_vessel_profile(imo)
        psc = data_tools.get_psc_history(imo)
        owner_name = prof.get("owner") or ""
        owner = data_tools.get_owner_record(owner_name)
        sanc = data_tools.check_sanctions(imo, owner_name)
        ships.append({
            "imo": imo, "name": prof["name"],
            "inputs": {
                "vessel_type": prof.get("type"), "year_built": prof.get("year_built"),
                "flag_list": prof.get("flag_list"), "iacs_member": prof.get("iacs_member"),
                "class_status": prof.get("class_status"),
                "psc_inspections": psc["inspections"], "psc_deficiencies": psc["deficiencies"],
                "psc_detentions": psc["detentions"],
                "owner_inspections": owner["inspections"], "owner_deficiencies": owner["deficiencies"],
                "owner_detentions": owner["detentions"],
                "sanctions_match": sanc["match"], "sanctions_possible": sanc["possible_match"],
            },
        })
    return ships, data_tools.data_mode()


def _poisson(rng: random.Random, lam: float) -> int:
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def synthetic(n: int = 300, seed: int = 11, as_of_year: int = 2026) -> list[dict]:
    """Fictional ships with simulated outcomes. The hidden 'true' risk only partly
    overlaps the model's factors, plus noise, so the model isn't graded on its own rules."""
    rng = random.Random(seed)
    ships = []
    for i in range(n):
        age = rng.randint(1, 32)
        flag = rng.choices(["white", "grey", "black"], [0.75, 0.18, 0.07])[0]
        iacs = rng.random() < (0.9 if flag == "white" else 0.6)
        status = rng.choices(["in_class", "conditions", "overdue_survey", "suspended"], [0.8, 0.12, 0.06, 0.02])[0]
        upkeep = rng.gauss(0, 1) + 0.04 * age + (0.6 if not iacs else 0)   # hidden maintenance quality
        insp = rng.randint(0, 25)
        det = sum(rng.random() < min(0.6, 0.03 * math.exp(0.7 * upkeep)) for _ in range(insp))
        dfc = sum(_poisson(rng, max(0.2, 2 + 1.2 * upkeep)) for _ in range(insp))
        o_insp = rng.choice([0, rng.randint(5, 300)])
        o_det = sum(rng.random() < min(0.5, 0.025 * math.exp(0.5 * upkeep)) for _ in range(o_insp))
        o_dfc = sum(_poisson(rng, max(0.2, 2.2 + upkeep)) for _ in range(o_insp))
        exposure = round(rng.uniform(1, 3), 2)
        events = _poisson(rng, exposure * 0.06 * math.exp(0.55 * upkeep + 0.3 * rng.gauss(0, 1)))
        ships.append({
            "imo": f"SYN{i:04d}", "name": f"SYNTHETIC {i:04d}",
            "events": events, "exposure_years": exposure,
            "inputs": {
                "vessel_type": rng.choice(TYPES), "year_built": as_of_year - age, "flag_list": flag,
                "iacs_member": iacs, "class_status": status,
                "psc_inspections": insp, "psc_deficiencies": dfc, "psc_detentions": det,
                "owner_inspections": o_insp, "owner_deficiencies": o_dfc, "owner_detentions": o_det,
                "sanctions_match": False, "sanctions_possible": False, "as_of_year": as_of_year,
            },
        })
    return ships
