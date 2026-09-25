"use client";

import { useEffect } from "react";
import { useEdgeAutoScrollEnabled } from "@/hooks/useEdgeAutoScrollEnabled";

// Classroom kiosk machines are driven by an air mouse — a handheld pointer
// with none of a laptop trackpad's precision, and no scroll wheel at all.
// Reaching the edge of the screen is the one gesture it CAN reliably
// perform, so this hook turns that into page scrolling, the same way
// drag-to-edge works in slide/doc editors.

// How close to the viewport's top/bottom edge (px) the cursor must get
// before auto-scroll engages. Small enough not to fire while clicking
// ordinary content, big enough to forgive an air mouse's shakier aim.
const EDGE_ZONE_PX = 48;
// Scroll speed at the very edge of the zone; ramps down toward 0 at the
// zone's outer boundary instead of snapping straight to full speed.
const MAX_SCROLL_PX_PER_FRAME = 14;

const INTERACTIVE_SELECTOR =
  'button, a, input, textarea, select, [role="button"], [role="link"], [contenteditable="true"], [data-no-edge-scroll]';

function findScrollableAncestor(el: Element | null): HTMLElement | null {
  let node: Element | null = el;
  while (node && node !== document.body) {
    if (node instanceof HTMLElement) {
      const overflowY = getComputedStyle(node).overflowY;
      if ((overflowY === "auto" || overflowY === "scroll") && node.scrollHeight > node.clientHeight) {
        return node;
      }
    }
    node = node.parentElement;
  }
  return null;
}

/**
 * Mount once in a layout that has scrollable content. Skips engaging while
 * the cursor rests on a button/link/input so reaching a control pinned near
 * the screen edge (a sticky toolbar, a fullscreen stage's bottom bar) never
 * gets fought by the page scrolling out from under it.
 *
 * Can be turned off entirely (TopBar's "Edge scroll" toggle) — reported
 * 2026-09-22 that it can get in the way (hovering near the edge while doing
 * something else unintentionally scrolls the page), so it's an opt-out a
 * teacher can flip per-device, not something baked in unconditionally.
 */
export function useEdgeAutoScroll() {
  const enabled = useEdgeAutoScrollEnabled();

  useEffect(() => {
    // Toggled off (TopBar's "Edge scroll" button) — attach nothing at all
    // rather than attaching the listener and early-returning inside it, so
    // there's zero mousemove overhead while it's off, and no stale timer
    // can be left running from before the toggle flipped.
    if (!enabled) return;

    let rafId: number | null = null;
    let direction: 1 | -1 | 0 = 0;
    let speed = 0;
    let target: HTMLElement | null = null;

    function tick() {
      if (direction !== 0 && target) {
        target.scrollBy({ top: direction * speed, behavior: "auto" });
        rafId = requestAnimationFrame(tick);
      } else {
        rafId = null;
      }
    }

    function onMouseMove(e: MouseEvent) {
      const { clientX, clientY } = e;
      const viewportH = window.innerHeight;

      let dir: 1 | -1 | 0 = 0;
      let depth = 0; // how far past the edge threshold, 0..EDGE_ZONE_PX
      if (clientY < EDGE_ZONE_PX) { dir = -1; depth = EDGE_ZONE_PX - clientY; }
      else if (clientY > viewportH - EDGE_ZONE_PX) { dir = 1; depth = clientY - (viewportH - EDGE_ZONE_PX); }

      if (dir === 0) { direction = 0; target = null; return; }

      const hovered = document.elementFromPoint(clientX, clientY);
      if (hovered?.closest(INTERACTIVE_SELECTOR)) { direction = 0; target = null; return; }

      const scrollTarget =
        findScrollableAncestor(hovered) ??
        (document.querySelector("[data-edge-autoscroll-target]") as HTMLElement | null);
      if (!scrollTarget) { direction = 0; target = null; return; }

      direction = dir;
      speed = Math.max(2, Math.min(MAX_SCROLL_PX_PER_FRAME, (depth / EDGE_ZONE_PX) * MAX_SCROLL_PX_PER_FRAME));
      target = scrollTarget;

      if (rafId === null) rafId = requestAnimationFrame(tick);
    }

    function onMouseLeave() { direction = 0; target = null; }

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseleave", onMouseLeave);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseleave", onMouseLeave);
      if (rafId !== null) cancelAnimationFrame(rafId);
    };
  }, [enabled]);
}
