"""Pre-run the agent on the demo vessels and cache the results for the web page.

    python -m agent.export_demo          # mock mode, no API key
    python -m agent.export_demo --live   # real LLM runs (needs ANTHROPIC_API_KEY)

Writes web/demo.json. The live demo reads this cache so classroom wifi
can't break it.
"""
import argparse
import json
from pathlib import Path

from agent.agent import run_agent, run_mock
from agent.tools.data_tools import _vessels

OUT = Path(__file__).resolve().parents[1] / "web" / "demo.json"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true")
    a = p.parse_args()

    runs = []
    for imo, v in _vessels()[0].items():
        events = []
        request = f"Assess IMO {imo} for hull & machinery cover."
        memo = (run_agent if a.live else run_mock)(request, events.append)
        runs.append({"imo": imo, "name": v["name"], "request": request,
                     "events": events, "memo": memo, "mode": "live" if a.live else "mock"})

    OUT.write_text(json.dumps({"runs": runs}, indent=2))
    print(f"Wrote {len(runs)} runs to {OUT}")


if __name__ == "__main__":
    main()
