// Risk score for the web form: vessel (0-50) + owner (0-50) = total (0-100).
// Mirror of agent/tools/scoring.py. Same config (risk_config.json), same
// formulas, same half-up rounding, same error messages.
// tests/test_scoring.py checks the two agree.

const r1 = x => Math.floor(x * 10 + 0.5) / 10;
const r2 = x => Math.floor(x * 100 + 0.5) / 100;
const r0 = x => Math.floor(x + 0.5);
const clamp01 = x => Math.max(0, Math.min(1, x));
const known = v => v !== null && v !== undefined && v !== '';
const truthy = v => v === true || v === 1 || (typeof v === 'string' && ['true', 'yes', '1'].includes(v.trim().toLowerCase()));

const COUNT_FIELDS = ['psc_inspections', 'psc_deficiencies', 'psc_detentions',
                      'owner_inspections', 'owner_deficiencies', 'owner_detentions'];

// Parse a whole number: [value, ok]. Blank counts as 0.
function whole(v) {
  if (!known(v)) return [0, true];
  if (typeof v === 'boolean') return [0, false];
  if (typeof v === 'string' && !/^\s*-?\d+(\.\d+)?\s*$/.test(v)) return [0, false];
  const f = Number(v);
  if (!Number.isFinite(f) || f !== Math.floor(f)) return [0, false];
  return [f, true];
}

export function canonicalType(cfg, vesselType) {
  const vt = cfg.vessel.vessel_type;
  if (!known(vesselType)) return ['Other', false];
  const t = String(vesselType).trim();
  if (t in vt.points) return [t, true];
  const hit = vt.aliases[t.toLowerCase()];
  return hit ? [hit, true] : ['Other', false];
}

export function validateInputs(cfg, inp, asOfYear) {
  const errors = [], counts = {};
  for (const k of COUNT_FIELDS) {
    const [n, ok] = whole(inp[k]);
    if (!ok) errors.push(`${k} must be a whole number`);
    else if (n < 0) errors.push(`${k} can't be negative`);
    counts[k] = n;
  }
  for (const who of ['psc', 'owner'])
    if (counts[`${who}_detentions`] > counts[`${who}_inspections`])
      errors.push(`${who}_detentions can't exceed ${who}_inspections`);
  if (known(inp.year_built)) {
    const [y, ok] = whole(inp.year_built), lo = cfg.limits.min_year_built;
    if (!ok) errors.push('year_built must be a whole number');
    else if (y < lo || y > asOfYear) errors.push(`year_built must be between ${lo} and ${asOfYear}`);
  }
  return errors;
}

function scoreVesselPart(cfg, inp, asOfYear) {
  const c = cfg.vessel, missing = [], notes = [], factors = {};

  const a = c.age;
  if (known(inp.year_built)) {
    const age = asOfYear - whole(inp.year_built)[0];
    factors.age = { label: 'Vessel age', points: r1(a.max * clamp01((age - a.min_years) / (a.full_years - a.min_years))),
                    max: a.max, detail: `${age} years old` };
  } else {
    factors.age = { label: 'Vessel age', points: a.max, max: a.max, detail: 'year built unknown, scored at max' };
    missing.push('year_built');
  }

  const p = c.psc;
  const n = whole(inp.psc_inspections)[0], det = whole(inp.psc_detentions)[0], dfc = whole(inp.psc_deficiencies)[0];
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
  else key = truthy(inp.iacs_member) ? 'iacs' : 'non_iacs';
  factors.class_society = { label: 'Class society', points: cs.points[key], max: cs.max,
                            detail: { iacs: 'IACS member', non_iacs: 'not IACS', unknown: 'unknown' }[key] };

  const st = c.class_status;
  key = String(inp.class_status || 'unknown').trim().toLowerCase();
  if (!(key in st.points)) key = 'unknown';
  if (key === 'unknown') missing.push('class_status');
  factors.class_status = { label: 'Class status', points: st.points[key], max: st.max, detail: st.labels[key] };

  const vt = c.vessel_type;
  const [type, recognized] = canonicalType(cfg, inp.vessel_type);
  let detail = type;
  if (!known(inp.vessel_type)) { missing.push('vessel_type'); detail = 'unknown, scored as Other'; }
  else if (!recognized) {
    const t = String(inp.vessel_type).trim();
    notes.push(`Vessel type '${t}' is not in the model; scored as Other`);
    detail = `${t}, scored as Other`;
  }
  factors.vessel_type = { label: 'Vessel type', points: vt.points[type], max: vt.max, detail };

  const score = r1(Object.values(factors).reduce((s, x) => s + x.points, 0));
  return { score, max: c.max, factors, credibility_z: r2(z), missing, notes };
}

function scoreOwnerPart(cfg, inp) {
  const c = cfg.owner;
  const n = whole(inp.owner_inspections)[0], det = whole(inp.owner_detentions)[0], dfc = whole(inp.owner_deficiencies)[0];
  const z = n / (n + c.k), d = c.detention, f = c.deficiency;
  const detIdx = n ? clamp01((det / n) / d.rate_full) : 0;
  const detBase = clamp01(d.baseline_rate / d.rate_full);
  const dfcIdx = n ? clamp01((dfc / n) / f.per_inspection_full) : 0;
  const dfcBase = clamp01(f.baseline_per_inspection / f.per_inspection_full);
  const none = 'no fleet record, industry baseline';
  const factors = {
    fleet_detentions: { label: 'Owner fleet detentions', points: r1(d.max * (z * detIdx + (1 - z) * detBase)), max: d.max,
                        detail: n ? `${det} detentions in ${n} fleet inspections` : none },
    fleet_deficiencies: { label: 'Owner fleet deficiencies', points: r1(f.max * (z * dfcIdx + (1 - z) * dfcBase)), max: f.max,
                          detail: n ? `${dfc} deficiencies in ${n} fleet inspections` : none },
  };
  return { score: r1(Object.values(factors).reduce((s, x) => s + x.points, 0)), max: c.max, factors,
           credibility_z: r2(z), missing: n ? [] : ['owner_fleet_record'] };
}

export function scoreRisk(cfg, inp, asOfYear = new Date().getFullYear()) {
  const year = inp.as_of_year || asOfYear;
  const errors = validateInputs(cfg, inp, year);
  if (errors.length) return { error: 'Invalid input: ' + errors.join('; '), errors };

  const v = scoreVesselPart(cfg, inp, year);
  const o = scoreOwnerPart(cfg, inp);
  const total = r1(v.score + o.score);
  let rec = cfg.recommendation.bands.find(b => total < b.below).label;
  const overrides = [], notes = [...v.notes];
  if (truthy(inp.sanctions_match)) overrides.push('Sanctions match on vessel or owner: automatic DECLINE');
  if (String(inp.class_status || '').trim().toLowerCase() === 'suspended')
    overrides.push('Class suspended or withdrawn: hull cover requires class, automatic DECLINE');
  if (overrides.length) rec = 'DECLINE';
  else if (truthy(inp.sanctions_possible) && ['ACCEPT', 'ACCEPT WITH CONDITIONS'].includes(rec)) {
    overrides.push('Possible sanctions match on owner name: a person must confirm, raised to REFER');
    rec = 'REFER';
  }
  if (v.credibility_z < cfg.thin_data_z) notes.push('Thin vessel PSC record: score leans on the peer baseline');
  if (o.credibility_z < cfg.thin_data_z) notes.push('Thin owner fleet record: score leans on the industry baseline');
  return { total, vessel_score: v.score, owner_score: o.score, vessel: v, owner: o,
           recommendation: rec, overrides, notes, missing: [...v.missing, ...o.missing],
           model_version: cfg.model_version };
}

export function findRiskLevers(cfg, inp, asOfYear = new Date().getFullYear()) {
  const base = scoreRisk(cfg, inp, asOfYear);
  if (base.error) return base;
  const levers = [];
  for (const opt of cfg.levers.options) {
    const cur = inp[opt.field];
    if (!known(cur)) continue;
    const norm = typeof opt.to === 'boolean' ? truthy(cur) : String(cur).trim().toLowerCase();
    if (opt.unless.includes(norm)) continue;
    const r = scoreRisk(cfg, { ...inp, [opt.field]: opt.to }, asOfYear);
    const cut = r1(base.total - r.total);
    if (cut > 0) levers.push({ change: opt.label, field: opt.field, to: opt.to, new_total: r.total,
                               reduction: cut, new_recommendation: r.recommendation });
  }
  levers.sort((a, b) => b.reduction - a.reduction);
  return { current_total: base.total, current_recommendation: base.recommendation, levers,
           model_version: base.model_version };
}

export function pricePremium(cfg, score, insuredValue) {
  const p = cfg.pricing, value = Number(insuredValue);
  if (!Number.isFinite(value) || value <= 0) return { error: 'insured_value_usd must be greater than 0' };
  const relativity = p.relativity_intercept + p.relativity_slope * Number(score);
  const expectedLoss = p.base_rate * value * relativity;
  const premium = expectedLoss * (1 + p.loading);
  return {
    relativity: r2(relativity),
    expected_loss_usd: r0(expectedLoss),
    premium_usd: r0(premium),
    rate_on_value_pct: Math.floor(100 * premium / value * 1000 + 0.5) / 1000,
    model_version: cfg.model_version,
  };
}
