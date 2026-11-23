"""Contract tests: tool outputs must keep the shapes in docs/tool-spec.md."""
from agent.agent import run_mock
from agent.tools import run_tool


def test_profile_found_and_missing():
    assert run_tool("get_vessel_profile", {"imo": "9900001"})["found"] is True
    assert run_tool("get_vessel_profile", {"imo": "0000000"})["found"] is False


def test_sanctions_owner_match():
    r = run_tool("check_sanctions", {"imo": "9900003", "owner_name": "Demo Sanctioned Trading Co"})
    assert r["match"] is True


def test_owner_record_found_and_missing():
    assert run_tool("get_owner_record", {"owner_name": "Demo Opaque Holdings SA"})["detentions"] == 4
    missing = run_tool("get_owner_record", {"owner_name": "Nobody Ltd"})
    assert missing["found"] is False and missing["inspections"] == 0


RUSTY = {"vessel_type": "Bulk Carrier", "year_built": 2003, "flag_list": "grey", "iacs_member": False,
         "class_status": "conditions", "psc_inspections": 11, "psc_deficiencies": 47, "psc_detentions": 3,
         "owner_inspections": 18, "owner_deficiencies": 71, "owner_detentions": 4, "sanctions_match": False}


def test_score_shape_and_range():
    r = run_tool("score_risk", RUSTY)
    assert 0 <= r["total"] <= 100
    assert set(r["vessel"]["factors"]) == {"age", "psc", "flag", "class_society", "class_status", "vessel_type"}
    assert set(r["owner"]["factors"]) == {"fleet_detentions", "fleet_deficiencies"}


def test_riskier_ship_scores_higher():
    clean = dict(RUSTY, year_built=2019, flag_list="white", iacs_member=True, class_status="in_class",
                 psc_inspections=9, psc_deficiencies=4, psc_detentions=0,
                 owner_inspections=62, owner_deficiencies=98, owner_detentions=1)
    assert run_tool("score_risk", RUSTY)["total"] > run_tool("score_risk", clean)["total"]


def test_tool_errors_are_reported_not_raised():
    assert "error" in run_tool("score_risk", {"bad": 1})
    assert "error" in run_tool("no_such_tool", {})


def test_mock_agent_declines_sanctioned_vessel():
    assert "DECLINE" in run_mock("Assess IMO 9900003", lambda e: None)


def test_owner_names_match_loosely_but_sanctions_only_flag_possible():
    assert run_tool("get_owner_record", {"owner_name": "DEMO OPAQUE HOLDINGS S.A."})["found"]
    r = run_tool("check_sanctions", {"imo": "1", "owner_name": "Demo Sanctioned Trading Company Ltd."})
    assert r["match"] is False and r["possible_match"] is True
