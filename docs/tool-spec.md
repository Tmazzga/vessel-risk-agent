# Tool Spec

The agent calls these tools. Each tool is deterministic Python; the LLM never computes a number itself.
**Lock the inputs and outputs below this week.** Internals can change freely; shapes can't without telling the team.

## Data tools: owner Ty (`agent/tools/data_tools.py`)

| Tool | Input | Output |
|---|---|---|
| `get_vessel_profile` | `imo` | `found, name, type, year_built, flag, flag_list, class_society, iacs_member, gross_tonnage, owner, insured_value_usd, source` |
| `get_psc_history` | `imo` | `found, inspections, deficiencies, detentions, last_inspection, source` |
| `check_sanctions` | `imo, owner_name` | `match, hits[{name, list, matched_on}], source` |

Real sources to replace the sample data: USCG PSIX, Paris MOU THETIS, Equasis (manual pulls only, do not scrape or commit raw data), OFAC SDN list.

## Model tools: owner math teammate (`agent/tools/model_tools.py`)

| Tool | Input | Output |
|---|---|---|
| `score_vessel` | `vessel_type, year_built, flag_list, iacs_member, inspections, deficiencies, detentions` | `score (0-100), contributions{age, psc, flag, class}, credibility_z, cohort_psc_risk, model_version` |
| `price_premium` | `score, insured_value_usd` | `relativity, expected_loss_usd, premium_usd, rate_on_value_pct, model_version` |

Current math is **placeholder**. Questions to answer before replacing it:

1. **Features:** Which inputs does the score need? Add or drop any from the list above.
2. **Missing data:** If a value is missing, does `score_vessel` reject, impute, or rely more on the cohort?
3. **Cohorts:** What defines the peer group for credibility weighting (type, age band, flag)? What is `k`?
4. **Weights:** Fitted how? (e.g. Poisson regression of casualty counts with vessel-years as exposure)
5. **Pricing:** Where do the base loss rate, severity, and loading come from? What does score 50 mean?
6. **Validation:** Which cohort and date cutoff for the out-of-sample casualty check?

## Rules the whole team agrees to

- The LLM never states a number that didn't come from a tool result.
- Every memo figure cites its tool in brackets, e.g. `[score_vessel]`.
- Tools return `{"error": ...}` on failure; the agent reports gaps instead of guessing.
