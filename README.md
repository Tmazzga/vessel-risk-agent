# Vessel Risk Agent

An LLM agent that assesses hull & machinery insurance risk for commercial vessels. Given an IMO number, it calls deterministic tools for registry data, Port State Control history, sanctions screening, and the owner's fleet record, then scores the risk out of 100 (vessel 0–50 + owner 0–50), prices it, and writes an underwriting memo where every figure is traced to a tool. A web form scores any vessel you describe, using the same model.

PRV 201 – Frontiers of Technology: AI · Stevens Institute of Technology · Track A (Build)

> **Status:** prototype. Demo data is fictional, and scoring weights are prototype assumptions pending calibration (see `docs/scoring-model.md`).

## How it works

```
request ──▶ LLM agent ──▶ get_vessel_profile ┐
              ▲  │        get_psc_history    │
              │  └──────▶ check_sanctions    │  deterministic
              │           get_owner_record   │  Python tools
              │           score_risk         │  vessel 0-50 + owner 0-50 = 0-100
              │           price_premium      ┘
              └── tool results ──▶ underwriting memo (every number cited)

web form ──▶ web/scoring.js ─┐
agent    ──▶ scoring.py ─────┴─▶ web/risk_config.json (one set of weights)
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

# Ask follow-ups ("what if it had one fewer detention?") after the memo
python -m agent.agent --chat --mock "Assess IMO 9900002"

# Cache demo runs, then open the web form + agent replay at http://localhost:8000
python -m agent.export_demo            # add --live for real LLM runs
python -m http.server -d web 8000

# Real data (see docs/data-collection.md)
python -m pipeline.fetch_ofac        # sanctions list -> data/processed/sanctions.csv
python -m pipeline.validate_vessels  # check data/processed/vessels.csv and owners.csv

# Check memos: every number must trace to a tool output
python -m eval.check_memo                 # checks web/demo.json

# Tests
pytest
```

Demo vessels (fictional): `9900001` clean, `9900002` high-risk, `9900003` thin data + sanctions hit.

## Repo layout

| Path | What | Owner |
|---|---|---|
| `agent/agent.py` | Tool-calling loop, system prompt, mock runner | Ty |
| `agent/tools/data_tools.py` | Vessel profile, PSC, sanctions, owner fleet record | Ty |
| `agent/tools/scoring.py` | Vessel + owner risk score, credibility, pricing | Yuvraj |
| `web/risk_config.json` | Every scoring weight and threshold (shared by agent and web form) | Yuvraj |
| `docs/scoring-model.md` | How the score works | Yuvraj |
| `docs/tool-spec.md` | Tool contracts + open modeling questions | All |
| `eval/memo_rubric.md` | Memo grading rubric + governance questions | Robert |
| `eval/check_memo.py` | Automated check for untraced numbers and missing citations | Robert |
| `pipeline/` | OFAC download, vessel CSV validator | Ty |
| `web/` | Scoring form + agent replay (GitHub Pages) | Ty |
| `tests/` | Tool contract tests | All |

## Team workflow

- Work on a branch, open a PR, have one teammate review. Don't push to `main` directly.
- Tag each milestone submission: `git tag m1-problem`, `m2-design`, `m3-prototype`, `m5-final`.
- Never commit raw Equasis data (license restricts redistribution). Commit derived features only.

## Data sources (planned)

USCG PSIX · Paris MOU THETIS · Equasis (manual) · OFAC SDN list · USCG marine casualty data (validation). See `data/SOURCES.md` once added.

## Limitations

No proprietary claims data; US/EU port-call bias in PSC records; small validation cohort. Not for real underwriting decisions.
