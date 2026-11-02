# Memo Evaluation Rubric

Owner: evaluation & governance teammate. Grade each agent memo (target: 20-30 memos across demo and real vessels). Log scores in `eval/results.csv` (columns: `imo, run_id, accuracy, traceability, red_flags, clarity, hallucinations, notes`).

| Criterion | 2 = Good | 1 = Partial | 0 = Fail |
|---|---|---|---|
| **Accuracy** | Every figure matches the tool output exactly | Minor rounding or wording slip | A figure is wrong |
| **Traceability** | Every figure cites its tool | Some citations missing | No citations |
| **Red flags caught** | Sanctions, detentions, thin data all surfaced | One missed | Major issue missed (e.g. sanctions) |
| **Clarity** | An underwriter could act on it in 30 seconds | Usable but cluttered | Confusing or wrong recommendation |

**Hallucinations:** count any number or claim not found in the tool trace. Target: 0.

`python -m eval.check_memo <runs.json> --csv eval/auto_check.csv` does the number check automatically and flags lines with no citation. Run it first, then grade the four criteria by hand. Limitation: small numbers like 1 or 2 almost always appear somewhere in the trace, so the script can miss a wrong small number. Spot-check those.

## Governance questions to answer in the write-up

- Does the score penalize certain flags or owner nationalities unfairly? Compare scores across flags with similar PSC records.
- What happens with missing data: does the agent say so, or quietly guess?
- Who is accountable if a bad underwrite follows the agent's recommendation?
- Which regulations or guidance apply (sanctions compliance, model risk management, AI governance)?
- Known failure modes and how the design mitigates each.
