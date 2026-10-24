<script lang="ts" generics="T extends string | number">
  let {
    options,
    value,
    label,
    onpick,
  }: {
    options: { value: T; label: string }[];
    value: T;
    /** Label the choice for screen readers. */
    label: string;
    onpick: (v: T) => void;
  } = $props();
</script>

<div class="seg" role="group" aria-label={label}>
  {#each options as o (o.value)}
    <button type="button" aria-pressed={value === o.value} onclick={() => onpick(o.value)}
      >{o.label}</button
    >
  {/each}
</div>

<style>
  .seg {
    display: inline-flex;
    padding: 2px;
    gap: 2px;
    border-radius: var(--radius-control);
    background: var(--panel-2);
  }
  button {
    font: inherit;
    font-size: var(--text-control);
    font-weight: 500;
    min-height: var(--control-height);
    padding: var(--space-1) 10px;
    border: 0;
    border-radius: var(--radius-control);
    background: transparent;
    color: var(--ink-2);
    cursor: pointer;
  }
  @media (hover: hover) {
    button:hover {
      color: var(--ink);
    }
  }
  button:focus-visible { outline: var(--focus-width) solid var(--grid); outline-offset: -2px; }
  /* Larger targets on touch screens. */
  @media (pointer: coarse) {
    button {
      min-height: var(--touch-target);
      padding: 4px 12px;
    }
  }
  button[aria-pressed="true"] {
    background: var(--panel);
    color: var(--ink);
    box-shadow: inset 0 -2px 0 var(--ink);
  }
</style>
