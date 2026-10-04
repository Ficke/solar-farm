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
    border-radius: 7px;
    background: var(--panel-2);
  }
  button {
    font: inherit;
    font-size: 13px;
    font-weight: 500;
    padding: 3px 10px;
    border: 0;
    border-radius: 5px;
    background: transparent;
    color: var(--ink-2);
    cursor: pointer;
  }
  button:hover {
    color: var(--ink);
  }
  button[aria-pressed="true"] {
    background: var(--panel);
    color: var(--ink);
    box-shadow:
      0 0 0 1px var(--line),
      0 1px 2px rgb(0 0 0 / 0.06);
  }
</style>
