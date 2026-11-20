"""Tiny self-contained HTML report builder for the validation and fairness scripts.

One chart type is all we need: a column chart for one measure across a few
categories, with optional 95% interval whiskers, value labels on the caps,
a hover tooltip per column, and a table view under it. No dependencies.
Colors follow a validated single-series palette (light and dark).
"""
import html
import math

CSS = """
.viz-root { color-scheme: light;
  --page: #f9f9f7; --surface-1: #fcfcfb; --text-primary: #0b0b0b; --text-secondary: #52514e;
  --muted: #898781; --grid: #e1e0d9; --axis: #c3c2b7; --series-1: #2a78d6; --border: rgba(11,11,11,0.10);
  --warn-bg: #fff4e5; --warn-ink: #6b3d00; }
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) .viz-root { color-scheme: dark;
    --page: #0d0d0d; --surface-1: #1a1a19; --text-primary: #f0efec; --text-secondary: #c3c2b7;
    --muted: #898781; --grid: #2c2c2a; --axis: #383835; --series-1: #3987e5; --border: rgba(255,255,255,0.10);
    --warn-bg: #2b1d05; --warn-ink: #f5c77e; }
}
:root[data-theme="dark"] .viz-root { color-scheme: dark;
  --page: #0d0d0d; --surface-1: #1a1a19; --text-primary: #f0efec; --text-secondary: #c3c2b7;
  --muted: #898781; --grid: #2c2c2a; --axis: #383835; --series-1: #3987e5; --border: rgba(255,255,255,0.10);
  --warn-bg: #2b1d05; --warn-ink: #f5c77e; }
* { box-sizing: border-box; }
body { margin: 0; }
.viz-root { background: var(--page); color: var(--text-primary); min-height: 100vh;
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; padding: 24px 16px; }
.wrap { max-width: 860px; margin: 0 auto; }
h1 { font-size: 22px; margin: 0 0 4px; }
.sub { color: var(--text-secondary); margin: 0 0 20px; }
.banner { background: var(--warn-bg); color: var(--warn-ink); border-radius: 8px; padding: 10px 14px;
  margin: 0 0 20px; font-weight: 600; }
.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 16px;
  margin-bottom: 20px; }
.card h2 { font-size: 16px; margin: 0 0 2px; }
.card .lede { color: var(--text-secondary); margin: 0 0 12px; font-size: 14px; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 20px; }
.stat { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; }
.stat .label { color: var(--text-secondary); font-size: 13px; }
.stat .value { font-size: 26px; font-weight: 700; line-height: 1.2; }
.stat .note { color: var(--muted); font-size: 12px; }
.chart { position: relative; }
.chart svg { display: block; width: 100%; height: auto; overflow: visible; }
.tip { position: absolute; pointer-events: none; background: var(--surface-1); color: var(--text-primary);
  border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; font-size: 13px;
  box-shadow: 0 2px 8px rgba(0,0,0,.12); white-space: nowrap; opacity: 0; transition: opacity .1s; }
table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 12px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--grid); }
th { color: var(--text-secondary); font-weight: 600; }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; }
details summary { cursor: pointer; color: var(--text-secondary); font-size: 13px; margin-top: 8px; }
.foot { color: var(--muted); font-size: 12px; margin-top: 8px; }
ul { margin: 0; padding-left: 20px; }
"""

JS = """
document.querySelectorAll('.chart').forEach(chart => {
  const tip = chart.querySelector('.tip');
  chart.querySelectorAll('[data-tip]').forEach(hit => {
    const show = e => {
      tip.textContent = hit.dataset.tip; tip.style.opacity = 1;
      const box = chart.getBoundingClientRect(), r = hit.getBoundingClientRect();
      const x = Math.min(Math.max(r.left + r.width / 2 - box.left - tip.offsetWidth / 2, 0), box.width - tip.offsetWidth);
      tip.style.left = x + 'px'; tip.style.top = Math.max(r.top - box.top - tip.offsetHeight - 6, 0) + 'px';
    };
    hit.addEventListener('mouseenter', show); hit.addEventListener('focus', show);
    hit.addEventListener('mouseleave', () => tip.style.opacity = 0);
    hit.addEventListener('blur', () => tip.style.opacity = 0);
  });
});
"""

e = html.escape


def _axis(vmax: float):
    """Clean ticks: a step of 1, 2 or 5 x 10^n giving at most 5 intervals."""
    vmax = max(vmax, 1e-9)
    raw = vmax / 5
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)
    top = math.ceil(vmax / step) * step
    return top, [i * step for i in range(int(round(top / step)) + 1)]


def column_chart(rows, value_fmt, axis_title, aria_label):
    """rows: [{"label", "value", "lo"?, "hi"?, "tip"}]. Returns an HTML block."""
    W, H, left, right, top, bottom = 760, 300, 56, 16, 28, 44
    pw, ph = W - left - right, H - top - bottom
    vmax, ticks = _axis(max([r.get("hi", r["value"]) for r in rows] + [0]) * 1.05)
    y = lambda v: top + ph - (v / vmax) * ph
    band = pw / len(rows)
    bw = 24  # thin columns: the leftover band is air
    parts = []
    for i, v in enumerate(ticks):
        parts.append(f'<line x1="{left}" x2="{W - right}" y1="{y(v):.1f}" y2="{y(v):.1f}" '
                     f'stroke="var({"--axis" if i == 0 else "--grid"})" stroke-width="1"/>')
        parts.append(f'<text x="{left - 8}" y="{y(v) + 4:.1f}" text-anchor="end" font-size="12" '
                     f'fill="var(--muted)" style="font-variant-numeric:tabular-nums">{e(value_fmt(v, axis=True))}</text>')
    parts.append(f'<text x="{left}" y="14" font-size="12" fill="var(--text-secondary)">{e(axis_title)}</text>')
    for i, r in enumerate(rows):
        cx = left + band * (i + 0.5)
        x0, v = cx - bw / 2, r["value"]
        yt, yb = y(v), y(0)
        rad = min(4, max(0, yb - yt))
        path = (f"M{x0:.1f},{yb:.1f} V{yt + rad:.1f} Q{x0:.1f},{yt:.1f} {x0 + rad:.1f},{yt:.1f} "
                f"H{x0 + bw - rad:.1f} Q{x0 + bw:.1f},{yt:.1f} {x0 + bw:.1f},{yt + rad:.1f} V{yb:.1f} Z")
        parts.append(f'<path d="{path}" fill="var(--series-1)"/>')
        label_y = yt
        if "lo" in r and "hi" in r:
            ylo, yhi = y(r["lo"]), y(r["hi"])
            parts.append(f'<g stroke="var(--text-secondary)" stroke-width="1.5">'
                         f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{yhi:.1f}" y2="{ylo:.1f}"/>'
                         f'<line x1="{cx - 6:.1f}" x2="{cx + 6:.1f}" y1="{yhi:.1f}" y2="{yhi:.1f}"/>'
                         f'<line x1="{cx - 6:.1f}" x2="{cx + 6:.1f}" y1="{ylo:.1f}" y2="{ylo:.1f}"/></g>')
            label_y = min(label_y, yhi)
        parts.append(f'<text x="{cx:.1f}" y="{label_y - 8:.1f}" text-anchor="middle" font-size="13" font-weight="600" '
                     f'fill="var(--text-primary)">{e(value_fmt(v))}</text>')
        parts.append(f'<text x="{cx:.1f}" y="{H - bottom + 18}" text-anchor="middle" font-size="12" '
                     f'fill="var(--text-secondary)">{e(r["label"])}</text>')
        parts.append(f'<rect x="{cx - band / 2 + 2:.1f}" y="{top}" width="{band - 4:.1f}" height="{ph}" fill="transparent" '
                     f'tabindex="0" data-tip="{e(r["tip"])}" aria-label="{e(r["tip"])}"/>')
    svg = (f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{e(aria_label)}">' + "".join(parts) + "</svg>")
    return f'<div class="chart">{svg}<div class="tip" role="status"></div></div>'


def table(headers, rows, numeric_cols=()):
    head = "".join(f'<th class="{"n" if i in numeric_cols else ""}">{e(h)}</th>' for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(f'<td class="{"n" if i in numeric_cols else ""}">{e(str(c))}</td>'
                                    for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def stat(label, value, note=""):
    return (f'<div class="stat"><div class="label">{e(label)}</div><div class="value">{e(value)}</div>'
            f'<div class="note">{e(note)}</div></div>')


def page(title, subtitle, body, banner=None):
    b = f'<div class="banner">{e(banner)}</div>' if banner else ""
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'><title>{e(title)}</title>"
            f"<style>{CSS}</style></head><body><div class='viz-root'><div class='wrap'>"
            f"<h1>{e(title)}</h1><p class='sub'>{e(subtitle)}</p>{b}{body}</div></div>"
            f"<script>{JS}</script></body></html>")
