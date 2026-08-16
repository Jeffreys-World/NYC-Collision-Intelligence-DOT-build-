# DESIGN.md — NYC Collision Intelligence (DOT build)

Produced by `/plan-design-review` on 2026-08-15. This is the calibration source for every
UI decision in `CLAUDE_CODE_PROMPT.md` §5. Where the two disagree, this file wins.

Classifier: **APP UI** — a data-dense workspace for transit and safety engineers. Not a
landing page. Calm surface hierarchy, few colours, dense but readable, minimal chrome.

---

## 1. Colour: three independent channels

The palette inherited from the dashboard repo sets `C_DEATH` and `C_UNLABELED` to the same
`#B4232C` (`app/streamlit_app.py:29-30`). That was survivable when the two never shared a
chart. Here they share a screen, and §2.7 adds a third distinction on top. Three meanings
cannot ride one channel.

| Meaning | Channel | Why this channel |
|---|---|---|
| **Severity** — how much harm | **Hue** + opacity | Keeps §5's green→red ramp; opacity is a redundant channel so severity survives colour-vision deficiency |
| **Certainty** — observed vs expected | **Fill vs outline** | Survives greyscale and every form of CVD; the pair most dangerous to confuse |
| **Completeness** — records other tools drop | **Neutral + hatch** | Deliberately outside the severity ramp, so it can never read as a harm signal |
| **Vulnerable-road-user harm** | **Reserved hue** | §5's existing rule; used only in the victim-split chart, never on the map |

```css
:root{
  /* base surfaces */
  --base:#0F1419; --panel:#161C22; --panel-2:#1C242C; --line:#2A343E;
  --ink:#E6EDF3; --ink-dim:#8B98A5; --ink-faint:#5C6873;

  /* severity ramp — HUE channel, low to high harm */
  --sev-1:#2E7D5B; --sev-2:#C9A227; --sev-3:#D97706; --sev-4:#B4232C;

  /* certainty — expected uses the accent, observed uses outline-only */
  --expected:#4C9BE8;          /* reserved: EB figures and nothing else */
  --observed-stroke:1.5px;      /* outlined marks = observed, no EB match */

  /* completeness — neutral, never a severity hue */
  --incomplete-ink:var(--ink-dim);
  --incomplete-fill:repeating-linear-gradient(45deg,var(--ink-faint) 0 2px,transparent 2px 5px);

  /* vulnerable road users — reserved, victim-split chart only */
  --vru:#B57EDC;
}
```

**Hard rules.**
- `--expected` appears on EB figures and nowhere else. If it shows up on a button, it is a bug.
- Completeness never borrows a severity hue. It is neutral plus texture, always.
- A legend is always visible wherever more than one channel is in play. A three-channel
  system with no legend is a puzzle.
- Body text ≥16px. Contrast ≥4.5:1 for body, ≥3:1 for focus indicators and non-text marks.
  Note the measured precedent: `#B4232C` on `#0E1117` is ~2.9:1 and **fails** the 3:1 focus
  bar — the dashboard repo hit this and switched to `currentColor`. Do not re-introduce it.

---

## 2. Typography

Self-hosted, declared via Streamlit's theme `fontFaces`. **No CDN.** §1.1 chose a committed
Parquet so nothing can fail on stage; a font request that a venue network blocks is the same
class of risk, and it changes the app's appearance live.

| Role | Face | Notes |
|---|---|---|
| Headings | **IBM Plex Sans Condensed** | The "condensed grotesque" §5 asks for, named |
| Figures | **IBM Plex Mono** | Columns align; §5's requirement |
| Body | **IBM Plex Sans** | Same family, so the three read as one voice |

Commit the woff2 files. Never `system-ui`, `-apple-system`, Inter, Roboto or Arial as the
primary display face.

---

## 3. Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│ FRESHNESS LINE — persistent, every screen, opens "why the lag" ▾      │
├──────────────────────────────────────────────────────────────────────┤
│ CONTROL BAR — corridor ▾ · casualty toggle · date range   [sticky]    │
├───────────────────────────────────────────┬──────────────────────────┤
│                                           │ DRAWER  320–360px        │
│  MAP  ≥65% of width, never less           │                          │
│  ColumnLayer on pre-binned centroids      │ Belt Pkwy                │
│  hue = expected harm (EB)                 │ HIGHWAY ▾  (correctable) │
│  outlined bins = observed only            │ ──────────────────────   │
│                                           │ Casualty crashes  4,893  │
│                                           │ Killed               55  │
│                                           │ Expected harm      38.4  │
│                                           │ ▨ Includes 10,963 …      │
└───────────────────────────────────────────┴──────────────────────────┘
```

- **Drawer is a real `st.columns` column, not a CSS overlay.** Injected CSS re-applies with a
  delay on every rerun (documented in the dashboard repo's `DESIGN-SECTION-RAIL.md`), which
  would make the panel visibly jump mid-demo.
- **The map never drops below 65% of the content width.** §7's Belt Pkwy vs Atlantic Ave
  contrast is a map comparison; compress the map and the beat weakens.
- **Primary controls live in the sticky bar, not the sidebar.** Streamlit collapses the
  sidebar below ~768px, which is the width §5 names as a requirement — and the corridor
  dropdown is the designated accessible path (§5 below), so it must never hide.

### Breakpoints

| Width | Layout |
|---|---|
| ≥1280px | Control bar, map ~68%, drawer 360px |
| 820–1280px | Control bar, map ~62%, drawer 320px |
| <820px | Control bar stays; map full width; drawer stacks beneath, auto-scrolled to on selection |

Sidebar holds secondary settings only. Nothing required to operate the map lives there.

---

## 4. Components

**KPI figures are typographic rows, not cards.** Label left, value right on a shared baseline
grid, hairline separators, qualifier as small text beneath. Never a bare number — §5's rule
stands. Seven bordered tiles in a drawer is the stacked-card pattern and an instant fail for
app UI.

**Cards are reserved for countermeasure options**, which are genuinely selectable. That is the
only place a card is the interaction, so a boxed thing on screen always means "you can pick
this."

**Road class is a labelled, correctable control** at the top of the drawer, showing its basis.
The curated limited-access list fails silently when a road is missing from it; a visible
control turns that into something the engineer fixes in the room. Overrides are recorded in
the export.

---

## 5. Accessibility — target WCAG 2.2 AA

The map is a WebGL canvas. To assistive technology it is one opaque image: no keyboard focus,
no per-bin semantics, no tooltips. Visible focus styling does not help when nothing is
focusable.

**The Featured corridors dropdown is the designated keyboard and screen-reader equivalent of
the map**, not a demo convenience. Everything the map can do must be reachable through it.

- A **ranked corridor table** carries the same figures as the map in text form. It is the
  text alternative and must stay in sync with the map and drawer.
- Touch targets ≥44px.
- Every control reachable and operable by keyboard, in a sensible tab order.
- `prefers-reduced-motion: reduce` disables the drawer transition and any scroll behaviour.
- Contrast per §1.

---

## 6. Motion budget

Drawer transition, and `:hover` / `:focus-visible` transitions. That is all. Streamlit's rerun
model fights anything more ambitious, and injected CSS is re-applied with a delay. Do not
reach for scroll-linked animation, Plotly transitions, or scrollspy.

---

## 7. Copy

Sentence case, active voice, utility register — orientation, status, action. Not mood or
brand. Errors state what happened and what to do next. Empty states propose an action.

Banned per §0.1: "real-time", "live crash data", "current", "today's crashes", "up to the
minute".

Named empty and edge states:

| State | Copy |
|---|---|
| Corridor, 0 casualties in range | "No casualty crashes on {corridor} between {from} and {to}. Widen the date range." |
| CMF at 1.0 | "No expected effect at CMF 1.00. Move the slider to estimate a reduction." |
| Unit cost 0 | "Enter a unit cost to see cost per crash avoided." |
| EB unmatched | "Observed only — no Empirical Bayes match for this corridor." |
| Export blocked | "Fix the section showing an error before exporting. An export without every figure is a liability." |

---

## 8. Inherited constraints that still bind

From the dashboard repo's approved design docs:

- **No `pydeck HexagonLayer`.** It is on the tutorial-fingerprint avoid-list. The eng review
  independently landed on `ColumnLayer`, so this is already satisfied — keep it deliberate.
- No "Show raw data" checkbox, no "Hour to look at" slider, no "Breakdown by minute" chart.
- The freshness line is static in the sense that it never counts up. Coverage is derived from
  the data; the feed date is a fixed historical fact.
