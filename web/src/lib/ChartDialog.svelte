<script lang="ts">
  // One chart full screen. Dragging across it with a mouse zooms in; the
  // overview under it shows the whole range with the visible span framed,
  // and the frame can be drawn, moved or resized by mouse, touch or keys.
  // Double click or Reset zoom goes back to the whole range.

  import type { ComponentProps } from "svelte";
  import { onMount } from "svelte";
  import { AXIS_W, MIN_SPAN, PAD_R } from "./layout";
  import TimeChart from "./TimeChart.svelte";
  import { fmtDayClock } from "./time";

  type Chart = Omit<ComponentProps<typeof TimeChart>, "title" | "mode" | "view" | "onview">;

  let { title, chart, onclose }: { title: string; chart: Chart; onclose: () => void } = $props();

  let dialog: HTMLDialogElement;
  let brush: HTMLDivElement;
  let zoom = $state<[number, number] | null>(null);

  const from = $derived(chart.from);
  const to = $derived(chart.to);
  // A zoom stays on the same clock times while the axis moves on, kept inside it.
  const lo = $derived(zoom ? Math.max(from, Math.min(zoom[0], to - MIN_SPAN)) : from);
  const hi = $derived(zoom ? Math.min(to, Math.max(zoom[1], lo + MIN_SPAN)) : to);
  const zoomed = $derived(zoom != null);

  function setView([a, b]: [number, number]) {
    a = Math.max(from, a);
    b = Math.min(to, b);
    if (b - a < MIN_SPAN) {
      const c = Math.min(Math.max((a + b) / 2, from + MIN_SPAN / 2), to - MIN_SPAN / 2);
      [a, b] = [c - MIN_SPAN / 2, c + MIN_SPAN / 2];
    }
    zoom = b - a >= to - from - 60 ? null : [a, b];
  }

  onMount(() => {
    dialog.showModal();
    const root = document.documentElement;
    const overflow = root.style.overflow;
    root.style.overflow = "hidden";
    return () => {
      root.style.overflow = overflow;
    };
  });

  // The overview frame, in px across the brush.
  let bw = $state(0);
  const px = (t: number) => ((t - from) / (to - from)) * bw;
  const at = (x: number) => from + (x / Math.max(1, bw)) * (to - from);

  type Drag =
    | { kind: "new"; x0: number; moved: boolean }
    | { kind: "left" }
    | { kind: "right" }
    | { kind: "pan"; t0: number; span: [number, number] };
  let drag: Drag | null = null;
  let cursor = $state("crosshair");

  function hit(x: number, touch: boolean): Drag["kind"] {
    const tol = touch ? 16 : 7;
    const [x0, x1] = [px(lo), px(hi)];
    if (Math.abs(x - x0) <= tol && zoomed) return "left";
    if (Math.abs(x - x1) <= tol && zoomed) return "right";
    if (zoomed && x > x0 && x < x1) return "pan";
    return "new";
  }

  const localX = (e: PointerEvent) => e.clientX - brush.getBoundingClientRect().left;

  function down(e: PointerEvent) {
    if (e.button !== 0) return;
    const x = localX(e);
    const kind = hit(x, e.pointerType !== "mouse");
    brush.setPointerCapture(e.pointerId);
    drag =
      kind === "new"
        ? { kind, x0: x, moved: false }
        : kind === "pan"
          ? { kind, t0: at(x), span: [lo, hi] }
          : ({ kind } as Drag);
    e.preventDefault();
  }

  function move(e: PointerEvent) {
    const x = localX(e);
    if (!drag) {
      const k = hit(x, false);
      cursor = k === "pan" ? "grab" : k === "new" ? "crosshair" : "ew-resize";
      return;
    }
    const t = at(Math.max(0, Math.min(bw, x)));
    if (drag.kind === "new") {
      if (!drag.moved && Math.abs(x - drag.x0) < 4) return;
      drag.moved = true;
      const t0 = at(drag.x0);
      setView([Math.min(t0, t), Math.max(t0, t)]);
    } else if (drag.kind === "left") {
      setView([Math.min(t, hi - MIN_SPAN), hi]);
    } else if (drag.kind === "right") {
      setView([lo, Math.max(t, lo + MIN_SPAN)]);
    } else {
      const [a, b] = drag.span;
      const d = Math.max(from - a, Math.min(to - b, t - drag.t0));
      setView([a + d, b + d]);
    }
  }

  function up(e: PointerEvent) {
    // A tap outside the frame centers the frame there.
    if (drag?.kind === "new" && !drag.moved && zoomed) {
      const t = at(localX(e));
      const half = (hi - lo) / 2;
      const c = Math.max(from + half, Math.min(to - half, t));
      setView([c - half, c + half]);
    }
    drag = null;
  }

  function key(e: KeyboardEvent) {
    const span = hi - lo;
    const step = span * (e.shiftKey ? 0.5 : 0.1);
    const c = (lo + hi) / 2;
    const pan = (d: number) => {
      d = Math.max(from - lo, Math.min(to - hi, d));
      setView([lo + d, hi + d]);
    };
    const scale = (f: number) => setView([c - (span * f) / 2, c + (span * f) / 2]);
    const keys: Record<string, () => void> = {
      ArrowLeft: () => pan(-step),
      ArrowRight: () => pan(step),
      Home: () => pan(from - lo),
      End: () => pan(to - hi),
      "+": () => scale(0.5),
      "=": () => scale(0.5),
      "-": () => scale(2),
    };
    const k = keys[e.key];
    if (k) {
      k();
      e.preventDefault();
    }
  }

  const rangeText = $derived(`${fmtDayClock(lo)} – ${fmtDayClock(hi)}`);
</script>

<dialog bind:this={dialog} aria-label={title} {onclose}>
  <header>
    <div class="title">
      <h2>{title}</h2>
      <span class="range">{rangeText}</span>
    </div>
    <button type="button" class="text" disabled={!zoomed} onclick={() => (zoom = null)}>
      Reset zoom
    </button>
    <button type="button" class="icon" aria-label="Close" onclick={() => dialog.close()}>
      <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"
        ><path d="M2.5 2.5l9 9M11.5 2.5l-9 9" /></svg
      >
    </button>
  </header>
  <div class="main">
    <TimeChart {...chart} mode="expanded" view={[lo, hi]} onview={setView} />
  </div>
  <div class="overview">
    <TimeChart {...chart} mode="overview" height={80} />
    <div
      class="brush"
      bind:this={brush}
      bind:clientWidth={bw}
      style:left="{AXIS_W}px"
      style:right="{PAD_R}px"
      style:cursor
      role="slider"
      tabindex="0"
      aria-label="Visible range"
      aria-valuemin={from}
      aria-valuemax={to}
      aria-valuenow={Math.round((lo + hi) / 2)}
      aria-valuetext={rangeText}
      onpointerdown={down}
      onpointermove={move}
      onpointerup={up}
      onpointercancel={() => (drag = null)}
      onkeydown={key}
    >
      <i class="shade" style:left="0" style:width="{px(lo)}px"></i>
      <i class="shade" style:left="{px(hi)}px" style:right="0"></i>
      <i class="frame" class:zoomed style:left="{px(lo)}px" style:width="{px(hi) - px(lo)}px"
        ><b></b><b></b></i
      >
    </div>
  </div>
</dialog>

<style>
  dialog {
    position: fixed;
    inset: 0;
    width: 100%;
    height: 100%;
    max-width: none;
    max-height: none;
    margin: 0;
    border: 0;
    box-sizing: border-box;
    padding: max(16px, env(safe-area-inset-top)) max(20px, env(safe-area-inset-right))
      max(16px, env(safe-area-inset-bottom)) max(20px, env(safe-area-inset-left));
    background: var(--bg);
    color: var(--ink);
    flex-direction: column;
    gap: 16px;
  }
  dialog[open] {
    display: flex;
  }
  dialog::backdrop {
    background: var(--bg);
  }
  header {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .title {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 2px 16px;
  }
  h2 {
    font: 600 15px var(--f-sans);
    letter-spacing: -0.005em;
    margin: 0;
  }
  .range {
    font-size: 13px;
    color: var(--ink-2);
  }
  button {
    font: inherit;
    color: var(--ink-2);
    background: transparent;
    border: 0;
    cursor: pointer;
  }
  button:hover:not(:disabled) {
    color: var(--ink);
    background: var(--panel-2);
  }
  button:focus-visible,
  .brush:focus-visible {
    outline: 2px solid var(--grid);
    outline-offset: 1px;
  }
  .text {
    font-size: 13px;
    font-weight: 500;
    padding: 4px 10px;
    border-radius: 6px;
    box-shadow: inset 0 0 0 1px var(--line);
  }
  .text:disabled {
    color: var(--ink-3);
    opacity: 0.6;
    cursor: default;
  }
  .icon {
    display: grid;
    place-items: center;
    width: 32px;
    height: 32px;
    padding: 0;
    border-radius: 6px;
  }
  .icon path {
    fill: none;
    stroke: currentColor;
    stroke-width: 1.5;
    stroke-linecap: round;
  }
  .main {
    flex: 1;
    min-height: 0;
  }
  .overview {
    position: relative;
    flex: none;
    border-top: 1px solid var(--line);
    padding-top: 10px;
  }
  .brush {
    position: absolute;
    /* Over the plot, not the time axis under it. */
    top: 16px;
    height: 46px;
    touch-action: none;
    user-select: none;
    border-radius: 3px;
  }
  .shade {
    position: absolute;
    top: 0;
    bottom: 0;
    background: color-mix(in srgb, var(--bg) 70%, transparent);
  }
  .frame {
    position: absolute;
    top: 0;
    bottom: 0;
    box-sizing: border-box;
    border: 1px solid var(--ink-3);
    border-radius: 3px;
  }
  .frame:not(.zoomed) {
    border-color: var(--line);
  }
  .frame b {
    position: absolute;
    top: 50%;
    width: 6px;
    height: 18px;
    margin: -9px 0 0 -4px;
    border-radius: 2px;
    background: var(--panel);
    box-shadow: inset 0 0 0 1px var(--ink-3);
  }
  .frame:not(.zoomed) b {
    display: none;
  }
  .frame b:last-child {
    left: 100%;
    margin-left: -3px;
  }
</style>
