<script lang="ts" module>
  export interface TipRow {
    value?: string;
    name?: string;
    color?: string;
    /** A square key for areas and bars, a short line for lines. */
    shape?: "square" | "line";
  }
</script>

<script lang="ts">
  // The hover box every chart shares: a heading and one row per value.
  // Placed at (x, y) inside a positioned parent, beside the pointer, or to
  // its left with `flip` when there's no room on the right.
  let {
    x,
    y,
    title,
    rows,
    flip = false,
    offset = 12,
    width = $bindable(0),
  }: {
    x: number;
    y: number;
    title: string;
    rows: TipRow[];
    flip?: boolean;
    offset?: number;
    width?: number;
  } = $props();
</script>

<div
  class="tip"
  bind:clientWidth={width}
  style:left="{x}px"
  style:top="{y}px"
  style:transform={flip ? `translate(calc(-100% - ${offset}px), 0)` : `translate(${offset}px, 0)`}
>
  <div class="when">{title}</div>
  {#each rows as r, i (i)}
    <div class="row">
      {#if r.color}<span class="key {r.shape ?? 'square'}" style:background="var({r.color})"></span>{/if}
      {#if r.value}<strong>{r.value}</strong>{/if}
      {#if r.name}<span class="name">{r.name}</span>{/if}
    </div>
  {/each}
</div>

<style>
  .tip {
    position: absolute;
    z-index: 2;
    pointer-events: none;
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 8px;
    box-shadow: 0 4px 16px rgb(0 0 0 / 0.15);
    padding: 8px 10px;
    font-size: 12px;
    white-space: nowrap;
  }
  .when {
    color: var(--ink-2);
    margin-bottom: 4px;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 6px;
    line-height: 1.6;
  }
  .row strong {
    color: var(--ink);
    font-variant-numeric: tabular-nums;
  }
  .name {
    color: var(--ink-3);
  }
  .key {
    width: 10px;
    height: 10px;
    border-radius: 2px;
  }
  .key.line {
    height: 2px;
    border-radius: 1px;
  }
</style>
