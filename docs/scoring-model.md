# Scoring Model (prototype)

**Total risk = vessel score (0–50) + owner score (0–50), out of 100. Higher is riskier.**

All numbers below live in [`web/risk_config.json`](../web/risk_config.json). The agent tool (`agent/tools/scoring.py`) and the web form (`web/scoring.js`) both read that file, and `tests/test_scoring.py` checks on 300 random ships that they give identical answers. To change the model, edit the config, not the code.

> Every weight here is a **prototype assumption** chosen to be reasonable, not fitted. Calibrating them on real data is the next step (Yuvraj).

## Vessel score (max 50)

| Factor | Max | How points are given |
|---|---|---|
| PSC record | 15 | Detention rate (70%) and deficiencies per inspection (30%), blended with a peer baseline by credibility (below). Full points at a 25% detention rate or 6 deficiencies per inspection. |
| Age | 10 | 0 points up to 5 years old, rising linearly to 10 at 25+ years. Unknown = 10. |
| Flag | 7 | Paris MOU list: white 0, grey 4, black 7. Unknown = 4. |
| Class society | 7 | IACS member 0, not IACS 7. Unknown = 7. |
| Class status | 6 | In class 0, open conditions of class 3, overdue survey 5, suspended or withdrawn 6. Unknown = 3. |
| Vessel type | 5 | Container ship 2, tanker 2, bulk carrier 3, general cargo 4, ro-ro 5, other 3. |

## Owner score (max 50)

Based on the registered owner's **fleet-wide** PSC record over the last 36 months (all its ships, from the Equasis company record).

| Factor | Max | How points are given |
|---|---|---|
| Fleet detentions | 35 | Fleet detention rate, full points at 15%. Industry baseline 3%. |
| Fleet deficiencies | 15 | Deficiencies per inspection, full points at 6. Industry baseline 2.5. |

## Credibility weighting

A ship or owner with few inspections shouldn't be judged on its own record alone. Each PSC factor blends the record with a baseline:

```
points = max × (Z × own index + (1 − Z) × baseline index),   Z = n / (n + k)
```

`n` = inspections. `k` = 5 for a single ship, 20 for an owner's fleet. With no inspections, Z = 0 and the score is the baseline. When Z is below 0.5, the result includes a "thin data" note.

## Recommendation

| Total | Recommendation |
|---|---|
| under 30 | ACCEPT |
| 30 to under 50 | ACCEPT WITH CONDITIONS |
| 50 to under 70 | REFER |
| 70 and up | DECLINE |

**Overrides (always DECLINE, whatever the score):**
- Sanctions match on the vessel or the owner.
- Class suspended or withdrawn. Hull policies require the ship to stay in class.

**Possible sanctions match** (the owner name only matches once legal-form words like Ltd, Co or SA are ignored): raised to at least REFER so a person confirms it.

A declined vessel isn't given a premium quote.

## Input checks

Impossible inputs are rejected instead of scored: negative or non-whole counts, more detentions than inspections, or a build year before 1900 or in the future. The agent then recommends REFER and asks for the data to be checked; the form shows what's wrong.

Vessel types are matched through aliases (bulker, car carrier, oil tanker...). A type the model doesn't know scores as Other and is flagged in the notes.

## Risk levers

`find_risk_levers` tries each actionable change on its own (clear open class items, reflag to a white-list flag, move to an IACS class society) and reports how much each lowers the total. The agent turns these into conditions for ACCEPT WITH CONDITIONS or REFER; the form lists them with a "Try it" button.

## Premium

```
premium = 1.2% × insured value × relativity × 1.30 loading
relativity = 0.4 + 0.012 × total score        (score 50 = 1.0×, the average-risk rate)
```

## Checking the model

| Script | Question | Run |
|---|---|---|
| `eval/validate_scores.py` | Do higher scores predict more incidents? Compares incident rates across score quarters with 95% intervals, and checks each half of the score separately. | `python -m eval.validate_scores --outcomes data/processed/outcomes.csv` |
| `eval/fairness_flags.py` | Does the flag factor push ships with clean records into worse bands? Re-scores every ship on a white-list flag. | `python -m eval.fairness_flags` |

Both write an HTML report with a chart to `eval/reports/`. Add `--demo` to try them on a synthetic cohort; those results only show the scripts work and are labeled as such.

`outcomes.csv` columns: `imo, events, exposure_years`. Events must come from a window **after** the inspection data was pulled, otherwise detentions count twice. Casualties are rare, so PSC detentions in the next 12–24 months are a more practical outcome.

## Known limitations

- Weights and baselines are judgment calls until fitted on casualty or detention data.
- Vessel type points are rough relative risk, not measured loss rates.
- PSC records over-represent ships that call at U.S. and European ports.
- Flag points use the Paris MOU list, which judges flag states as a group, not individual ships. `eval/fairness_flags.py` measures how often this pushes a ship with a clean record into a worse band.
- When an owner has few inspections, the owner score falls back toward the industry baseline. That can pull a very risky ship's total under the DECLINE line (demo ship DEMO OLD COASTER: vessel 40.9/50, total 63.5, REFER).
