# Data Collection Guide

How to replace the fictional demo ships with real data. Target: about 50 bulk carriers that called at U.S. ports.

## 1. Sanctions list (one command)

On your own computer (the OFAC site isn't reachable from every network):

```bash
python -m pipeline.fetch_ofac
```

This writes `data/processed/sanctions.csv`. If the download fails, grab `SDN.CSV` from the OFAC Sanctions List Service in a browser and run `python -m pipeline.fetch_ofac --file SDN.CSV`. Public data, safe to commit.

## 2. Vessel spreadsheet (by hand)

Copy `data/processed/vessels_template.csv` to `data/processed/vessels.csv` and fill one row per ship.

| Column | Where to get it | Notes |
|---|---|---|
| `imo` | Equasis / USCG PSIX | 7 digits; the validator checks the check digit |
| `name`, `type`, `year_built`, `gross_tonnage` | Equasis ship info | `type` = "Bulk Carrier" for our cohort |
| `flag` | Equasis | Country name |
| `flag_list` | Paris MOU white/grey/black list (current year) | `white`, `grey`, or `black` |
| `class_society`, `iacs_member` | Equasis classification section | `true` if DNV, ABS, LR, BV, ClassNK, KR, RINA, CCS, IRS, CRS, PRS, TL |
| `owner` | Equasis registered owner | Exact spelling helps the sanctions match |
| `insured_value_usd` | Our estimate | Ask Yuvraj for the valuation rule; leave blank if unknown |
| `psc_inspections`, `psc_deficiencies`, `psc_detentions` | Equasis PSC section (all MOUs), or USCG PSIX for U.S. only | Count over the same window for every ship, e.g. last 36 months |
| `psc_last_inspection` | Same | `YYYY-MM-DD` |
| `source`, `date_pulled` | You | e.g. `Equasis + USCG PSIX`, `2026-11-05` |

**Equasis rule:** its terms don't allow scraping or redistributing raw data. Look ships up by hand and only record the fields above. Don't commit screenshots or exports.

## 3. Check it

```bash
python -m pipeline.validate_vessels
```

Fix anything it flags (usually a mistyped IMO or a misspelled flag list), then commit. Once `vessels.csv` exists, the agent uses it automatically instead of the demo ships.
