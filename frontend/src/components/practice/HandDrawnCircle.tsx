"use client";

/**
 * Draws a rough, hand-drawn-looking oval around a bbox — like a teacher
 * circling a mistake in red pen on a notebook page, not a crisp geometric
 * ellipse. bbox is [x1,y1,x2,y2] in the same normalized 0-1000 space
 * RecognizedStep.bbox already uses (see practice_engine.py's vision-step
 * extraction), so this only needs an absolutely-positioned SVG over the
 * image at its natural size — no pixel math against the rendered size.
 *
 * Deterministically "random" (seeded by a caller-supplied key, e.g.
 * `${attempt_id}-${stepIndex}`) so the same attempt/step draws the same
 * wobble on every re-render instead of re-randomizing and jittering
 * visually — but different attempts don't all look identically robotic.
 *
 * Animates in as a live "being drawn" stroke (2026-09-24) rather than
 * appearing instantly — a teacher's red-pen circle is a MOMENT, not a
 * static decal, and the previous static render read as flat/decorative
 * ("not intuitive... should be made better premium") rather than as an
 * actual correction happening in front of the student.
 */
import { useEffect, useRef } from "react";

const DRAW_MS = 620;

export function HandDrawnCircle({ bbox, seed }: { bbox: number[] | null | undefined; seed: string }) {
  const path1Ref = useRef<SVGPathElement>(null);
  const path2Ref = useRef<SVGPathElement>(null);
  const valid = !!bbox && bbox.length === 4;

  const [x1, y1, x2, y2] = valid ? bbox! : [0, 0, 0, 0];
  const cx = (x1 + x2) / 2;
  const cy = (y1 + y2) / 2;
  // Padded beyond the tight bbox — a real correction circles AROUND the
  // words with room to spare, it doesn't hug their exact edges.
  const rx = Math.max(35, (x2 - x1) / 2) * 1.35;
  const ry = Math.max(22, (y2 - y1) / 2) * 1.7;
  const d1 = valid ? roughOvalPath(cx, cy, rx, ry, seed) : "";
  const d2 = valid ? roughOvalPath(cx, cy, rx, ry, seed + "-2") : "";

  useEffect(() => {
    if (!valid) return;
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    // Second pass starts a beat after the first — a teacher's second,
    // reinforcing loop follows the first, it doesn't trace it in lockstep.
    const els: [SVGPathElement | null, number][] = [[path1Ref.current, 0], [path2Ref.current, 110]];
    const timeouts: ReturnType<typeof setTimeout>[] = [];
    for (const [el, delay] of els) {
      if (!el) continue;
      if (reduceMotion) { el.style.strokeDashoffset = "0"; continue; }
      const len = el.getTotalLength();
      el.style.transition = "none";
      el.style.strokeDasharray = `${len}`;
      el.style.strokeDashoffset = `${len}`;
      timeouts.push(setTimeout(() => {
        el.style.transition = `stroke-dashoffset ${DRAW_MS}ms cubic-bezier(0.65,0,0.35,1)`;
        el.style.strokeDashoffset = "0";
      }, delay));
    }
    return () => timeouts.forEach(clearTimeout);
    // Re-runs (and re-draws) whenever the shape itself changes — a
    // different seed/bbox is a genuinely different correction, not a
    // re-render of the same one.
  }, [valid, d1, d2]);

  if (!valid) return null;

  return (
    <svg
      viewBox="0 0 1000 1000"
      preserveAspectRatio="none"
      className="pointer-events-none absolute inset-0 h-full w-full"
      aria-hidden="true"
    >
      {/* Two overlapping passes, offset by different seeds — a real hand
          correcting something rarely circles it in one perfect pass; a
          second slightly-off loop is what actually reads as "hand-drawn"
          rather than "a wobbly single stroke." */}
      <path ref={path1Ref} d={d1} fill="none" stroke="#ef4444" strokeWidth={9} strokeLinecap="round" strokeLinejoin="round" opacity={0.55} />
      <path ref={path2Ref} d={d2} fill="none" stroke="#ef4444" strokeWidth={7} strokeLinecap="round" strokeLinejoin="round" opacity={0.75} />
    </svg>
  );
}

// Tiny seeded PRNG (mulberry32) — deterministic per seed string, no
// dependency needed for something this small.
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

function roughOvalPath(cx: number, cy: number, rx: number, ry: number, seed: string): string {
  const rand = seededRandom(seed);
  const POINT_COUNT = 11;
  // Slightly more than a full turn so the stroke overlaps its own start
  // instead of closing perfectly — the classic hand-drawn-circle "tail"
  // where a freehand loop never quite lines back up with itself.
  const TURNS = 1.12;
  const startAngle = rand() * Math.PI * 2;
  const pts: [number, number][] = [];
  for (let i = 0; i <= POINT_COUNT; i++) {
    const t = startAngle + (i / POINT_COUNT) * TURNS * Math.PI * 2;
    const jitter = 0.82 + rand() * 0.32; // ±~18% radius wobble per point
    pts.push([cx + Math.cos(t) * rx * jitter, cy + Math.sin(t) * ry * jitter]);
  }

  // Smooth through the points with quadratic beziers via midpoints — a
  // cheap way to get an organic curve without a full Catmull-Rom spline.
  let d = `M ${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const mx = (pts[i][0] + pts[i + 1][0]) / 2;
    const my = (pts[i][1] + pts[i + 1][1]) / 2;
    d += ` Q ${pts[i][0].toFixed(1)} ${pts[i][1].toFixed(1)}, ${mx.toFixed(1)} ${my.toFixed(1)}`;
  }
  const secondLast = pts[pts.length - 2];
  const last = pts[pts.length - 1];
  d += ` Q ${secondLast[0].toFixed(1)} ${secondLast[1].toFixed(1)}, ${last[0].toFixed(1)} ${last[1].toFixed(1)}`;
  return d;
}
