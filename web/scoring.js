// Risk score for the web form: vessel (0-50) + owner (0-50) = total (0-100).
// Mirror of agent/tools/scoring.py. Same config (risk_config.json), same
// formulas, same half-up rounding. tests/test_scoring.py checks they agree.

const r1 = x => Math.floor(x * 10 + 0.5) / 10;
const r2 = x => Math.floor(x * 100 + 0.5) / 100;
const r0 = x => Math.floor(x + 0.5);
const clamp01 = x => Math.max(0, Math.min(1, x));
const known = v => v !== null && v !== undefined && v !== '';
const int = v => (known(v) ? parseInt(v, 10) || 0 : 0);

export function scoreVesselPart(cfg, inp, asOfYear) {
  const c = cfg.vessel, missing = [], factors = {};

  const a = c.age;
  if (known(inp.year_built)) {
    const age = asOfYear - int(inp.year_built);
    factors.age = { label: 'Vessel age', points: r1(a.max * clamp01((age - a.min_years) / (a.full_years - a.min_years))),
                    max: a.max, detail: `${age} years old` };
  } else {
    factors.age = { label: 'Vessel age', points: a.max, max: a.max, detail: 'year built unknown, scored at max' };
    missing.push('year_built');
  }

  const p = c.psc;
  const n = int(inp.psc_inspections), det = int(inp.psc_detentions), dfc = int(inp.psc_deficiencies);
  const raw = n > 0
    ? p.detention_weight * clamp01((det / n) / p.detention_rate_full)
      + p.deficiency_weight * clamp01((dfc / n) / p.deficiencies_per_inspection_full)
    : 0;
  const z = n / (n + p.k);
  factors.psc = { label: 'Vessel PSC record', points: r1(p.max * (z * raw + (1 - z) * p.peer_index)), max: p.max,
                  detail: `${n} inspections, ${dfc} deficiencies, ${det} detentions; credibility ${r2(z)}` };

  const f = c.flag;
  let key = String(inp.flag_list || 'unknown').trim().toLowerCase();
  if (!(key in f.points)) key = 'unknown';
  if (key === 'unknown') missing.push('flag_list');
  factors.flag = { label: 'Flag', points: f.points[key], max: f.max, detail: `${key} list` };

  const cs = c.class_society;
  if (!known(inp.iacs_member)) { key = 'unknown'; missing.push('iacs_member'); }
  else key = [true, 'true', 'yes', 1].includes(inp.iacs_member) ? 'iacs' : 'non_iacs';
  factors.class_society = { label: 'Class society', points: cs.points[key], max: cs.max,
                            detail: { iacs: 'IACS member', non_iacs: 'not IACS', unknown: 'unknown' }[key] };

  const st = c.class_status;
  key = String(inp.class_status || 'unknown').trim().toLowerCase();
  if (!(key in st.points)) key = 'unknown';
  if (key === 'unknown') missing.push('class_status');
  factors.class_status = { label: 'Class status', points: st.points[key], max: st.max, detail: st.labels[key] };

  const vt = c.vessel_type;
  key = inp.vessel_type in vt.points ? inp.vessel_type : 'Other';
  if (!known(inp.vessel_type)) missing.push('vessel_type');
  factors.vessel_type = { label: 'Vessel type', points: vt.points[key], max: vt.max, detail: key };

  const score = r1(Object.values(factors).reduce((s, x) => s + x.points, 0));
  return { score, max: c.max, factors, credibility_z: r2(z), missing };
}

export function scoreOwnerPart(cfg, inp) {
  const c = cfg.owner;
  const n = int(inp.owner_inspections), det = int(inp.owner_detentions), dfc = int(inp.owner_deficiencies);
  const z = n / (n + c.k), d = c.detention, f = c.deficiency;
  const detIdx = n ? clamp01((det / n) / d.rate_full) : 0;
  const detBase = clamp01(d.baseline_rate / d.rate_full);
  const dfcIdx = n ? clamp01((dfc / n) / f.per_inspection_full) : 0;
  const dfcBase = clamp01(f.baseline_per_inspection / f.per_inspection_full);
  const factors = {
    fleet_detentions: { label: 'Owner fleet detentions', points: r1(d.max * (z * detIdx + (1 - z) * detBase)), max: d.max,
                        detail: n ? `${det} detentions in ${n} fleet inspections` : 'no fleet record, industry baseline' },
    fleet_deficiencies: { label: 'Owner fleet deficiencies', points: r1(f.max * (z * dfcIdx + (1 - z) * dfcBase)), max: f.max,
                          detail: n ? `${dfc} deficiencies in ${n} fleet inspections` : 'no fleet record, industry baseline' },
  };
  return { score: r1(Object.values(factors).reduce((s, x) => s + x.points, 0)), max: c.max, factors,
           credibility_z: r2(z), missing: n ? [] : ['owner_fleet_record'] };
}

export function scoreRisk(cfg, inp, asOfYear = new Date().getFullYear()) {
  const v = scoreVesselPart(cfg, inp, inp.as_of_year || asOfYear);
  const o = scoreOwnerPart(cfg, inp);
  const total = r1(v.score + o.score);
  let rec = cfg.recommendation.bands.find(b => total < b.below).label;
  const overrides = [], notes = [];
  if ([true, 'true', 1].includes(inp.sanctions_match))
    overrides.push('Sanctions match on vessel or owner: automatic DECLINE');
  if (String(inp.class_status || '').trim().toLowerCase() === 'suspended')
    overrides.push('Class suspended or withdrawn: hull cover requires class, automatic DECLINE');
  if (overrides.length) rec = 'DECLINE';
  if (v.credibility_z < cfg.thin_data_z) notes.push('Thin vessel PSC record: score leans on the peer baseline');
  if (o.credibility_z < cfg.thin_data_z) notes.push('Thin owner fleet record: score leans on the industry baseline');
  return { total, vessel_score: v.score, owner_score: o.score, vessel: v, owner: o,
           recommendation: rec, overrides, notes, missing: [...v.missing, ...o.missing],
           model_version: cfg.model_version };
}

export function pricePremium(cfg, score, insuredValue) {
  const p = cfg.pricing;
  const relativity = p.relativity_intercept + p.relativity_slope * Number(score);
  const expectedLoss = p.base_rate * Number(insuredValue) * relativity;
  const premium = expectedLoss * (1 + p.loading);
  return {
    relativity: Math.floor(relativity * 100 + 0.5) / 100,
    expected_loss_usd: r0(expectedLoss),
    premium_usd: r0(premium),
    rate_on_value_pct: Math.floor(100 * premium / Number(insuredValue) * 1000 + 0.5) / 1000,
    model_version: cfg.model_version,
  };
}
