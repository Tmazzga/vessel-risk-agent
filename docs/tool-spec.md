# Tool Spec

The agent calls these tools. Each tool is deterministic Python; the LLM never computes a number itself.
Internals can change freely; input and output shapes can't change without telling the team.

## Data tools: owner Ty (`agent/tools/data_tools.py`)

| Tool | Input | Output |
|---|---|---|
| `get_vessel_profile` | `imo` | `found, name, type, year_built, flag, flag_list, class_society, iacs_member, class_status, gross_tonnage, owner, insured_value_usd, source, missing_fields?` |
| `get_psc_history` | `imo` | `found, inspections, deficiencies, detentions, last_inspection, source` |
| `check_sanctions` | `imo, owner_name` | `match, hits[{name, list, program, matched_on}], source` |
| `get_owner_record` | `owner_name` | `found, owner, fleet_size, inspections, deficiencies, detentions, period, source` (counts are 0 when not found) |

Real sources: Equasis (ship and company pages, by hand only), USCG PSIX, Paris MOU THETIS, OFAC SDN list. See `docs/data-collection.md`.

## Model tools: owner Yuvraj (`agent/tools/scoring.py`, numbers in `web/risk_config.json`)

| Tool | Input | Output |
|---|---|---|
| `score_risk` | `vessel_type, year_built, flag_list, iacs_member, class_status, psc_inspections, psc_deficiencies, psc_detentions, owner_inspections, owner_deficiencies, owner_detentions, sanctions_match` (null = unknown) | `total (0-100), vessel_score (0-50), owner_score (0-50), vessel{factors, credibility_z}, owner{factors, credibility_z}, recommendation, overrides[], notes[], missing[], model_version` |
| `price_premium` | `score` (the total), `insured_value_usd` | `relativity, expected_loss_usd, premium_usd, rate_on_value_pct, model_version` |

Each factor is `{label, points, max, detail}`. The method is in `docs/scoring-model.md`.

Open questions for calibration:

1. **Weights:** fit factor maxes on real outcomes (e.g. Poisson regression on future detentions or casualties).
2. **Baselines:** replace the peer and industry baselines with averages from our real cohort.
3. **k values:** how many inspections before a record is trusted (currently 5 for a ship, 20 for a fleet)?
4. **Vessel type points:** replace judgment with casualty rates by ship type.
5. **Pricing:** where should the base rate and loading come from?

## Rules the whole team agrees to

- The LLM never states a number that didn't come from a tool result.
- Every memo figure cites its tool in brackets, e.g. `[score_risk]`.
- Tools return `{"error": ...}` on failure; the agent reports gaps instead of guessing.
- Scoring numbers only change in `web/risk_config.json`, so the agent and the web form stay identical.
