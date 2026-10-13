"""Contract tests: tool outputs must keep the shapes in docs/tool-spec.md."""
from agent.agent import run_mock
from agent.tools import run_tool


def test_profile_found_and_missing():
    assert run_tool("get_vessel_profile", {"imo": "9900001"})["found"] is True
    assert run_tool("get_vessel_profile", {"imo": "0000000"})["found"] is False


def test_sanctions_owner_match():
    r = run_tool("check_sanctions", {"imo": "9900003", "owner_name": "Demo Sanctioned Trading Co"})
    assert r["match"] is True


def test_score_shape_and_range():
    r = run_tool("score_vessel", {"vessel_type": "Bulk Carrier", "year_built": 2003,
                                  "flag_list": "grey", "iacs_member": False,
                                  "inspections": 11, "deficiencies": 47, "detentions": 3})
    assert 0 <= r["score"] <= 100
    assert set(r["contributions"]) == {"age", "psc", "flag", "class"}
    assert 0 <= r["credibility_z"] <= 1


def test_riskier_ship_scores_higher():
    clean = run_tool("score_vessel", {"vessel_type": "Bulk Carrier", "year_built": 2019,
                                      "flag_list": "white", "iacs_member": True,
                                      "inspections": 9, "deficiencies": 4, "detentions": 0})
    rusty = run_tool("score_vessel", {"vessel_type": "Bulk Carrier", "year_built": 2003,
                                      "flag_list": "grey", "iacs_member": False,
                                      "inspections": 11, "deficiencies": 47, "detentions": 3})
    assert rusty["score"] > clean["score"]


def test_tool_errors_are_reported_not_raised():
    assert "error" in run_tool("score_vessel", {"bad": 1})
    assert "error" in run_tool("no_such_tool", {})


def test_mock_agent_declines_sanctioned_vessel():
    assert "DECLINE" in run_mock("Assess IMO 9900003", lambda e: None)
