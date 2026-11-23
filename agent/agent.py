"""Underwriting agent: LLM tool-calling loop (owner: Ty).

Usage:
    python -m agent.agent "Assess IMO 9900002 for hull & machinery cover"
    python -m agent.agent --mock "Assess IMO 9900002"     # no API key needed
    python -m agent.agent --chat                          # assess, then ask follow-ups
    python -m agent.agent --chat --mock

The LLM decides which tools to call and writes the memo. Every number in the
memo must come from a tool result (see SYSTEM_PROMPT). A session keeps the
conversation, so follow-ups like "what if it had one fewer detention?" re-run
the tools instead of guessing.
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
- Every number you state (score, premium, counts, ages, values) must come from a tool result. Never estimate, round differently, or invent figures.
- Cite the tool each figure came from in square brackets, e.g. [get_psc_history].
- If a sanctions check returns a match, recommend DECLINE and say why; you may still report the other findings.
- If a tool result has "missing_fields", list each one under DATA GAPS. If insured value is missing, do not call price_premium; say the vessel could not be priced.
- If a tool returns "error" or "found": false, do not guess the missing values. Recommend REFER and explain what is missing.
- If PSC data is thin (credibility_z below 0.5), say so and give the credibility weight.
- Follow-up "what if" questions: re-run score_vessel (and price_premium) with the changed inputs, then compare old vs new. Never estimate the effect yourself.

Memo format:
RECOMMENDATION: ACCEPT / ACCEPT WITH CONDITIONS / REFER / DECLINE
RISK SCORE: <score>/100
PREMIUM: <premium>
TOP RISK DRIVERS: 2-3 bullets
DATA GAPS: bullets
"""


class AgentSession:
    """Live LLM agent. Keeps the message history so follow-ups have context."""

    def __init__(self, client=None):
        if client is None:
            import anthropic  # imported here so mock mode works without the package
            client = anthropic.Anthropic()
        self.client = client
        self.messages = []

    def ask(self, text: str, on_event=print) -> str:
        self.messages.append({"role": "user", "content": text})
        for _ in range(MAX_STEPS):
            resp = self.client.messages.create(
                model=MODEL, max_tokens=2000, system=SYSTEM_PROMPT,
                tools=TOOL_SCHEMAS, messages=self.messages,
            )
            self.messages.append({"role": "assistant", "content": resp.content})

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
            self.messages.append({"role": "user", "content": results})

        return "Stopped: step limit reached without a final memo."


WORD_NUM = {"no": 0, "zero": 0, "one": 1, "a": 1, "an": 1, "two": 2, "three": 3,
            "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
FIELD_RE = r"(detention|deficienc|inspection)\w*"


def parse_what_if(text: str, current: dict) -> dict | None:
    """Read 'one fewer detention', '2 more deficiencies', 'no detentions', '5 inspections'.
    Returns new PSC counts, or None if the question isn't a what-if we understand."""
    t = text.lower()
    field_of = {"detention": "detentions", "deficienc": "deficiencies", "inspection": "inspections"}
    num = r"(\d+|" + "|".join(WORD_NUM) + r")"
    new = dict(current)
    changed = False
    for m in re.finditer(num + r"\s+(fewer|less|more|extra|additional)\s+" + FIELD_RE, t):
        n = int(m.group(1)) if m.group(1).isdigit() else WORD_NUM[m.group(1)]
        f = field_of[m.group(3)]
        new[f] = max(0, new[f] + (n if m.group(2) in ("more", "extra", "additional") else -n))
        changed = True
    if not changed:
        for m in re.finditer(num + r"\s+" + FIELD_RE, t):
            n = int(m.group(1)) if m.group(1).isdigit() else WORD_NUM[m.group(1)]
            new[field_of[m.group(2)]] = n
            changed = True
    if not changed:
        return None
    new["detentions"] = min(new["detentions"], new["inspections"])
    return new


class MockSession:
    """Scripted stand-in for the LLM: same tools, fixed order, templated memo.
    For offline development and as a demo fallback. Not the real agent."""

    def __init__(self):
        self.state = None  # remembered after the first assessment

    def _call(self, name, args, on_event):
        on_event({"event": "tool_call", "tool": name, "input": args})
        out = run_tool(name, args)
        on_event({"event": "tool_result", "tool": name, "output": out})
        return out

    def ask(self, text: str, on_event=print) -> str:
        m = re.search(r"\b(\d{7})\b", text)
        if m:
            return self._assess(m.group(1), on_event)
        if self.state:
            return self._what_if(text, on_event)
        return "No 7-digit IMO number found in the request."

    def _score_inputs(self, prof, psc):
        return {"vessel_type": prof["type"], "year_built": prof["year_built"],
                "flag_list": prof["flag_list"], "iacs_member": prof["iacs_member"],
                "inspections": psc["inspections"], "deficiencies": psc["deficiencies"],
                "detentions": psc["detentions"]}

    def _assess(self, imo, on_event):
        call = lambda n, a: self._call(n, a, on_event)
        prof = call("get_vessel_profile", {"imo": imo})
        if not prof.get("found"):
            return f"RECOMMENDATION: REFER\nNo registry data found for IMO {imo} [get_vessel_profile]."
        psc = call("get_psc_history", {"imo": imo})
        sanc = call("check_sanctions", {"imo": imo, "owner_name": prof.get("owner") or ""})
        score = call("score_vessel", self._score_inputs(prof, psc))
        if "error" in score:
            return (f"RECOMMENDATION: REFER\nCould not score IMO {imo}: {score['error']} [score_vessel]\n"
                    f"Missing fields: {', '.join(prof.get('missing_fields', [])) or 'none'} [get_vessel_profile]")
        price = None
        if prof.get("insured_value_usd"):
            price = call("price_premium", {"score": score["score"],
                                           "insured_value_usd": prof["insured_value_usd"]})
        self.state = {"imo": imo, "prof": prof, "psc": psc, "score": score, "price": price}

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
        for f in prof.get("missing_fields", []):
            gaps.append(f"- Missing {f} [get_vessel_profile]")
        gaps.append("- Mock mode: memo is templated, not LLM-written")

        return "\n".join([
            f"VESSEL: {prof['name']} (IMO {imo}), {prof['type']}, built {prof['year_built']} [get_vessel_profile]",
            f"RECOMMENDATION: {rec}",
            f"RISK SCORE: {score['score']}/100 [score_vessel]",
            (f"PREMIUM: ${price['premium_usd']:,} ({price['rate_on_value_pct']}% of value) [price_premium]"
             if price else "PREMIUM: not priced, insured value missing [get_vessel_profile]"),
            "TOP RISK DRIVERS:",
            *[f"- {k}: {v} pts [score_vessel]" for k, v in top],
            *([f"- Sanctions match: {sanc['hits'][0]['name']} on {sanc['hits'][0]['list']} [check_sanctions]"]
              if sanc["match"] else []),
            "DATA GAPS:",
            *gaps,
        ])

    def _what_if(self, text, on_event):
        s = self.state
        old = {k: s["psc"][k] for k in ("inspections", "deficiencies", "detentions")}
        new = parse_what_if(text, old)
        if new is None:
            return ("Mock mode only understands what-ifs about PSC counts, e.g. "
                    "'what if it had one fewer detention?'")
        call = lambda n, a: self._call(n, a, on_event)
        score = call("score_vessel", self._score_inputs(s["prof"], new))
        price = None
        if s["price"]:
            price = call("price_premium", {"score": score["score"],
                                           "insured_value_usd": s["prof"]["insured_value_usd"]})
        lines = ["WHAT-IF:"]
        for k in old:
            if old[k] != new[k]:
                lines.append(f"- {k}: {old[k]} [get_psc_history] -> {new[k]} [score_vessel input]")
        lines.append(f"RISK SCORE: {s['score']['score']} -> {score['score']}/100 [score_vessel]")
        if price:
            lines.append(f"PREMIUM: ${s['price']['premium_usd']:,} -> ${price['premium_usd']:,} [price_premium]")
        lines.append("Note: hypothetical only; the vessel's actual record is unchanged.")
        return "\n".join(lines)


def run_agent(request: str, on_event=print) -> str:
    return AgentSession().ask(request, on_event)


def run_mock(request: str, on_event=print) -> str:
    return MockSession().ask(request, on_event)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("request", nargs="?", help="omit with --chat to be prompted")
    p.add_argument("--mock", action="store_true", help="scripted run, no API key needed")
    p.add_argument("--chat", action="store_true", help="keep asking follow-up questions")
    a = p.parse_args()

    def log(ev):
        print(json.dumps(ev), file=sys.stderr)

    session = MockSession() if a.mock else AgentSession()
    request = a.request or (input("> ") if a.chat else None)
    if not request:
        p.error("give a request, or use --chat")
    print(session.ask(request, log))
    while a.chat:
        try:
            q = input("\n> ").strip()
        except EOFError:
            break
        if q.lower() in ("", "quit", "exit"):
            break
        print(session.ask(q, log))


if __name__ == "__main__":
    main()
