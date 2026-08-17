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

# DESIGN.md specifies dark as the app's one committed look — DARK_VARS is the
# source of truth. LIGHT_VARS is a runtime preference layered on top (a plain
# CSS variable swap via the toggle in the UI), not a second design: every
# severity/completeness/expected-vs-observed rule from DESIGN.md §1 still
# applies, just repainted for a white surface at the same contrast targets
# (§5: >=4.5:1 body text, >=3:1 focus/non-text marks).
DARK_VARS = """
  --base:#0F1419; --panel:#161C22; --panel-2:#1C242C; --line:#2A343E;
  --ink:#E6EDF3; --ink-dim:#8B98A5; --ink-faint:#5C6873;
  --sev-1:#2E7D5B; --sev-2:#C9A227; --sev-3:#D97706; --sev-4:#B4232C;
  --expected:#4C9BE8;
  --incomplete-ink:#8B98A5;
  --incomplete-fill: repeating-linear-gradient(45deg, #5C6873 0 2px, transparent 2px 5px);
  --vru:#B57EDC;
"""

LIGHT_VARS = """
  --base:#FFFFFF; --panel:#F5F7F9; --panel-2:#ECEFF2; --line:#D3DAE0;
  --ink:#14181D; --ink-dim:#4A545E; --ink-faint:#6B7580;
  --sev-1:#1F6B4A; --sev-2:#8A6A15; --sev-3:#A85705; --sev-4:#A01D26;
  --expected:#1D5FA3;
  --incomplete-ink:#4A545E;
  --incomplete-fill: repeating-linear-gradient(45deg, #6B7580 0 2px, transparent 2px 5px);
  --vru:#8F4FBF;
"""

# Streamlit's own chrome is set dark via .streamlit/config.toml at process
# start and can't be swapped per-session through that file, so light mode
# needs its native containers overridden directly or the toggle would only
# repaint the custom KPI/legend/badge elements below and leave the rest dark.
LIGHT_APP_OVERRIDES = """
.stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
  background-color: var(--base) !important; color: var(--ink) !important;
}
[data-testid="stSidebar"], [data-testid="stExpander"] details,
div[data-baseweb="popover"], div[data-baseweb="select"], div[data-baseweb="select"] *,
div[data-baseweb="menu"], li[role="option"] {
  background-color: var(--panel) !important; color: var(--ink) !important;
  border-color: var(--line) !important;
}
input, textarea, [data-baseweb="input"], [data-baseweb="base-input"] {
  background-color: var(--panel) !important; color: var(--ink) !important;
}
/* Buttons (kind="header"/"secondary"/"primary" — Deploy, the popover
   trigger, download buttons) were the worst offender: black box, invisible
   text on white. */
button, [data-testid^="stBaseButton"] {
  background-color: var(--panel) !important; color: var(--ink) !important;
  border-color: var(--line) !important;
}
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li,
label, .stMarkdown, h1, h2, h3, h4 { color: var(--ink) !important; }
[data-testid="stDataFrame"] { filter: invert(1) hue-rotate(180deg); }
hr, [data-testid="stDivider"] { border-color: var(--line) !important; }
/* Toggle/checkbox tracks default to a low-contrast colour tuned for the dark
   background; give the unchecked state a visible outline on white. */
[role="switch"], [role="checkbox"] {
  border: 1px solid var(--line) !important;
}
"""

STATIC_CSS = """
/* KPI rows: label left, value right, hairline separators. Never a bare number
   or a bordered card - Section 5/DESIGN.md Section 4 reserve cards for
   countermeasures. */
.kpi-row {
  display: flex; justify-content: space-between; align-items: baseline;
  padding: 0.5rem 0; border-bottom: 1px solid var(--line);
  font-variant-numeric: tabular-nums;
}
.kpi-row:last-child { border-bottom: none; }
.kpi-label { color: var(--ink-dim); font-size: 0.875rem; }
.kpi-value { color: var(--ink); font-size: 1.25rem; font-weight: 600; }
.kpi-qualifier { color: var(--ink-faint); font-size: 0.75rem; display: block; }

/* Completeness badge: neutral + hatch, never a severity hue. */
.completeness-badge {
  display: inline-flex; align-items: center; gap: 0.5rem;
  padding: 0.35rem 0.6rem; border: 1px solid var(--line); border-radius: 4px;
  background-image: var(--incomplete-fill);
  color: var(--incomplete-ink); font-size: 0.8125rem;
}

/* Demo-safety banner: full-width, unmissable, per Section 4.2. currentColor
   keeps the focus/border contrast correct instead of the ~2.9:1
   #B4232C-on-base pairing DESIGN.md flags as a measured failure. */
.trust-banner {
  border: 2px solid var(--sev-4); color: var(--sev-4); background: rgba(180,35,44,0.12);
  padding: 0.75rem 1rem; border-radius: 6px; font-weight: 600; margin-bottom: 0.75rem;
}

/* Road-class control and CMF caveat block share this quieter treatment. */
.info-box {
  border: 1px solid var(--line); background: var(--panel-2);
  padding: 0.75rem 1rem; border-radius: 6px; color: var(--ink-dim); font-size: 0.875rem;
}

/* Legend: always visible wherever >1 colour channel is in play. */
.legend { display: flex; flex-wrap: wrap; gap: 1rem; font-size: 0.75rem; color: var(--ink-dim); }
.legend-item { display: flex; align-items: center; gap: 0.4rem; }
.legend-swatch { width: 12px; height: 12px; border-radius: 2px; display: inline-block; }

@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; scroll-behavior: auto !important; }
}
"""


def inject(mode: str = "dark") -> None:
    variables = LIGHT_VARS if mode == "light" else DARK_VARS
    overrides = LIGHT_APP_OVERRIDES if mode == "light" else ""
    css = "<style>\n:root {\n" + variables + "\n}\n" + overrides + STATIC_CSS + "</style>"
    st.markdown(css, unsafe_allow_html=True)


def kpi_row(label: str, value: str, qualifier: str = "") -> None:
    qualifier_html = f'<span class="kpi-qualifier">{qualifier}</span>' if qualifier else ""
    st.markdown(
        f'<div class="kpi-row"><span class="kpi-label">{label}{qualifier_html}</span>'
        f'<span class="kpi-value">{value}</span></div>',
        unsafe_allow_html=True,
    )
