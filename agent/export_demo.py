"""Pre-run the agent on the demo vessels and cache the results for the web page.

    python -m agent.export_demo          # mock mode, no API key
    python -m agent.export_demo --live   # real LLM runs (needs ANTHROPIC_API_KEY)

Writes web/demo.json. Each run includes one what-if follow-up so the demo
shows the agent re-running its tools. The live demo reads this cache so
classroom wifi can't break it.
"""
import argparse
import json
from pathlib import Path

from agent.agent import AgentSession, MockSession
from agent.tools.data_tools import _vessels

OUT = Path(__file__).resolve().parents[1] / "web" / "demo.json"


def follow_up_for(v: dict) -> str:
    if v["psc"]["detentions"] > 0:
        return "What if it had one fewer detention?"
    return "What if it had one more detention?"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true")
    a = p.parse_args()

    runs = []
    for imo, v in _vessels()[0].items():
        session = AgentSession() if a.live else MockSession()
        events = []
        request = f"Assess IMO {imo} for hull & machinery cover."
        memo = session.ask(request, events.append)

        question = follow_up_for(v)
        f_events = []
        f_memo = session.ask(question, f_events.append)

        runs.append({"imo": imo, "name": v["name"], "request": request,
                     "events": events, "memo": memo,
                     "followups": [{"question": question, "events": f_events, "memo": f_memo}],
                     "mode": "live" if a.live else "mock"})

    OUT.write_text(json.dumps({"runs": runs}, indent=2))
    print(f"Wrote {len(runs)} runs to {OUT}")


if __name__ == "__main__":
    main()
