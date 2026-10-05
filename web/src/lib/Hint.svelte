<script lang="ts">
  // Hover or focus to show a short description under the label.
  import type { Snippet } from "svelte";

  let { text, children }: { text: string; children: Snippet } = $props();
  const id = $props.id();
  let tip = $state<HTMLElement>();
  let shift = $state(0);

  // Keep the box inside the viewport.
  function show() {
    shift = 0;
    requestAnimationFrame(() => {
      if (!tip) return;
      const r = tip.getBoundingClientRect();
      shift = Math.min(0, window.innerWidth - 8 - r.right);
    });
  }
</script>

<span class="hint" tabindex="0" role="button" aria-describedby={id} onpointerenter={show} onfocus={show}
  >{@render children()}<span class="tip" role="tooltip" {id} bind:this={tip} style:translate="{shift}px 0"
    >{text}</span
  ></span
>

<style>
  .hint {
    position: relative;
    cursor: help;
    text-decoration: underline dotted var(--ink-3);
    text-underline-offset: 3px;
    outline: none;
  }
  .hint:focus-visible {
    border-radius: 2px;
    box-shadow: 0 0 0 2px var(--grid-fill);
  }
  .tip {
    display: none;
    position: absolute;
    top: calc(100% + 6px);
    left: 0;
    z-index: 3;
    width: max-content;
    max-width: min(260px, calc(100vw - 16px));
    padding: 6px 10px;
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 6px;
    box-shadow: 0 2px 8px rgb(0 0 0 / 0.08);
    font: 400 12px / 1.5 var(--f-sans);
    color: var(--ink-2);
    white-space: normal;
    text-align: left;
    cursor: auto;
  }
  .hint:hover .tip,
  .hint:focus .tip {
    display: block;
  }
</style>
