"use client";

/**
 * Draws a hand-drawn-looking red underline beneath a bbox, plus a red X
 * mark just past its right edge — the "teacher marking wrong work with a
 * red pen" look (underline the wrong phrase, X the line), as an alternative
 * to HandDrawnCircle's circling style. Same bbox contract as HandDrawnCircle:
 * [x1,y1,x2,y2] in the normalized 0-1000 space RecognizedStep.bbox already
 * uses — an absolutely-positioned SVG over the image at its natural size,
 * no pixel math against the rendered size.
 *
 * Seeded the same way as HandDrawnCircle (deterministic per caller-supplied
 * key) so a given attempt/step draws the same wobble on every re-render.
 */
import { useEffect, useRef } from "react";

const DRAW_MS = 500;

export function RedPenMark({ bbox, seed }: { bbox: number[] | null | undefined; seed: string }) {
  const underlineRef = useRef<SVGPathElement>(null);
  const xStroke1Ref = useRef<SVGPathElement>(null);
  const xStroke2Ref = useRef<SVGPathElement>(null);
  const valid = !!bbox && bbox.length === 4;

  const [x1, y1, x2, y2] = valid ? bbox! : [0, 0, 0, 0];
  const underlineY = y2 + 8;
  const underlineD = valid ? roughLinePath(x1 - 4, underlineY, x2 + 4, underlineY, seed) : "";

  // X mark sits just past the underlined text, vertically centered on it —
  // matches a teacher marking the END of a wrong line, not the middle.
  const xSize = Math.max(18, Math.min(34, (y2 - y1) * 0.55));
  const xCx = x2 + 18 + xSize / 2;
  const xCy = (y1 + y2) / 2;
  const xStroke1D = valid ? roughLinePath(xCx - xSize / 2, xCy - xSize / 2, xCx + xSize / 2, xCy + xSize / 2, seed + "-x1") : "";
  const xStroke2D = valid ? roughLinePath(xCx + xSize / 2, xCy - xSize / 2, xCx - xSize / 2, xCy + xSize / 2, seed + "-x2") : "";

  useEffect(() => {
    if (!valid) return;
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    // Underline draws first, then the X strikes over it a beat later — the
    // same "this is a moment, not a decal" reasoning as HandDrawnCircle.
    const els: [SVGPathElement | null, number][] = [
      [underlineRef.current, 0],
      [xStroke1Ref.current, DRAW_MS + 60],
      [xStroke2Ref.current, DRAW_MS + 180],
    ];
    const timeouts: ReturnType<typeof setTimeout>[] = [];
    for (const [el, delay] of els) {
      if (!el) continue;
      if (reduceMotion) { el.style.strokeDashoffset = "0"; continue; }
      const len = el.getTotalLength();
      el.style.transition = "none";
      el.style.strokeDasharray = `${len}`;
      el.style.strokeDashoffset = `${len}`;
      timeouts.push(setTimeout(() => {
        el.style.transition = `stroke-dashoffset ${DRAW_MS * 0.55}ms cubic-bezier(0.65,0,0.35,1)`;
        el.style.strokeDashoffset = "0";
      }, delay));
    }
    return () => timeouts.forEach(clearTimeout);
  }, [valid, underlineD, xStroke1D, xStroke2D]);

  if (!valid) return null;

  return (
    <svg
      viewBox="0 0 1000 1000"
      preserveAspectRatio="none"
      className="pointer-events-none absolute inset-0 h-full w-full"
      aria-hidden="true"
    >
      <path ref={underlineRef} d={underlineD} fill="none" stroke="#ef4444" strokeWidth={7} strokeLinecap="round" opacity={0.8} />
      <path ref={xStroke1Ref} d={xStroke1D} fill="none" stroke="#ef4444" strokeWidth={8} strokeLinecap="round" opacity={0.85} />
      <path ref={xStroke2Ref} d={xStroke2D} fill="none" stroke="#ef4444" strokeWidth={8} strokeLinecap="round" opacity={0.85} />
    </svg>
  );
}

// Tiny seeded PRNG (mulberry32) — same as HandDrawnCircle's, duplicated
// rather than shared per this codebase's existing small-helper convention.
function seededRandom(seedStr: string): () => number {
  let h = 1779033703 ^ seedStr.length;
  for (let i = 0; i < seedStr.length; i++) {
    h = Math.imul(h ^ seedStr.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  let a = h >>> 0;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// A slightly wobbly straight line between two points — not a perfectly
// straight SVG line, which would read as computer-drawn rather than a
// quick red-pen stroke.
function roughLinePath(x1: number, y1: number, x2: number, y2: number, seed: string): string {
  const rand = seededRandom(seed);
  const midX = (x1 + x2) / 2 + (rand() - 0.5) * 14;
  const midY = (y1 + y2) / 2 + (rand() - 0.5) * 10;
  return `M ${x1.toFixed(1)} ${y1.toFixed(1)} Q ${midX.toFixed(1)} ${midY.toFixed(1)}, ${x2.toFixed(1)} ${y2.toFixed(1)}`;
}
