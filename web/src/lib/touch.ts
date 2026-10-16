// Keep a touch readout after the finger lifts, as iPhone charts do, until the
// next touch lands outside the element.
const held = new Map<Element, (e: PointerEvent) => void>();

export function holdTouch(el: Element, clear: () => void) {
  if (held.has(el)) return;
  const off = (e: PointerEvent) => {
    if (el.contains(e.target as Node)) return;
    document.removeEventListener("pointerdown", off, true);
    held.delete(el);
    clear();
  };
  held.set(el, off);
  document.addEventListener("pointerdown", off, true);
}
