<script lang="ts">
  import type { Snippet } from "svelte";
  import type { HTMLButtonAttributes } from "svelte/elements";

  let {
    children,
    variant = "secondary",
    class: className = "",
    ...attributes
  }: HTMLButtonAttributes & { children: Snippet; variant?: "secondary" | "icon" } = $props();
</script>

<button {...attributes} type={attributes.type ?? "button"} class="control {variant} {className}">
  {@render children()}
</button>

<style>
  .control {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    min-height: var(--control-height);
    padding: var(--space-1) var(--space-3);
    border: var(--border-width) solid var(--line);
    border-radius: var(--radius-control);
    background: var(--panel);
    color: var(--ink-2);
    font: 500 var(--text-control) / 1.4 var(--f-sans);
    cursor: pointer;
  }
  .control:hover:not(:disabled) { background: var(--panel-2); color: var(--ink); }
  .control:focus-visible { outline: var(--focus-width) solid var(--grid); outline-offset: 2px; }
  .control:disabled { opacity: 0.55; cursor: default; }
  .icon { width: var(--control-height); padding: 0; border-color: transparent; background: transparent; }
  @media (pointer: coarse) {
    .control { min-height: var(--touch-target); }
    .icon { width: var(--touch-target); }
  }
</style>
