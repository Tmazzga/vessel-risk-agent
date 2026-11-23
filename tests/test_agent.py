"""Tests for follow-up questions, the memo checker, and the live agent loop
(with a fake LLM client, so no API key or network is needed)."""
from types import SimpleNamespace as NS

from agent.agent import AgentSession, MockSession, parse_what_if
from eval.check_memo import check

BASE = {"inspections": 11, "deficiencies": 47, "detentions": 3}


def test_parse_what_if():
    assert parse_what_if("what if it had one fewer detention?", BASE)["detentions"] == 2
    assert parse_what_if("2 more deficiencies", BASE)["deficiencies"] == 49
    assert parse_what_if("what if it had no detentions", BASE)["detentions"] == 0
    assert parse_what_if("what about 5 inspections", BASE)["inspections"] == 5
    assert parse_what_if("five fewer detentions", BASE)["detentions"] == 0  # floors at 0
    assert parse_what_if("is the owner reputable?", BASE) is None


def test_mock_follow_up_reruns_tools_and_lowers_score():
    s, events = MockSession(), []
    s.ask("Assess IMO 9900002", lambda e: None)
    memo = s.ask("What if it had one fewer detention?", events.append)
    called = [e["tool"] for e in events if e["event"] == "tool_call"]
    assert called == ["score_risk", "price_premium"]
    before = s.state["score"]["total"]
    after = next(e for e in events if e["event"] == "tool_result")["output"]
    assert after["vessel_score"] < s.state["score"]["vessel_score"]
    assert after["owner_score"] == s.state["score"]["owner_score"]  # owner record unchanged
    assert after["total"] < before and "WHAT-IF" in memo


def test_checker_passes_traced_memo():
    events = [{"event": "tool_result", "tool": "score_risk", "output": {"score": 75.1}},
              {"event": "tool_result", "tool": "price_premium", "output": {"premium_usd": 182688}}]
    memo = "RISK SCORE: 75.1/100 [score_risk]\nPREMIUM: $182,688 [price_premium]"
    assert check(memo, events)["pass"]


def test_checker_catches_made_up_number_and_missing_citation():
    events = [{"event": "tool_result", "tool": "score_risk", "output": {"score": 75.1}}]
    r = check("RISK SCORE: 78.4/100 [score_risk]\nThe premium is $250,000.", events)
    assert not r["pass"]
    assert {u["number"] for u in r["untraced"]} == {"78.4", "$250,000"}
    assert r["uncited_lines"] == ["The premium is $250,000."]


def test_checker_allows_rounding_to_shown_decimals():
    events = [{"event": "tool_result", "tool": "score_risk", "output": {"credibility_z": 0.1667}}]
    assert check("Credibility weight 0.17 [score_risk]", events)["pass"]


class FakeClient:
    """Plays back scripted LLM turns: first a tool call, then a final text answer."""

    def __init__(self, turns):
        self.turns, self.seen = list(turns), []
        self.messages = self

    def create(self, **kw):
        self.seen.append(len(kw["messages"]))
        return self.turns.pop(0)


def _tool_turn(name, args):
    return NS(stop_reason="tool_use",
              content=[NS(type="tool_use", id="t1", name=name, input=args)])


def _text_turn(text):
    return NS(stop_reason="end_turn", content=[NS(type="text", text=text)])


def test_live_loop_runs_tools_and_keeps_history():
    client = FakeClient([
        _tool_turn("get_psc_history", {"imo": "9900002"}),
        _text_turn("RECOMMENDATION: REFER"),
        _text_turn("Follow-up answer"),
    ])
    s, events = AgentSession(client=client), []
    assert s.ask("Assess IMO 9900002", events.append) == "RECOMMENDATION: REFER"
    assert events[1]["output"]["detentions"] == 3  # real tool ran on the LLM's request
    s.ask("What if it had one fewer detention?", events.append)
    # second question sent the whole history: user, assistant, tool result, assistant, user
    assert client.seen[-1] == 5


def test_checker_accepts_multi_tool_citations_and_flags_model_math():
    events = [{"event": "tool_result", "tool": "score_risk", "output": {"total": 24.1, "age_pts": 3.5}},
              {"event": "tool_result", "tool": "score_risk", "output": {"total": 21.1}},
              {"event": "tool_result", "tool": "get_vessel_profile", "output": {"year_built": 2014, "age": 12}}]
    ok = "- Vessel age: 12 years old (built 2014) adds 3.5 points [get_vessel_profile, score_risk]"
    assert check(ok, events)["pass"]
    bad = "- Total: **24.1/100** (previously 21.1/100), an increase of **3.0 points** [score_risk]"
    r = check(bad, events)
    assert [u["number"] for u in r["untraced"]] == ["3.0"]


def test_prompt_demands_citations_on_every_numeric_line():
    from agent.agent import SYSTEM_PROMPT
    assert "EVERY line that contains a number" in SYSTEM_PROMPT
    assert "Never compute anything yourself" in SYSTEM_PROMPT
    assert "[score_risk]" in SYSTEM_PROMPT.split("Memo format:")[1]


def test_checker_skips_score_scales_with_or_without_spaces():
    events = [{"event": "tool_result", "tool": "score_risk", "output": {"total": 26.6, "v": 13.3}}]
    assert check("RISK SCORE: 26.6 / 100 (vessel 13.3 / 50) [score_risk]", events)["pass"]
