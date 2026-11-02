# Vessel Risk Agent

An LLM agent that assesses hull & machinery insurance risk for commercial vessels. Given an IMO number, it calls deterministic tools for registry data, Port State Control history, sanctions screening, a credibility-weighted risk score, and premium pricing, then writes an underwriting memo where every figure is traced to a tool.

PRV 201 – Frontiers of Technology: AI · Stevens Institute of Technology · Track A (Build)

> **Status:** scaffold. Data is fictional sample data and the scoring/pricing math is placeholder.

## How it works

```
request ──▶ LLM agent ──▶ get_vessel_profile ┐
              ▲  │        get_psc_history    │  deterministic
              │  └──────▶ check_sanctions    │  Python tools
              │           score_vessel       │
              │           price_premium      ┘
              └── tool results ──▶ underwriting memo (every number cited)
```

The LLM plans, calls tools, handles gaps, and writes the memo. It never computes a number itself. That keeps the output auditable.

## Quickstart

```bash
pip install -r requirements.txt

# Offline scripted run (no API key)
python -m agent.agent --mock "Assess IMO 9900002 for H&M cover"

# Real agent
export ANTHROPIC_API_KEY=...
python -m agent.agent "Assess IMO 9900002 for H&M cover"

# Cache demo runs for the web page, then open web/index.html via a local server
python -m agent.export_demo            # add --live for real LLM runs
python -m http.server -d web 8000

# Real data (see docs/data-collection.md)
python -m pipeline.fetch_ofac        # sanctions list -> data/processed/sanctions.csv
python -m pipeline.validate_vessels  # check data/processed/vessels.csv

# Tests
pytest
```

Demo vessels (fictional): `9900001` clean, `9900002` high-risk, `9900003` thin data + sanctions hit.

## Repo layout

| Path | What | Owner |
|---|---|---|
| `agent/agent.py` | Tool-calling loop, system prompt, mock runner | Ty |
| `agent/tools/data_tools.py` | Vessel profile, PSC, sanctions | Ty |
| `agent/tools/model_tools.py` | Risk score, credibility, pricing | Math teammate |
| `docs/tool-spec.md` | Tool contracts + open modeling questions | All |
| `eval/memo_rubric.md` | Memo grading rubric + governance questions | Eval teammate |
| `pipeline/` | OFAC download, vessel CSV validator | Ty |
| `web/` | Static demo page (GitHub Pages) | Ty |
| `tests/` | Tool contract tests | All |

## Team workflow

- Work on a branch, open a PR, have one teammate review. Don't push to `main` directly.
- Tag each milestone submission: `git tag m1-problem`, `m2-design`, `m3-prototype`, `m5-final`.
- Never commit raw Equasis data (license restricts redistribution). Commit derived features only.

## Data sources (planned)

USCG PSIX · Paris MOU THETIS · Equasis (manual) · OFAC SDN list · USCG marine casualty data (validation). See `data/SOURCES.md` once added.

## Limitations

No proprietary claims data; US/EU port-call bias in PSC records; small validation cohort. Not for real underwriting decisions.
