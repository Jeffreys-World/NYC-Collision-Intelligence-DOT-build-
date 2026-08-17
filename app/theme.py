"""CSS tokens from DESIGN.md §1, injected once per run.

`.streamlit/config.toml` sets the base theme (surfaces, accent). This module
carries what the theme API cannot express: the severity ramp, the
completeness hatch, KPI row styling, and the `#B4232C`-on-`#0E1119`
focus-contrast fix DESIGN.md §1 calls out by name.

No font-face block here — DESIGN.md §2 wants IBM Plex self-hosted as woff2,
and the files are not committed yet (see the comment in config.toml). Adding
`font-family` overrides without the files would silently fall back to the
system stack, which is the exact failure the self-hosting decision exists to
avoid. Tracked as an open item, not shipped half-done.
"""

from __future__ import annotations

import streamlit as st

CSS = """
<style>
:root {
  --base:#0F1419; --panel:#161C22; --panel-2:#1C242C; --line:#2A343E;
  --ink:#E6EDF3; --ink-dim:#8B98A5; --ink-faint:#5C6873;

  --sev-1:#2E7D5B; --sev-2:#C9A227; --sev-3:#D97706; --sev-4:#B4232C;

  --expected:#4C9BE8;
  --incomplete-ink:#8B98A5;
  --incomplete-fill: repeating-linear-gradient(45deg, #5C6873 0 2px, transparent 2px 5px);

  --vru:#B57EDC;
}

/* KPI rows: label left, value right, hairline separators. Never a bare number
   or a bordered card — §5/DESIGN.md §4 reserve cards for countermeasures. */
.kpi-row {
  display: flex; justify-content: space-between; align-items: baseline;
  padding: 0.5rem 0; border-bottom: 1px solid var(--line);
  font-variant-numeric: tabular-nums;
}
.kpi-row:last-child { border-bottom: none; }
.kpi-label { color: var(--ink-dim); font-size: 0.875rem; }
.kpi-value { color: var(--ink); font-size: 1.25rem; font-weight: 600; }
.kpi-qualifier { color: var(--ink-faint); font-size: 0.75rem; display: block; }

/* Completeness badge: neutral + hatch, never a severity hue (§1 / §2.6). */
.completeness-badge {
  display: inline-flex; align-items: center; gap: 0.5rem;
  padding: 0.35rem 0.6rem; border: 1px solid var(--line); border-radius: 4px;
  background-image: var(--incomplete-fill);
  color: var(--incomplete-ink); font-size: 0.8125rem;
}

/* Demo-safety banner: full-width, unmissable, per §4.2. currentColor keeps the
   focus/border contrast correct instead of the ~2.9:1 #B4232C-on-base pairing
   DESIGN.md flags as a measured failure. */
.trust-banner {
  border: 2px solid var(--sev-4); color: var(--sev-4); background: rgba(180,35,44,0.12);
  padding: 0.75rem 1rem; border-radius: 6px; font-weight: 600; margin-bottom: 0.75rem;
}

/* Road-class control and CMF caveat block share this quieter treatment. */
.info-box {
  border: 1px solid var(--line); background: var(--panel-2);
  padding: 0.75rem 1rem; border-radius: 6px; color: var(--ink-dim); font-size: 0.875rem;
}

/* Legend: always visible wherever >1 colour channel is in play (§1). */
.legend { display: flex; flex-wrap: wrap; gap: 1rem; font-size: 0.75rem; color: var(--ink-dim); }
.legend-item { display: flex; align-items: center; gap: 0.4rem; }
.legend-swatch { width: 12px; height: 12px; border-radius: 2px; display: inline-block; }

@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; scroll-behavior: auto !important; }
}
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def kpi_row(label: str, value: str, qualifier: str = "") -> None:
    qualifier_html = f'<span class="kpi-qualifier">{qualifier}</span>' if qualifier else ""
    st.markdown(
        f'<div class="kpi-row"><span class="kpi-label">{label}{qualifier_html}</span>'
        f'<span class="kpi-value">{value}</span></div>',
        unsafe_allow_html=True,
    )
