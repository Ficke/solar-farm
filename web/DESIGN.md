# Solar Farm design system

Reviewed 2026-10-24. A precise energy instrument panel: clear comparisons,
stable meanings and a compact live view. The primary task is understanding
energy use and carbon savings; live operation is a peer view.

## Foundation

Use IBM Carbon's grid, typography and data-interface principles as the
foundation. This is a local adaptation, implemented in Svelte and uPlot.
It does not install Carbon React or reproduce every Carbon component.

Flat controls are a project decision. Current systems differ on shape;
rounding alone does not determine whether an interface is modern.

## Information architecture

| Area | Order and scope |
| --- | --- |
| Shared shell | Identity, two peer tabs, refresh failures and data warnings. |
| Energy & carbon | Period selection; estimated carbon impact and its sources; supply and consumption totals and breakdowns; exact period values. |
| Live system | Latest state and next transition; battery and power readings; recent supply and consumption; charging plan; optional forecast and grid details. |

- Open Energy & carbon by default. Keep its period selection when changing tabs.
- Use underlined tabs for the two tasks and segmented controls for local filters.
- Keep comparable values together: solar and grid; connected load and overhead;
  grid and stored-charge carbon intensity.
- Keep forecast accuracy, generation mix and wholesale prices in disclosures.
- Keep important warnings outside inactive tabs. Label stale readings as delayed.
- Use W for current power, Wh/kWh for energy, kg for carbon impact and g/kWh
  for carbon intensity. Label time ranges and the incomplete current period.

## Tokens and components

[`src/tokens.css`](src/tokens.css) is the source of shared visual values.
Use semantic tokens in both themes. Add or change a token there before
introducing another shared color, type role or control size.

| Role | Rule |
| --- | --- |
| Typeface | IBM Plex Sans; tabular numerals. |
| Type | 12 px metadata; 14 px controls; 16 px body role; 20 px section headings; 28 px status; 40 px report metrics, 32 px on phones. |
| Spacing | 4, 8, 12, 16, 24, 32, 48 and 64 px. Align section headings, figures and table edges. |
| Structure | Neutral surfaces, whitespace and 1 px rules. Avoid enclosing every metric in a card. |
| Shape | 0 px controls and structural surfaces; 2 px floating tooltips; 1 px legend keys. Circles identify state dots. |
| Elevation | No decorative card or button shadows. Only floating explanations use the shared shadow. |
| Controls | At least 32 px high; 44 px on coarse pointers. Selected and focused states are distinct. |

- Use [`Button.svelte`](src/lib/Button.svelte) for actions and icon buttons.
- Use [`Segmented.svelte`](src/lib/Segmented.svelte) for local choices.
- Use [`Hint.svelte`](src/lib/Hint.svelte) for optional definitions and
  [`Tooltip.svelte`](src/lib/Tooltip.svelte) for chart readings.
- Keep essential interpretation visible: units, baseline, signs, time range
  and data availability must not depend on hover.
- Use [`TimeChart.svelte`](src/lib/TimeChart.svelte) and
  [`ChartDialog.svelte`](src/lib/ChartDialog.svelte) for time-series interactions.

## Color and chart semantics

| Meaning | Token |
| --- | --- |
| Solar | `--solar` / `--solar-fill` |
| Grid supply | `--grid` / `--grid-fill` |
| Connected appliances | `--load` |
| Battery's own draw | `--overhead` |
| Carbon effect of load shifting | `--shift` |
| Favorable/adverse outcome | `--good-ink` / `--bad-ink` |

- Keep these meanings across cards, legends, tooltips and expanded views.
  Do not use grid blue to mean carbon saved by load shifting.
- Use neutral text for series labels. Color supports labels, not replaces them.
- Use paired positive stacks for period supply and consumption. Stored charge
  can make supply and consumption differ; neither is a calculated net balance.
- Separate live supply and consumption into aligned panels with the same time
  and watt scales, a linked cursor and shared expanded-view zoom.
- Keep zero on bar and filled-area axes. Use square bar ends and restrained grids.
- Use solid actuals and dashed forecasts. Reserve negative carbon values for
  added emissions; label the direct-grid baseline and that savings are estimated.
- Show missing readings separately from zero. Never invent savings percentages,
  confidence intervals, household totals or cost savings from unavailable data.

## Interaction and verification

- Follow the WAI-ARIA tabs pattern: selected state, associated panels, one tab
  stop in the tab row, Left/Right, Home/End, and visible focus. Do not capture
  Up/Down in a horizontal tab row.
- Make the active panel keyboard reachable. Use automatic tab activation only
  when switching can display content without waiting for a network request.
- Preserve native vertical touch scrolling and keyboard access to chart values.
- Check both views at 320 px and desktop widths, both themes, negative impact,
  missing readings, loading/failure states, tabs and expanded-chart zoom.
- Target WCAG 2.2 AA. This document is not a claim of a completed conformance audit.

## Research basis

The following sources inform the decisions above. Exact sizes and local
semantic colors are Solar Farm choices, not requirements copied from a system.

| Source | Verified status or relevance |
| --- | --- |
| [Carbon tabs](https://www.carbondesignsystem.com/building-blocks/core/components/tabs/guidelines) | Updated September 30, 2026. Separate related tasks; keep comparisons in the same view; use local switches for filters. |
| [Carbon 2x Grid](https://www.carbondesignsystem.com/building-blocks/foundations/2x-grid/overview) | Updated September 25, 2026. Foundation for aligned edges and spacing. |
| [Singapore Government tabs](https://v3.designsystem.tech.gov.sg/components/tab) | Updates June 8 and August 5, 2026. Parallel views, visible labels, underlined active state and accessibility. |
| [ONS dashboards](https://service-manual.ons.gov.uk/data-visualisation/guidance/dashboards) | Lead with important insights; do not force every measure onto one screen. |
| [ONS small multiples](https://service-manual.ons.gov.uk/data-visualisation/chart-types/small-multiple-charts) | Reduce overlapping series; preserve matching horizontal and vertical scales. |
| [WAI-ARIA tabs](https://www.w3.org/WAI/ARIA/apg/patterns/tabs/) | Keyboard behavior, focus and panel relationships. |
| [WCAG 2.2](https://www.w3.org/TR/WCAG22/) and [WCAG 3 status](https://www.w3.org/WAI/standards-guidelines/wcag/wcag3-intro/) | WCAG 2.2 is the implementation target. WCAG 3's September 2026 updates are still draft work. |

Alternatives reviewed: [USWDS](https://designsystem.digital.gov/documentation/settings/)
for token configuration; [GOV.UK](https://design-system.service.gov.uk/styles/layout/)
for hierarchy and content clarity; [Equinor EDS](https://eds.equinor.com/docs/about/about_eds/)
for energy-domain interfaces. Carbon best matches the existing typography and
data-heavy context without requiring a framework migration.
