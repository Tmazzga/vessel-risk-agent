"""Underwriting agent: LLM tool-calling loop (owner: Ty).

Usage:
    python -m agent.agent --provider gemini --chat "Assess IMO 9900002"   # free (see agent/providers.py)
    python -m agent.agent "Assess IMO 9900002 for hull & machinery cover"  # Claude (ANTHROPIC_API_KEY)
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

Process: first call get_vessel_profile and WAIT for its result. Then get_psc_history,
check_sanctions (vessel IMO + the owner name from the profile), get_owner_record (same
owner name), then score_risk with everything you found, then
price_premium with the TOTAL score. For ACCEPT WITH CONDITIONS or REFER, also call
find_risk_levers with the same inputs and turn its levers into conditions.

Rules:
- Never guess or invent a tool input. Owner names must be copied exactly from get_vessel_profile; if you don't have the profile yet, get it first.
- The risk score has two halves: vessel (0-50) and owner (0-50), added to a total out of 100. Report all three exactly as score_risk returns them. Never add, estimate, round differently, or invent figures.
- Use the recommendation score_risk returns. If it lists overrides (sanctions match, suspended class), state them; they force DECLINE.
- Do not call price_premium when the recommendation is DECLINE; write "not quoted".
- EVERY line that contains a number must end with the tool(s) it came from in square brackets, e.g. [get_psc_history] or [get_owner_record, score_risk]. That includes headings, intro sentences, and the RISK SCORE line.
- Never compute anything yourself: no differences, sums, percentages, or "increase of X points". To compare, state the old and new values the tools returned (e.g. "65.1 -> 58.1").
- Pass check_sanctions "match" as sanctions_match and "possible_match" as sanctions_possible. A possible match must be confirmed by a person; say so.
- If score_risk returns "error", the inputs are impossible (e.g. more detentions than inspections). Do not score by hand: recommend REFER and say which data must be checked.
- Pass null to score_risk for anything unknown, and list everything in its "missing" field under DATA GAPS. If insured value is missing, do not call price_premium; say the vessel could not be priced.
- If a tool returns "error" or the vessel is not found, do not guess. Recommend REFER and explain what is missing.
- List every entry in score_risk "notes" (e.g. thin data) under DATA GAPS, along with its "missing" fields. Write "none" only if both are empty.
- Follow-up "what if" questions: re-run score_risk (and price_premium) with the changed inputs, then list each changed value as "old -> new" with citations. Never estimate the effect yourself.

Memo format:
RECOMMENDATION: ACCEPT / ACCEPT WITH CONDITIONS / REFER / DECLINE
RISK SCORE: <total>/100 (vessel <v>/50 + owner <o>/50) [score_risk]
PREMIUM: <premium> [price_premium]
TOP RISK DRIVERS: 2-3 bullets
OVERRIDES: bullets, or none
CONDITIONS: for ACCEPT WITH CONDITIONS or REFER, the levers from find_risk_levers with their score reductions; otherwise none
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

    def _score_inputs(self, prof, psc, owner, sanc):
        return {"vessel_type": prof.get("type"), "year_built": prof.get("year_built"),
                "flag_list": prof.get("flag_list"), "iacs_member": prof.get("iacs_member"),
                "class_status": prof.get("class_status"),
                "psc_inspections": psc["inspections"], "psc_deficiencies": psc["deficiencies"],
                "psc_detentions": psc["detentions"],
                "owner_inspections": owner["inspections"], "owner_deficiencies": owner["deficiencies"],
                "owner_detentions": owner["detentions"], "sanctions_match": sanc["match"],
                "sanctions_possible": sanc.get("possible_match", False)}

    def _assess(self, imo, on_event):
        call = lambda n, a: self._call(n, a, on_event)
        prof = call("get_vessel_profile", {"imo": imo})
        if not prof.get("found"):
            return f"RECOMMENDATION: REFER\nNo registry data found for IMO {imo} [get_vessel_profile]."
        psc = call("get_psc_history", {"imo": imo})
        owner_name = prof.get("owner") or ""
        sanc = call("check_sanctions", {"imo": imo, "owner_name": owner_name})
        owner = call("get_owner_record", {"owner_name": owner_name})
        inputs = self._score_inputs(prof, psc, owner, sanc)
        score = call("score_risk", inputs)
        if "error" in score:
            return (f"RECOMMENDATION: REFER\nCould not score IMO {imo}: the records are inconsistent "
                    f"({'; '.join(score['errors'])}) [score_risk]\nCheck the source data before quoting.")
        levers = None
        if score["recommendation"] in ("ACCEPT WITH CONDITIONS", "REFER"):
            levers = call("find_risk_levers", inputs)
        price = None
        if prof.get("insured_value_usd") and score["recommendation"] != "DECLINE":
            price = call("price_premium", {"score": score["total"],
                                           "insured_value_usd": prof["insured_value_usd"]})
        self.state = {"imo": imo, "prof": prof, "psc": psc, "inputs": inputs,
                      "score": score, "price": price}

        factors = list(score["vessel"]["factors"].values()) + list(score["owner"]["factors"].values())
        top = sorted(factors, key=lambda f: -f["points"])[:3]
        gaps = [f"- Missing {m} [score_risk]" for m in score["missing"]]
        gaps += [f"- {n} [score_risk]" for n in score["notes"]]
        if not owner.get("found"):
            gaps.append(f"- No fleet record for owner {owner_name} [get_owner_record]")
        gaps.append("- Mock mode: memo is templated, not LLM-written")

        return "\n".join([
            f"VESSEL: {prof['name']} (IMO {imo}), {prof['type']}, built {prof['year_built']} [get_vessel_profile]",
            f"OWNER: {owner_name} [get_vessel_profile]",
            f"RECOMMENDATION: {score['recommendation']} [score_risk]",
            f"RISK SCORE: {score['total']}/100 (vessel {score['vessel_score']}/50 + owner {score['owner_score']}/50) [score_risk]",
            (f"PREMIUM: ${price['premium_usd']:,} ({price['rate_on_value_pct']}% of value) [price_premium]"
             if price else "PREMIUM: not quoted, recommendation is DECLINE [score_risk]"
             if score["recommendation"] == "DECLINE"
             else "PREMIUM: not priced, insured value missing [get_vessel_profile]"),
            "TOP RISK DRIVERS:",
            *[f"- {f['label']}: {f['points']} of {f['max']} pts, {f['detail']} [score_risk]" for f in top],
            "OVERRIDES:",
            *([f"- {o} [score_risk]" for o in score["overrides"]] or ["- none"]),
            *([f"- Sanctions hit: {sanc['hits'][0]['name']} on {sanc['hits'][0]['list']} [check_sanctions]"]
              if sanc["match"] else []),
            *([f"- Possible sanctions hit: {sanc['possible_hits'][0]['name']} on {sanc['possible_hits'][0]['list']}, "
               f"needs a person to confirm [check_sanctions]"] if sanc.get("possible_match") else []),
            "CONDITIONS:",
            *([f"- {l['change']}: total {score['total']} -> {l['new_total']} [find_risk_levers]"
               for l in levers["levers"]] if levers and levers.get("levers") else ["- none"]),
            "DATA GAPS:",
            *gaps,
        ])

    def _what_if(self, text, on_event):
        s = self.state
        old = {k: s["psc"][k] for k in ("inspections", "deficiencies", "detentions")}
        new = parse_what_if(text, old)
        if new is None:
            return ("Mock mode only understands what-ifs about the vessel's PSC counts, e.g. "
                    "'what if it had one fewer detention?'")
        call = lambda n, a: self._call(n, a, on_event)
        inputs = {**s["inputs"], **{f"psc_{k}": v for k, v in new.items()}}
        score = call("score_risk", inputs)
        price = None
        if s["price"]:
            price = call("price_premium", {"score": score["total"],
                                           "insured_value_usd": s["prof"]["insured_value_usd"]})
        old_s = s["score"]
        lines = ["WHAT-IF:"]
        for k in old:
            if old[k] != new[k]:
                lines.append(f"- {k}: {old[k]} [get_psc_history] -> {new[k]} [score_risk input]")
        lines.append(f"VESSEL SCORE: {old_s['vessel_score']} -> {score['vessel_score']}/50 [score_risk]")
        lines.append(f"RISK SCORE: {old_s['total']} -> {score['total']}/100 [score_risk]")
        lines.append(f"RECOMMENDATION: {old_s['recommendation']} -> {score['recommendation']} [score_risk]")
        if price:
            lines.append(f"PREMIUM: ${s['price']['premium_usd']:,} -> ${price['premium_usd']:,} [price_premium]")
        lines.append("Note: hypothetical only; the vessel's actual record is unchanged.")
        return "\n".join(lines)


PROVIDERS = ["anthropic", "gemini", "groq", "ollama", "openai", "mock"]


def make_session(provider: str = "anthropic"):
    """The agent on any supported LLM. 'mock' is the scripted stand-in (no LLM)."""
    if provider == "mock":
        return MockSession()
    if provider == "anthropic":
        return AgentSession()
    from agent.providers import OpenAICompatSession
    return OpenAICompatSession(provider)


def run_agent(request: str, on_event=print) -> str:
    return AgentSession().ask(request, on_event)


def run_mock(request: str, on_event=print) -> str:
    return MockSession().ask(request, on_event)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("request", nargs="?", help="omit with --chat to be prompted")
    p.add_argument("--mock", action="store_true", help="scripted run, no API key needed")
    p.add_argument("--provider", choices=PROVIDERS, default=os.environ.get("AGENT_PROVIDER", "anthropic"),
                   help="which LLM runs the agent (default: anthropic, or $AGENT_PROVIDER)")
    p.add_argument("--chat", action="store_true", help="keep asking follow-up questions")
    a = p.parse_args()

    def log(ev):
        print(json.dumps(ev), file=sys.stderr)

    session = make_session("mock" if a.mock else a.provider)
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
