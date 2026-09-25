"use client";

/**
 * Keynote 3 — Case 2: Guided Practice, headlined by the new batch-scan
 * feature (one wide photo → every student named, cropped, and graded).
 * Same shell as /keynote2 and /keynote4.
 */

import {
  Camera, CheckCircle2, FlaskConical, ListChecks, Sparkles, Users, XCircle,
} from "lucide-react";
import {
  KeynoteDeck, Kicker, ClickCount, ButtonChip, StepFlow, Panel,
  SERIF, GOLD, GOLD_DEEP, INDIGO, GREEN, INK, INK_DIM,
} from "@/components/keynote/KeynoteShell";

// ── Slide 1 — cold open ──────────────────────────────────────────────────

function SlideTitle() {
  return (
    <div className="flex flex-col items-center text-center px-6">
      <div className="kn-rise text-[0.6875rem] sm:text-xs font-bold uppercase tracking-[0.4em]" style={{ color: INK_DIM }}>
        Case two
      </div>
      <h1
        className="kn-rise mt-6 font-semibold tracking-tight"
        style={{ ...SERIF, color: INK, fontSize: "clamp(40px, 8vw, 96px)", lineHeight: 1.02, animationDelay: "90ms" }}
      >
        Guided Practice.
      </h1>
      <p className="kn-rise mt-7 max-w-lg text-base sm:text-xl" style={{ color: INK_DIM, animationDelay: "180ms" }}>
        Every student working. Every student watched.
      </p>
    </div>
  );
}

// ── Slide 2 — statement ──────────────────────────────────────────────────

function SlideStatement() {
  return (
    <div className="flex flex-col items-center text-center px-6 gap-3">
      <p className="kn-rise text-xl sm:text-3xl" style={{ ...SERIF, color: INK_DIM, animationDelay: "40ms" }}>Thirty notebooks.</p>
      <p className="kn-rise text-xl sm:text-3xl" style={{ ...SERIF, color: INK_DIM, animationDelay: "160ms" }}>One photo.</p>
      <p
        className="kn-rise mt-3 font-semibold"
        style={{ ...SERIF, color: GOLD, fontSize: "clamp(40px, 8vw, 88px)", lineHeight: 1.05, animationDelay: "320ms" }}
      >
        Every kid, graded.
      </p>
    </div>
  );
}

// ── Slide 3 — generate questions ─────────────────────────────────────────

function SlideGenerate() {
  return (
    <div className="flex w-full max-w-xl flex-col items-center px-6 text-center">
      <Kicker>Questions, ready before class</Kicker>
      <h2 className="kn-rise font-semibold" style={{ ...SERIF, color: INK, fontSize: "clamp(32px, 6vw, 60px)", animationDelay: "100ms" }}>
        Generate in one tap.
      </h2>

      <div className="mt-9"><ClickCount n={1} /></div>

      <Panel className="mt-9 max-w-md" delay="300ms">
        <div className="flex flex-col gap-2.5 text-left">
          <span className="text-[0.6875rem] font-bold uppercase tracking-[0.15em]" style={{ color: GOLD }}>From a topic — no board photo needed</span>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-xl px-3 py-2 text-xs" style={{ background: "rgba(255,255,255,0.06)", color: INK_DIM }}>Mathematics</span>
            <span className="rounded-xl px-3 py-2 text-xs" style={{ background: "rgba(255,255,255,0.06)", color: INK_DIM }}>Trigonometric identities</span>
            <ButtonChip icon={Sparkles}>Generate</ButtonChip>
          </div>
        </div>
      </Panel>

      <p className="kn-rise mt-6 max-w-sm text-xs sm:text-sm" style={{ color: INK_DIM, animationDelay: "460ms" }}>
        Or generate straight from a board photo already in this session — same one tap.
      </p>
    </div>
  );
}

// ── Slide 4 — approve ────────────────────────────────────────────────────

function SlideApprove() {
  return (
    <div className="flex w-full max-w-xl flex-col items-center px-6 text-center">
      <Kicker tint={GOLD_DEEP}>You stay in control</Kicker>
      <h2 className="kn-rise font-semibold" style={{ ...SERIF, color: INK, fontSize: "clamp(32px, 6vw, 60px)", animationDelay: "100ms" }}>
        Approve in one tap.
      </h2>

      <div className="mt-9"><ClickCount n={1} /></div>

      <Panel className="mt-9 max-w-md text-left" delay="300ms">
        <div className="flex gap-2">
          <span className="rounded-full px-2.5 py-0.5 text-[0.625rem] font-bold" style={{ background: "rgba(215,162,78,0.18)", color: GOLD }}>Algebraic</span>
          <span className="rounded-full px-2.5 py-0.5 text-[0.625rem] font-bold" style={{ background: "rgba(255,255,255,0.08)", color: INK_DIM }}>easy</span>
        </div>
        <p className="mt-3 text-sm" style={{ ...SERIF, color: INK }}>
          Differentiate the function f(x) = 2x&sup5; &minus; 4x&sup3; + x using the power rule.
        </p>
        <div className="mt-4 flex items-center gap-2">
          <ButtonChip icon={CheckCircle2}>Approve</ButtonChip>
          <ButtonChip tint="rgba(255,255,255,0.10)" icon={XCircle}>Reject</ButtonChip>
        </div>
      </Panel>
    </div>
  );
}

// ── Slide 5 — batch scan (the headline feature) ──────────────────────────

const SCAN_STEPS = [
  { label: "Pick question", icon: ListChecks },
  { label: "Take the photo", icon: Camera },
  { label: "Snap", icon: Camera },
  { label: "Use photo", icon: CheckCircle2 },
];

const DETECTED = [
  { name: "Priya Sharma", tint: GREEN },
  { name: "Rahul Verma", tint: GOLD },
  { name: "Ananya Iyer", tint: GREEN },
];

function SlideBatchScan() {
  return (
    <div className="flex w-full max-w-2xl flex-col items-center px-6 text-center">
      <Kicker tint={GREEN}>One photo. Every desk.</Kicker>
      <h2 className="kn-rise font-semibold" style={{ ...SERIF, color: INK, fontSize: "clamp(32px, 6vw, 60px)", animationDelay: "100ms" }}>
        Scan the whole room.
      </h2>
      <p className="kn-rise mt-4 max-w-md text-sm sm:text-base" style={{ color: INK_DIM, animationDelay: "160ms" }}>
        Walk the aisle, take one wide photo — Drishti finds every name, crops every notebook, and grades each one separately.
      </p>

      <div className="mt-8"><ClickCount n={3} /></div>

      <div className="mt-8"><StepFlow steps={SCAN_STEPS} /></div>

      <Panel className="mt-9 max-w-lg" delay="440ms">
        <div className="flex items-center gap-2 text-left">
          <Users className="h-4 w-4" style={{ color: GOLD }} />
          <span className="text-[0.6875rem] font-bold uppercase tracking-[0.15em]" style={{ color: GOLD }}>3 students detected</span>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {DETECTED.map((d) => (
            <span key={d.name} className="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium" style={{ background: "rgba(255,255,255,0.06)", color: INK }}>
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: d.tint }} />
              {d.name}
            </span>
          ))}
        </div>
      </Panel>
    </div>
  );
}

// ── Slide 6 — live triage ────────────────────────────────────────────────

const TRIAGE_ROWS = [
  { name: "Rahul Verma", state: "Needs you", tint: "#DC2626", bg: "rgba(220,38,38,0.12)" },
  { name: "Ananya Iyer", state: "Stuck", tint: GOLD, bg: "rgba(215,162,78,0.14)" },
  { name: "Priya Sharma", state: "Progressing", tint: GREEN, bg: "rgba(62,122,87,0.14)" },
];

function SlideTriage() {
  return (
    <div className="flex w-full max-w-xl flex-col items-center px-6 text-center">
      <Kicker tint={INDIGO}>Know who to visit first</Kicker>
      <h2 className="kn-rise font-semibold" style={{ ...SERIF, color: INK, fontSize: "clamp(32px, 6vw, 60px)", animationDelay: "100ms" }}>
        Who needs help — sorted.
      </h2>

      <div className="kn-rise mt-10 flex w-full max-w-sm flex-col gap-2.5" style={{ animationDelay: "260ms" }}>
        {TRIAGE_ROWS.map((r) => (
          <div key={r.name} className="flex items-center gap-3 rounded-2xl p-3.5 text-left" style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)" }}>
            <span className="flex-1 text-sm font-medium" style={{ color: INK }}>{r.name}</span>
            <span className="shrink-0 rounded-full px-2.5 py-1 text-[0.6875rem] font-bold" style={{ background: r.bg, color: r.tint }}>{r.state}</span>
          </div>
        ))}
      </div>

      <p className="kn-rise mt-7 max-w-sm text-xs sm:text-sm" style={{ color: INK_DIM, animationDelay: "440ms" }}>
        No stack of notebooks to page through after class — the list is already sorted by urgency, live.
      </p>
    </div>
  );
}

// ── Slide 7 — closing ─────────────────────────────────────────────────────

function SlideClosing() {
  return (
    <div className="flex flex-col items-center text-center px-6">
      <FlaskConical className="kn-rise h-9 w-9" style={{ color: GOLD, animationDelay: "40ms" }} />
      <h2
        className="kn-rise mt-6 font-semibold"
        style={{ ...SERIF, color: INK, fontSize: "clamp(36px, 7vw, 84px)", lineHeight: 1.05, animationDelay: "100ms" }}
      >
        One photo. Whole class.
      </h2>
      <p className="kn-rise mt-6 text-base sm:text-lg" style={{ color: GOLD, animationDelay: "220ms", ...SERIF }}>
        Generate — 1 tap. Approve — 1 tap. Scan the room — 3 taps.
      </p>
    </div>
  );
}

// ── Deck ──────────────────────────────────────────────────────────────────

const SLIDES = [
  { render: () => <SlideTitle />, tint: GOLD },
  { render: () => <SlideStatement />, tint: GOLD_DEEP },
  { render: () => <SlideGenerate />, tint: GOLD },
  { render: () => <SlideApprove />, tint: GOLD_DEEP },
  { render: () => <SlideBatchScan />, tint: GREEN },
  { render: () => <SlideTriage />, tint: INDIGO },
  { render: () => <SlideClosing />, tint: GOLD },
];

export default function Keynote3Page() {
  return <KeynoteDeck slides={SLIDES} />;
}
