<script lang="ts" generics="T extends string | number">
  // A row of toggle buttons where exactly one is pressed.
  let {
    options,
    value,
    label,
    onpick,
  }: {
    options: { value: T; label: string }[];
    value: T;
    /** What the group chooses, for screen readers. */
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
    border: 1px solid var(--line);
    border-radius: 8px;
    overflow: hidden;
  }
  button {
    font: inherit;
    font-size: 12px;
    padding: 4px 10px;
    border: 0;
    background: transparent;
    color: var(--ink-2);
    cursor: pointer;
  }
  button + button {
    border-left: 1px solid var(--line);
  }
  button[aria-pressed="true"] {
    background: var(--panel-2);
    color: var(--ink);
    font-weight: 600;
  }
</style>
