"""Underwriting agent: LLM tool-calling loop (owner: Ty).

Usage:
    python -m agent.agent "Assess IMO 9900002 for hull & machinery cover"
    python -m agent.agent --mock "Assess IMO 9900002"     # no API key needed

The LLM decides which tools to call and writes the memo. Every number in the
memo must come from a tool result (see SYSTEM_PROMPT).
"""
import argparse
import json
import os
import re
import sys

from agent.tools import TOOL_SCHEMAS, run_tool

MODEL = os.environ.get("AGENT_MODEL", "claude-sonnet-5-5")
MAX_STEPS = 12

SYSTEM_PROMPT = """You are a marine hull & machinery underwriting assistant.
Given a vessel, gather evidence with the tools, then write a short underwriting memo.

Rules:
- Every number you state (score, premium, counts, ages, values) must come from a tool result. Never estimate or invent figures.
- If a sanctions check returns a match, recommend DECLINE and say why; you may still report the other findings.
- If data is missing or thin (e.g. few PSC inspections), say so and note the credibility weight.
- Cite the tool each figure came from in square brackets, e.g. [get_psc_history].

Memo format:
RECOMMENDATION: ACCEPT / ACCEPT WITH CONDITIONS / REFER / DECLINE
RISK SCORE: <score>/100
PREMIUM: <premium>
TOP RISK DRIVERS: 2-3 bullets
DATA GAPS: bullets
"""


def run_agent(request: str, on_event=print) -> str:
    """Run the LLM loop. on_event receives dicts for each tool call/result."""
    import anthropic  # imported here so --mock works without the package

    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": request}]

    for _ in range(MAX_STEPS):
        resp = client.messages.create(
            model=MODEL, max_tokens=2000, system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS, messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text")

        results = []
        for block in resp.content:
            if block.type == "tool_use":
                on_event({"event": "tool_call", "tool": block.name, "input": block.input})
                out = run_tool(block.name, block.input)
                on_event({"event": "tool_result", "tool": block.name, "output": out})
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": json.dumps(out)})
        messages.append({"role": "user", "content": results})

    return "Stopped: step limit reached without a final memo."


def run_mock(request: str, on_event=print) -> str:
    """Scripted stand-in for the LLM: same tools, fixed order, templated memo.
    For offline development and as a demo fallback. Not the real agent."""
    m = re.search(r"\b(\d{7})\b", request)
    if not m:
        return "No 7-digit IMO number found in the request."
    imo = m.group(1)

    def call(name, args):
        on_event({"event": "tool_call", "tool": name, "input": args})
        out = run_tool(name, args)
        on_event({"event": "tool_result", "tool": name, "output": out})
        return out

    prof = call("get_vessel_profile", {"imo": imo})
    if not prof.get("found"):
        return f"RECOMMENDATION: REFER\nNo registry data found for IMO {imo} [get_vessel_profile]."
    psc = call("get_psc_history", {"imo": imo})
    sanc = call("check_sanctions", {"imo": imo, "owner_name": prof["owner"]})
    score = call("score_vessel", {
        "vessel_type": prof["type"], "year_built": prof["year_built"],
        "flag_list": prof["flag_list"], "iacs_member": prof["iacs_member"],
        "inspections": psc["inspections"], "deficiencies": psc["deficiencies"],
        "detentions": psc["detentions"]})
    price = call("price_premium", {"score": score["score"],
                                   "insured_value_usd": prof["insured_value_usd"]})

    if sanc["match"]:
        rec = "DECLINE (sanctions match)"
    elif score["score"] >= 60:
        rec = "REFER"
    elif score["score"] >= 40:
        rec = "ACCEPT WITH CONDITIONS"
    else:
        rec = "ACCEPT"

    top = sorted(score["contributions"].items(), key=lambda kv: -kv[1])[:3]
    gaps = []
    if score["credibility_z"] < 0.5:
        gaps.append(f"- Thin PSC record ({psc['inspections']} inspections); credibility weight "
                    f"{score['credibility_z']} so score leans on peer cohort [score_vessel]")
    gaps.append("- Mock mode: memo is templated, not LLM-written")

    return "\n".join([
        f"VESSEL: {prof['name']} (IMO {imo}), {prof['type']}, built {prof['year_built']} [get_vessel_profile]",
        f"RECOMMENDATION: {rec}",
        f"RISK SCORE: {score['score']}/100 [score_vessel]",
        f"PREMIUM: ${price['premium_usd']:,} ({price['rate_on_value_pct']}% of value) [price_premium]",
        "TOP RISK DRIVERS:",
        *[f"- {k}: {v} pts [score_vessel]" for k, v in top],
        *([f"- Sanctions match: {sanc['hits'][0]['name']} on {sanc['hits'][0]['list']} [check_sanctions]"]
          if sanc["match"] else []),
        "DATA GAPS:",
        *gaps,
    ])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("request")
    p.add_argument("--mock", action="store_true", help="scripted run, no API key needed")
    a = p.parse_args()

    def log(ev):
        print(json.dumps(ev), file=sys.stderr)

    memo = run_mock(a.request, log) if a.mock else run_agent(a.request, log)
    print(memo)


if __name__ == "__main__":
    main()
