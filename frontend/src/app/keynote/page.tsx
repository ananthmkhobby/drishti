"use client";

/**
 * Keynote — a standalone, presenter-controlled reveal deck for unveiling
 * Drishti's new experience. Lives outside (dashboard) entirely (no sidebar/
 * topbar), touches no existing route, and reads no session data — it is
 * pure presentation, safe to open cold on stage with zero risk to the app
 * teachers actually use. Advance with a clicker (PageDown/Right/Space),
 * arrow keys, or by clicking/tapping the left/right half of the screen.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Book, Camera, FileText, HelpCircle, FlaskConical, BarChart3,
  ArrowRight, ChevronLeft, ChevronRight, Compass, Search, Eye, Sparkles,
  BookOpen, Cpu, X,
} from "lucide-react";

const SERIF = { fontFamily: "var(--font-fraunces), Georgia, serif" };

// Same dark "stage" palette as the Teaching fullscreen experience, so the
// keynote and the product it's unveiling feel like one continuous world.
const GOLD = "#D7A24E";
const GOLD_DEEP = "#B97F2C";
const INK = "#F5F1E7";
const INK_DIM = "#B9B4C4";

function StageBackdrop({ tint = GOLD }: { tint?: string }) {
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
      {/* Faint vignette so edge content never fights the projector's bezel */}
      <div className="absolute inset-0 shadow-[inset_0_0_180px_60px_rgba(0,0,0,0.55)]" />
    </div>
  );
}

function Kicker({ children, tint = GOLD }: { children: React.ReactNode; tint?: string }) {
  return (
    <div
      className="kn-rise mb-5 text-[0.75rem] sm:text-[0.8125rem] font-bold uppercase tracking-[0.25em]"
      style={{ color: tint, animationDelay: "40ms" }}
    >
      {children}
    </div>
  );
}

// ── Slide 1 — cold open ──────────────────────────────────────────────────

function SlideTitle() {
  return (
    <div className="flex flex-col items-center text-center px-6">
      <div className="kn-rise text-[0.6875rem] sm:text-xs font-bold uppercase tracking-[0.4em]" style={{ color: INK_DIM }}>
        Presenting
      </div>
      <h1
        className="kn-rise mt-6 font-semibold tracking-tight"
        style={{ ...SERIF, color: INK, fontSize: "clamp(56px, 11vw, 148px)", lineHeight: 0.98, animationDelay: "90ms" }}
      >
        Drishti
      </h1>
      <p
        className="kn-rise mt-7 max-w-xl text-base sm:text-xl"
        style={{ color: INK_DIM, animationDelay: "180ms" }}
      >
        Classroom intelligence, reimagined.
      </p>
    </div>
  );
}

// ── Slide 2 — the statement ──────────────────────────────────────────────

function SlideStatement() {
  return (
    <div className="flex flex-col items-center text-center px-6 gap-3">
      <p className="kn-rise text-xl sm:text-3xl" style={{ ...SERIF, color: INK_DIM, animationDelay: "40ms" }}>
        Five tools.
      </p>
      <p className="kn-rise text-xl sm:text-3xl" style={{ ...SERIF, color: INK_DIM, animationDelay: "160ms" }}>
        Forty clicks.
      </p>
      <p
        className="kn-rise mt-3 font-semibold"
        style={{ ...SERIF, color: GOLD, fontSize: "clamp(40px, 8vw, 96px)", lineHeight: 1.05, animationDelay: "320ms" }}
      >
        One classroom.
      </p>
    </div>
  );
}

// ── Slide 3 — Command Center ─────────────────────────────────────────────

const CENTER_TILES = [
  { icon: Book, bg: "#EDEAF9", fg: "#453B87" },
  { icon: Camera, bg: "#F6EAD3", fg: "#8A5D1E" },
  { icon: FileText, bg: "#EDEAF9", fg: "#453B87" },
  { icon: HelpCircle, bg: "#F6EAD3", fg: "#8A5D1E" },
  { icon: FlaskConical, bg: "#E7F1EA", fg: "#3E7A57" },
  { icon: BarChart3, bg: "#EDEAF9", fg: "#453B87" },
];

function SlideCommandCenter() {
  return (
    <div className="flex w-full max-w-4xl flex-col items-center px-6 text-center">
      <Kicker>Reach anything in one click</Kicker>
      <h2 className="kn-rise font-semibold" style={{ ...SERIF, color: INK, fontSize: "clamp(34px, 6vw, 68px)", animationDelay: "100ms" }}>
        Command Center.
      </h2>
      <p className="kn-rise mt-4 max-w-md text-sm sm:text-base" style={{ color: INK_DIM, animationDelay: "160ms" }}>
        Every session opens exactly where the teacher left off.
      </p>

      <div className="kn-rise mt-10 w-full max-w-lg rounded-3xl p-5 sm:p-6" style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.10)", animationDelay: "260ms" }}>
        <div className="flex flex-col sm:flex-row sm:items-center gap-4 rounded-2xl p-4" style={{ background: "rgba(255,255,255,0.04)" }}>
          <div className="flex items-center gap-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full" style={{ background: "radial-gradient(circle at 34% 30%, #F6EAD3, #EDEAF9 72%)" }}>
              <BookOpen className="h-5 w-5" style={{ color: "#453B87" }} />
            </div>
            <div className="min-w-0 flex-1 text-left">
              <div className="text-[0.6875rem] font-bold" style={{ color: GOLD }}>PICK UP WHERE YOU LEFT OFF</div>
              <div className="text-sm font-semibold break-words" style={{ ...SERIF, color: INK }}>Photosynthesis — Part 3</div>
            </div>
          </div>
          <div className="flex shrink-0 items-center justify-center gap-1.5 rounded-full px-3.5 py-2 text-xs font-bold sm:ml-auto" style={{ background: GOLD, color: "#1C1200" }}>
            Continue <ArrowRight className="h-3.5 w-3.5" />
          </div>
        </div>

        <div className="mt-4 grid grid-cols-3 sm:grid-cols-6 gap-2.5">
          {CENTER_TILES.map((t, i) => (
            <div key={i} className="flex h-11 items-center justify-center rounded-xl" style={{ background: t.bg }}>
              <t.icon className="h-4 w-4" style={{ color: t.fg }} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Slide 4 — Immersive Teaching ─────────────────────────────────────────

const QUEST_STEPS = [
  { label: "Guess", icon: Sparkles },
  { label: "Investigate", icon: Search },
  { label: "Observe", icon: Eye },
  { label: "Infer", icon: Compass },
];

function SlideTeaching() {
  return (
    <div className="flex w-full max-w-3xl flex-col items-center px-6 text-center">
      <Kicker>A stage, not a spreadsheet</Kicker>
      <h2 className="kn-rise font-semibold" style={{ ...SERIF, color: INK, fontSize: "clamp(34px, 6vw, 68px)", animationDelay: "100ms" }}>
        Immersive Teaching.
      </h2>
      <p className="kn-rise mt-4 max-w-md text-sm sm:text-base" style={{ color: INK_DIM, animationDelay: "160ms" }}>
        Board diagrams, guided questions, and a voice paced to the room.
      </p>

      <div className="kn-rise mt-10 flex items-center justify-center" style={{ animationDelay: "260ms" }}>
        {QUEST_STEPS.map((s, i) => {
          const active = i === 2;
          const done = i < 2;
          return (
            <div key={s.label} className="flex items-center">
              <div className="flex flex-col items-center gap-2">
                <div
                  className="flex h-9 w-9 items-center justify-center rounded-full"
                  style={
                    active
                      ? { background: GOLD, boxShadow: "0 0 0 6px rgba(215,162,78,0.20), 0 0 22px rgba(215,162,78,0.55)" }
                      : { background: done ? "rgba(215,162,78,0.22)" : "rgba(255,255,255,0.08)" }
                  }
                >
                  <s.icon className="h-4 w-4" style={{ color: active ? "#1C1200" : done ? GOLD : INK_DIM }} />
                </div>
                <span className="text-[0.6875rem] font-semibold" style={{ color: active ? GOLD : INK_DIM }}>{s.label}</span>
              </div>
              {i < QUEST_STEPS.length - 1 && <div className="mb-5 h-px w-10 sm:w-16" style={{ background: "rgba(255,255,255,0.14)" }} />}
            </div>
          );
        })}
      </div>

      <div className="kn-rise mt-8 flex items-center gap-2 rounded-full px-6 py-3.5" style={{ background: "rgba(255,255,255,0.07)", border: "1px solid rgba(255,255,255,0.18)", animationDelay: "340ms" }}>
        <span className="text-sm font-bold" style={{ color: GOLD }}>Continue</span>
        <span className="mx-1 h-4 w-px" style={{ background: "rgba(255,255,255,0.2)" }} />
        <span className="text-xs" style={{ color: INK_DIM }}>Say &ldquo;continue&rdquo;</span>
      </div>
    </div>
  );
}

// ── Slide 5 — Homepage ────────────────────────────────────────────────────

function MiniSessionRow({ title, subject, badge, badgeColor }: { title?: string; subject: string; badge: string; badgeColor: string }) {
  return (
    <div className="flex items-center gap-3 rounded-2xl p-3.5" style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)" }}>
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg" style={{ background: "rgba(215,162,78,0.16)" }}>
        <Cpu className="h-4 w-4" style={{ color: GOLD }} />
      </div>
      <div className="min-w-0 flex-1 text-left">
        {title && <div className="truncate text-xs font-semibold" style={{ color: INK }}>{title}</div>}
        <div className="truncate text-[0.6875rem]" style={{ color: INK_DIM }}>{subject}</div>
      </div>
      <span className="shrink-0 rounded-full px-2 py-0.5 text-[0.625rem] font-bold" style={{ background: badgeColor, color: "#1C1200" }}>{badge}</span>
    </div>
  );
}

function SlideHomepage() {
  return (
    <div className="flex w-full max-w-md flex-col items-center px-6 text-center">
      <Kicker>Every lesson, at a glance</Kicker>
      <h2 className="kn-rise font-semibold" style={{ ...SERIF, color: INK, fontSize: "clamp(34px, 6vw, 68px)", animationDelay: "100ms" }}>
        Your Classroom.
      </h2>
      <p className="kn-rise mt-4 max-w-sm text-sm sm:text-base" style={{ color: INK_DIM, animationDelay: "160ms" }}>
        Session history that finally looks like it belongs in this decade.
      </p>

      <div className="kn-rise mt-10 flex w-full flex-col gap-2.5" style={{ animationDelay: "260ms" }}>
        <MiniSessionRow title="Newton's Laws of Motion" subject="Physics · Grade 9" badge="AI Ready" badgeColor="rgba(69,59,135,0.9)" />
        <MiniSessionRow title="Photosynthesis" subject="Biology · Grade 8" badge="Active" badgeColor="rgba(62,122,87,0.9)" />
        <MiniSessionRow subject="Chemical Equilibrium · Grade 12" badge="Done" badgeColor={GOLD} />
      </div>
    </div>
  );
}

// ── Slide 6 — closing ─────────────────────────────────────────────────────

function SlideClosing() {
  return (
    <div className="flex flex-col items-center text-center px-6">
      <div className="kn-rise text-[0.6875rem] sm:text-xs font-bold uppercase tracking-[0.4em]" style={{ color: INK_DIM }}>
        Drishti
      </div>
      <h2
        className="kn-rise mt-6 font-semibold"
        style={{ ...SERIF, color: INK, fontSize: "clamp(40px, 8vw, 96px)", lineHeight: 1.05, animationDelay: "100ms" }}
      >
        Available today.
      </h2>
      <p className="kn-rise mt-7 text-base sm:text-xl" style={{ color: GOLD, animationDelay: "220ms", ...SERIF }}>
        Thank you.
      </p>
    </div>
  );
}

// ── Deck ──────────────────────────────────────────────────────────────────

const SLIDES: { render: () => React.ReactNode; tint: string }[] = [
  { render: () => <SlideTitle />, tint: GOLD },
  { render: () => <SlideStatement />, tint: GOLD_DEEP },
  { render: () => <SlideCommandCenter />, tint: "#453B87" },
  { render: () => <SlideTeaching />, tint: GOLD },
  { render: () => <SlideHomepage />, tint: "#3E7A57" },
  { render: () => <SlideClosing />, tint: GOLD },
];

export default function KeynotePage() {
  const [i, setI] = useState(0);
  const last = SLIDES.length - 1;

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

  const tint = useMemo(() => SLIDES[i].tint, [i]);

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

      {/* Exit — subtle, corner, never competes with the content */}
      <Link
        href="/sessions"
        aria-label="Exit keynote"
        className="fixed left-5 top-5 z-30 flex h-9 w-9 items-center justify-center rounded-full text-white/30 transition-colors hover:bg-white/10 hover:text-white/70"
      >
        <X className="h-4 w-4" />
      </Link>

      {/* Slide counter */}
      <div className="fixed right-6 top-6 z-30 text-[0.6875rem] font-medium tabular-nums" style={{ color: "rgba(255,255,255,0.28)" }}>
        {String(i + 1).padStart(2, "0")} / {String(SLIDES.length).padStart(2, "0")}
      </div>

      {/* Click zones — left half = back, right half = forward */}
      <button aria-label="Previous slide" onClick={() => go(-1)} className="fixed inset-y-0 left-0 z-10 w-1/2 cursor-w-resize" style={{ background: "transparent" }} />
      <button aria-label="Next slide" onClick={() => go(1)} className="fixed inset-y-0 right-0 z-10 w-1/2 cursor-e-resize" style={{ background: "transparent" }} />

      {/* Slide content */}
      <div className="relative z-20 flex h-full w-full items-center justify-center">
        <div key={i} className="flex w-full items-center justify-center">
          {SLIDES[i].render()}
        </div>
      </div>

      {/* Nav chevrons — desktop affordance, low-opacity until hover */}
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

      {/* Progress dots */}
      <div className="fixed inset-x-0 bottom-6 z-30 flex items-center justify-center gap-2">
        {SLIDES.map((_, idx) => (
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
