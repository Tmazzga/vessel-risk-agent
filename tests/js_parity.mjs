// Helper for tests/test_scoring.py: scores cases with web/scoring.js.
// Usage: node tests/js_parity.mjs <cases.json>   -> prints results as JSON
import { readFileSync } from 'node:fs';
import { scoreRisk, pricePremium } from '../web/scoring.js';

const cfg = JSON.parse(readFileSync(new URL('../web/risk_config.json', import.meta.url)));
const cases = JSON.parse(readFileSync(process.argv[2]));
const out = cases.map(c => {
  const r = scoreRisk(cfg, c, c.as_of_year);
  return { score: r, price: c.insured_value_usd ? pricePremium(cfg, r.total, c.insured_value_usd) : null };
});
process.stdout.write(JSON.stringify(out));
