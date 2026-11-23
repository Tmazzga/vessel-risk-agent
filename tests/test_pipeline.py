"""Tests for the data pipeline: OFAC parsing, vessel CSV validation, and the
data tools reading processed files. All fixtures are fictional."""
from pathlib import Path

from agent.tools import data_tools
from pipeline.fetch_ofac import parse_sdn
from pipeline.validate_vessels import imo_valid, validate, validate_owners

FIX = Path(__file__).parent / "fixtures"


def test_imo_check_digit():
    assert imo_valid("1000007")
    assert not imo_valid("1000008")
    assert not imo_valid("123456")
    assert not imo_valid("abcdefg")


def test_parse_sdn_extracts_imo_and_cleans_blanks():
    rows = parse_sdn((FIX / "sdn_sample.csv").read_text())
    assert len(rows) == 3
    tanker = rows[0]
    assert tanker["imo"] == "1000007"
    assert tanker["sdn_type"] == "vessel"
    assert tanker["vess_owner"] == "Demo Shadow Shipping Ltd"
    assert rows[1]["imo"] == "" and rows[1]["sdn_type"] == "entity"  # "-0-" cleaned


def test_validator_passes_good_file():
    assert validate(FIX / "vessels_good.csv") == []


def test_validator_catches_typos(tmp_path):
    good = (FIX / "vessels_good.csv").read_text().splitlines()
    bad_row = good[1].replace("1000007", "1000008").replace(",grey,", ",gray,")
    f = tmp_path / "bad.csv"
    f.write_text("\n".join([good[0], bad_row, good[1], good[1]]) + "\n")
    problems = " ".join(validate(f))
    assert "check digit" in problems
    assert "flag_list" in problems
    assert "duplicate IMO" in problems


def _use(monkeypatch, vessels=None, sanctions=None, tmp_path=None):
    data_tools._vessels.cache_clear()
    data_tools._sanctions.cache_clear()
    monkeypatch.setattr(data_tools, "VESSELS_CSV", vessels or tmp_path / "none.csv")
    monkeypatch.setattr(data_tools, "SANCTIONS_CSV", sanctions or tmp_path / "none.csv")


def test_tools_read_processed_files(monkeypatch, tmp_path):
    rows = parse_sdn((FIX / "sdn_sample.csv").read_text())
    sanc = tmp_path / "sanctions.csv"
    import csv
    with sanc.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    _use(monkeypatch, FIX / "vessels_good.csv", sanc, tmp_path)
    try:
        assert data_tools.data_mode() == "processed"
        prof = data_tools.get_vessel_profile("1000007")
        assert prof["found"] and prof["year_built"] == 2005 and prof["iacs_member"] is False
        assert data_tools.get_psc_history("1000007")["detentions"] == 2
        by_imo = data_tools.check_sanctions("1000007")
        assert by_imo["match"] and by_imo["hits"][0]["matched_on"] == "imo"
        by_owner = data_tools.check_sanctions("0000000", "demo shadow shipping ltd.")
        assert by_owner["match"] and by_owner["hits"][0]["matched_on"] == "owner_name"
    finally:
        data_tools._vessels.cache_clear()
        data_tools._sanctions.cache_clear()


def test_falls_back_to_sample_data(monkeypatch, tmp_path):
    _use(monkeypatch, tmp_path=tmp_path)
    try:
        assert data_tools.data_mode() == "sample"
        assert data_tools.get_vessel_profile("9900001")["found"]
    finally:
        data_tools._vessels.cache_clear()
        data_tools._sanctions.cache_clear()


def test_owner_validator(tmp_path):
    f = tmp_path / "owners.csv"
    f.write_text("owner,fleet_size,inspections,deficiencies,detentions,period,source,date_pulled\n"
                 "Demo Co,4,10,12,1,last 36 months,test,2026-11-20\n"
                 "demo co,4,10,12,11,last 36 months,test,2026-11-20\n")
    problems = " ".join(validate_owners(f))
    assert "duplicate owner" in problems and "more detentions" in problems
