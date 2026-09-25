"use client";

/**
 * Shared "stage" shell for the teacher-flow keynote decks (/keynote2,
 * /keynote3, /keynote4). Same dark palette, type, and navigation as the
 * original /keynote unveiling deck (frontend/src/app/keynote/page.tsx) —
 * factored out here because three new decks now consume it verbatim.
 * /keynote itself is left untouched.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ChevronLeft, ChevronRight, Mic, X, type LucideIcon } from "lucide-react";

export const SERIF = { fontFamily: "var(--font-fraunces), Georgia, serif" };
export const GOLD = "#D7A24E";
export const GOLD_DEEP = "#B97F2C";
export const INK = "#F5F1E7";
export const INK_DIM = "#B9B4C4";
export const INDIGO = "#453B87";
export const GREEN = "#3E7A57";

export interface KeynoteSlide {
  render: () => React.ReactNode;
  tint: string;
}

export function StageBackdrop({ tint = GOLD }: { tint?: string }) {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      <div
        className="absolute inset-0"
        style={{ background: "radial-gradient(ellipse 1100px 700px at 50% 30%, #1C1833, #0F0C1D 70%)" }}
      />
      <div
        className="kn-drift absolute left-1/2 top-1/3 h-[35rem] w-[35rem] -translate-x-1/2 -translate-y-1/2 rounded-full opacity-[0.16] blur-[110px]"
        style={{ background: tint }}
      />
      <div
        className="kn-drift-slow absolute right-[8%] bottom-[10%] h-[23.75rem] w-[23.75rem] rounded-full opacity-[0.10] blur-[100px]"
        style={{ background: "#453B87" }}
      />
      <div className="absolute inset-0 shadow-[inset_0_0_180px_60px_rgba(0,0,0,0.55)]" />
    </div>
  );
}

export function Kicker({ children, tint = GOLD }: { children: React.ReactNode; tint?: string }) {
  return (
    <div
      className="kn-rise mb-5 text-[0.75rem] sm:text-[0.8125rem] font-bold uppercase tracking-[0.25em]"
      style={{ color: tint, animationDelay: "40ms" }}
    >
      {children}
    </div>
  );
}

// Big gold number that IS the point of a slide — every feature slide in
// these decks leads with "how many taps," so this is the most-reused primitive.
export function ClickCount({
  n, label = "tap", sublabel,
}: { n: number | string; label?: string; sublabel?: string }) {
  const plural = typeof n === "number" && n !== 1;
  return (
    <div className="kn-rise flex flex-col items-center" style={{ animationDelay: "220ms" }}>
      <div className="flex items-baseline gap-3">
        <span
          className="font-semibold"
          style={{ ...SERIF, color: GOLD, fontSize: "clamp(72px, 14vw, 160px)", lineHeight: 1 }}
        >
          {n}
        </span>
        <span className="text-sm sm:text-base font-bold uppercase tracking-[0.2em]" style={{ color: INK_DIM }}>
          {label}{plural ? "s" : ""}
        </span>
      </div>
      {sublabel && <span className="mt-3 max-w-xs text-center text-xs sm:text-sm" style={{ color: INK_DIM }}>{sublabel}</span>}
    </div>
  );
}

export function VoiceLine({ text, caption = "or just say it" }: { text: string; caption?: string }) {
  return (
    <div className="kn-rise flex flex-col items-center gap-2.5" style={{ animationDelay: "420ms" }}>
      <span className="text-[0.625rem] font-bold uppercase tracking-[0.25em]" style={{ color: GOLD }}>{caption}</span>
      <div className="flex max-w-sm items-center gap-2 rounded-full px-5 py-2.5" style={{ background: "rgba(255,255,255,0.07)", border: "1px solid rgba(255,255,255,0.18)" }}>
        <Mic className="h-3.5 w-3.5 shrink-0" style={{ color: GOLD }} />
        <span className="text-sm italic" style={{ color: INK }}>&ldquo;{text}&rdquo;</span>
      </div>
    </div>
  );
}

export function ButtonChip({
  children, tint = GOLD, icon: Icon,
}: { children: React.ReactNode; tint?: string; icon?: LucideIcon }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-5 py-2.5 text-sm font-bold" style={{ background: tint, color: "#1C1200" }}>
      {children}
      {Icon && <Icon className="h-3.5 w-3.5" />}
    </span>
  );
}

export function Panel({ children, className = "", delay = "260ms" }: { children: React.ReactNode; className?: string; delay?: string }) {
  return (
    <div
      className={`kn-rise w-full rounded-3xl p-5 sm:p-6 ${className}`}
      style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.10)", animationDelay: delay }}
    >
      {children}
    </div>
  );
}

// A horizontal "this button, then that button" tracker — the literal tap
// sequence a teacher's thumb follows, made visible.
export function StepFlow({ steps }: { steps: { label: string; icon: LucideIcon }[] }) {
  return (
    <div className="kn-rise flex flex-wrap items-start justify-center gap-y-5" style={{ animationDelay: "300ms" }}>
      {steps.map((s, i) => (
        <div key={s.label} className="flex items-center">
          <div className="flex flex-col items-center gap-2">
            <div className="flex h-11 w-11 items-center justify-center rounded-full" style={{ background: "rgba(215,162,78,0.16)", border: "1px solid rgba(215,162,78,0.38)" }}>
              <s.icon className="h-4.5 w-4.5" style={{ color: GOLD }} />
            </div>
            <span className="max-w-[5.75rem] text-center text-[0.6875rem] font-semibold leading-tight" style={{ color: INK_DIM }}>{s.label}</span>
          </div>
          {i < steps.length - 1 && (
            <div className="mb-6 flex w-8 sm:w-12 items-center justify-center" style={{ color: "rgba(255,255,255,0.22)" }}>
              <ChevronRight className="h-4 w-4" />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export function KeynoteDeck({ slides, exitHref = "/sessions" }: { slides: KeynoteSlide[]; exitHref?: string }) {
  const [i, setI] = useState(0);
  const last = slides.length - 1;

  const go = useCallback((delta: number) => {
    setI((cur) => Math.min(last, Math.max(0, cur + delta)));
  }, [last]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (["ArrowRight", "ArrowDown", " ", "PageDown"].includes(e.key)) { e.preventDefault(); go(1); }
      else if (["ArrowLeft", "ArrowUp", "PageUp"].includes(e.key)) { e.preventDefault(); go(-1); }
      else if (e.key === "Home") { e.preventDefault(); setI(0); }
      else if (e.key === "End") { e.preventDefault(); setI(last); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, last]);

  const tint = useMemo(() => slides[i].tint, [i, slides]);

  return (
    <div className="fixed inset-0 overflow-hidden select-none" style={{ background: "#0F0C1D" }}>
      <style>{`
        @keyframes kn-rise-kf { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes kn-drift-kf { 0%,100% { transform: translate(-50%,-50%) scale(1); } 50% { transform: translate(-46%,-54%) scale(1.08); } }
        @keyframes kn-drift-slow-kf { 0%,100% { transform: translate(0,0) scale(1); } 50% { transform: translate(-14px,10px) scale(1.05); } }
        .kn-rise { animation: kn-rise-kf 620ms cubic-bezier(0.16,1,0.3,1) both; }
        .kn-drift { animation: kn-drift-kf 14s ease-in-out infinite; }
        .kn-drift-slow { animation: kn-drift-slow-kf 18s ease-in-out infinite; }
        @media (prefers-reduced-motion: reduce) {
          .kn-rise, .kn-drift, .kn-drift-slow { animation: none !important; }
        }
      `}</style>

      <StageBackdrop tint={tint} />

      <Link
        href={exitHref}
        aria-label="Exit keynote"
        className="fixed left-5 top-5 z-30 flex h-9 w-9 items-center justify-center rounded-full text-white/30 transition-colors hover:bg-white/10 hover:text-white/70"
      >
        <X className="h-4 w-4" />
      </Link>

      <div className="fixed right-6 top-6 z-30 text-[0.6875rem] font-medium tabular-nums" style={{ color: "rgba(255,255,255,0.28)" }}>
        {String(i + 1).padStart(2, "0")} / {String(slides.length).padStart(2, "0")}
      </div>

      <button aria-label="Previous slide" onClick={() => go(-1)} className="fixed inset-y-0 left-0 z-10 w-1/2 cursor-w-resize" style={{ background: "transparent" }} />
      <button aria-label="Next slide" onClick={() => go(1)} className="fixed inset-y-0 right-0 z-10 w-1/2 cursor-e-resize" style={{ background: "transparent" }} />

      <div className="relative z-20 flex h-full w-full items-center justify-center">
        <div key={i} className="flex w-full items-center justify-center">
          {slides[i].render()}
        </div>
      </div>

      <button
        aria-label="Previous"
        onClick={() => go(-1)}
        disabled={i === 0}
        className="fixed left-4 top-1/2 z-30 hidden -translate-y-1/2 h-11 w-11 items-center justify-center rounded-full text-white/20 transition-colors hover:bg-white/10 hover:text-white/60 disabled:opacity-0 sm:flex"
      >
        <ChevronLeft className="h-5 w-5" />
      </button>
      <button
        aria-label="Next"
        onClick={() => go(1)}
        disabled={i === last}
        className="fixed right-4 top-1/2 z-30 hidden -translate-y-1/2 h-11 w-11 items-center justify-center rounded-full text-white/20 transition-colors hover:bg-white/10 hover:text-white/60 disabled:opacity-0 sm:flex"
      >
        <ChevronRight className="h-5 w-5" />
      </button>

      <div className="fixed inset-x-0 bottom-6 z-30 flex items-center justify-center gap-2">
        {slides.map((_, idx) => (
          <button
            key={idx}
            aria-label={`Go to slide ${idx + 1}`}
            onClick={() => setI(idx)}
            className="h-1.5 rounded-full transition-all"
            style={{
              width: idx === i ? 22 : 6,
              background: idx === i ? GOLD : "rgba(255,255,255,0.22)",
            }}
          />
        ))}
      </div>
    </div>
  );
}
