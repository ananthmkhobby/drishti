"use client";

/**
 * Keynote 2 — Case 1: teach / revise / check understanding with the fewest
 * possible taps. Standalone reveal deck, same shell as /keynote and /keynote3
 * /keynote4. Every number on screen matches the real app (see KeynoteShell.tsx
 * consumers and the flows it illustrates) — this is a sales deck, not fiction.
 */

import {
  ArrowRight, BookOpen, CheckCircle2, ChevronRight as StepArrow,
  HelpCircle, Lightbulb, PlayCircle, SkipForward,
} from "lucide-react";
import {
  KeynoteDeck, Kicker, ClickCount, VoiceLine, ButtonChip, Panel,
  SERIF, GOLD, GOLD_DEEP, INDIGO, GREEN, INK, INK_DIM,
} from "@/components/keynote/KeynoteShell";

// ── Slide 1 — cold open ──────────────────────────────────────────────────

function SlideTitle() {
  return (
    <div className="flex flex-col items-center text-center px-6">
      <div className="kn-rise text-[0.6875rem] sm:text-xs font-bold uppercase tracking-[0.4em]" style={{ color: INK_DIM }}>
        Case one
      </div>
      <h1
        className="kn-rise mt-6 font-semibold tracking-tight"
        style={{ ...SERIF, color: INK, fontSize: "clamp(40px, 8vw, 104px)", lineHeight: 1.02, animationDelay: "90ms" }}
      >
        Teach in one tap.
      </h1>
      <p className="kn-rise mt-7 max-w-lg text-base sm:text-xl" style={{ color: INK_DIM, animationDelay: "180ms" }}>
        Resume, revise, and check understanding — without ever leaving the lesson.
      </p>
    </div>
  );
}

// ── Slide 2 — statement ──────────────────────────────────────────────────

function SlideStatement() {
  return (
    <div className="flex flex-col items-center text-center px-6 gap-3">
      <p className="kn-rise text-xl sm:text-3xl" style={{ ...SERIF, color: INK_DIM, animationDelay: "40ms" }}>No menus.</p>
      <p className="kn-rise text-xl sm:text-3xl" style={{ ...SERIF, color: INK_DIM, animationDelay: "160ms" }}>No searching.</p>
      <p
        className="kn-rise mt-3 font-semibold"
        style={{ ...SERIF, color: GOLD, fontSize: "clamp(40px, 8vw, 96px)", lineHeight: 1.05, animationDelay: "320ms" }}
      >
        Just tap Continue.
      </p>
    </div>
  );
}

// ── Slide 3 — resume teaching ────────────────────────────────────────────

function SlideResume() {
  return (
    <div className="flex w-full max-w-xl flex-col items-center px-6 text-center">
      <Kicker>Reach yesterday&rsquo;s lesson</Kicker>
      <h2 className="kn-rise font-semibold" style={{ ...SERIF, color: INK, fontSize: "clamp(32px, 6vw, 60px)", animationDelay: "100ms" }}>
        Continue teaching.
      </h2>

      <div className="mt-9"><ClickCount n={1} /></div>

      <Panel className="mt-9 max-w-md">
        <div className="flex flex-col sm:flex-row sm:items-center gap-4 text-left">
          <div className="flex items-center gap-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full" style={{ background: "radial-gradient(circle at 34% 30%, #F6EAD3, #EDEAF9 72%)" }}>
              <BookOpen className="h-5 w-5" style={{ color: INDIGO }} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-[0.6875rem] font-bold" style={{ color: GOLD }}>PICK UP WHERE YOU LEFT OFF</div>
              <div className="text-sm font-semibold break-words" style={{ ...SERIF, color: INK }}>Photosynthesis — Part 3</div>
            </div>
          </div>
          <div className="sm:ml-auto"><ButtonChip icon={ArrowRight}>Continue teaching</ButtonChip></div>
        </div>
      </Panel>

      <div className="mt-8"><VoiceLine text="Let's continue the photosynthesis chapter" caption="or skip the tap entirely" /></div>
    </div>
  );
}

// ── Slide 4 — new chapter ────────────────────────────────────────────────

function SlideNewChapter() {
  return (
    <div className="flex w-full max-w-xl flex-col items-center px-6 text-center">
      <Kicker tint={GOLD_DEEP}>Starting something new</Kicker>
      <h2 className="kn-rise font-semibold" style={{ ...SERIF, color: INK, fontSize: "clamp(32px, 6vw, 60px)", animationDelay: "100ms" }}>
        Two taps to a new chapter.
      </h2>

      <div className="mt-9"><ClickCount n={2} /></div>

      <div className="kn-rise mt-10 flex items-center gap-4" style={{ animationDelay: "320ms" }}>
        <ButtonChip tint="rgba(255,255,255,0.10)">Textbook tab</ButtonChip>
        <StepArrow className="h-4 w-4" style={{ color: "rgba(255,255,255,0.3)" }} />
        <ButtonChip>Start teaching</ButtonChip>
      </div>

      <p className="kn-rise mt-7 max-w-sm text-sm sm:text-base" style={{ color: INK_DIM, animationDelay: "420ms" }}>
        Then the lesson opens itself — segment one loads with no third tap.
      </p>
    </div>
  );
}

// ── Slide 5 — revision recap ─────────────────────────────────────────────

const RECAP_POINTS = [
  "Photosynthesis converts light energy into chemical energy.",
  "Chlorophyll absorbs mostly red and blue light.",
  "The products are glucose and oxygen.",
];

function SlideRevise() {
  return (
    <div className="flex w-full max-w-xl flex-col items-center px-6 text-center">
      <Kicker tint={GREEN}>Nothing to remember</Kicker>
      <h2 className="kn-rise font-semibold" style={{ ...SERIF, color: INK, fontSize: "clamp(32px, 6vw, 60px)", animationDelay: "100ms" }}>
        Revision, built in.
      </h2>
      <p className="kn-rise mt-4 max-w-md text-sm sm:text-base" style={{ color: INK_DIM, animationDelay: "160ms" }}>
        The first &ldquo;Continue&rdquo; of the day quietly recaps last class — then the lesson picks up exactly where it stopped.
      </p>

      <Panel className="mt-9 max-w-md" delay="260ms">
        <div className="flex items-center gap-2 text-left">
          <Lightbulb className="h-4 w-4" style={{ color: GOLD }} />
          <span className="text-[0.6875rem] font-bold uppercase tracking-[0.15em]" style={{ color: GOLD }}>Where we left off</span>
        </div>
        <ul className="mt-3 space-y-2 text-left">
          {RECAP_POINTS.map((p) => (
            <li key={p} className="flex items-start gap-2 text-sm" style={{ color: INK }}>
              <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full" style={{ background: GOLD }} />
              {p}
            </li>
          ))}
        </ul>
        <div className="mt-4 flex items-center gap-2">
          <ButtonChip icon={ArrowRight}>Continue</ButtonChip>
          <ButtonChip tint="rgba(255,255,255,0.10)" icon={SkipForward}>Skip</ButtonChip>
        </div>
      </Panel>

      <p className="kn-rise mt-6 text-xs sm:text-sm" style={{ color: INK_DIM, animationDelay: "460ms" }}>
        Shown once per visit — every &ldquo;Continue&rdquo; after that goes straight to the lesson.
      </p>
    </div>
  );
}

// ── Slide 6 — check understanding ────────────────────────────────────────

function SlideCheck() {
  return (
    <div className="flex w-full max-w-xl flex-col items-center px-6 text-center">
      <Kicker tint={INDIGO}>Know who&rsquo;s following</Kicker>
      <h2 className="kn-rise font-semibold" style={{ ...SERIF, color: INK, fontSize: "clamp(32px, 6vw, 60px)", animationDelay: "100ms" }}>
        Check understanding.
      </h2>

      <div className="mt-9"><ClickCount n={1} sublabel="mid-lesson, no menu to find" /></div>

      <Panel className="mt-9 max-w-md" delay="260ms">
        <div className="flex items-center gap-2 text-left">
          <HelpCircle className="h-4 w-4" style={{ color: GOLD }} />
          <span className="text-[0.6875rem] font-bold uppercase tracking-[0.15em]" style={{ color: GOLD }}>Quick check</span>
        </div>
        <p className="mt-3 text-left text-sm" style={{ ...SERIF, color: INK }}>
          Why does a leaf appear green under white light?
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <ButtonChip tint="rgba(255,255,255,0.10)">Show answer</ButtonChip>
          <ButtonChip icon={PlayCircle}>Continue teaching</ButtonChip>
        </div>
      </Panel>

      <p className="kn-rise mt-6 max-w-sm text-xs sm:text-sm" style={{ color: INK_DIM, animationDelay: "460ms" }}>
        One tap on the toolbar generates a fresh question on the spot — no waiting for the whole session to finish.
      </p>
    </div>
  );
}

// ── Slide 7 — closing ─────────────────────────────────────────────────────

const SUMMARY_ROWS: { icon: typeof BookOpen; label: string; count: string; tint: string }[] = [
  { icon: BookOpen, label: "Continue teaching", count: "1 tap", tint: GOLD },
  { icon: Lightbulb, label: "Revise last class", count: "automatic", tint: GREEN },
  { icon: HelpCircle, label: "Check understanding", count: "1 tap", tint: INDIGO },
];

function SlideClosing() {
  return (
    <div className="flex flex-col items-center text-center px-6">
      <h2
        className="kn-rise font-semibold"
        style={{ ...SERIF, color: INK, fontSize: "clamp(36px, 7vw, 84px)", lineHeight: 1.05, animationDelay: "80ms" }}
      >
        Teach. Revise. Check.
      </h2>
      <p className="kn-rise mt-4 text-base sm:text-lg" style={{ color: GOLD, animationDelay: "160ms", ...SERIF }}>
        That&rsquo;s the whole workflow.
      </p>

      <div className="kn-rise mt-10 flex w-full max-w-sm flex-col gap-2.5" style={{ animationDelay: "260ms" }}>
        {SUMMARY_ROWS.map((r) => (
          <div key={r.label} className="flex items-center gap-3 rounded-2xl p-3.5" style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)" }}>
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg" style={{ background: "rgba(215,162,78,0.16)" }}>
              <r.icon className="h-4 w-4" style={{ color: GOLD }} />
            </div>
            <span className="flex-1 text-left text-sm font-medium" style={{ color: INK }}>{r.label}</span>
            <span className="flex shrink-0 items-center gap-1 text-xs font-bold" style={{ color: r.tint }}>
              <CheckCircle2 className="h-3.5 w-3.5" />{r.count}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Deck ──────────────────────────────────────────────────────────────────

const SLIDES = [
  { render: () => <SlideTitle />, tint: GOLD },
  { render: () => <SlideStatement />, tint: GOLD_DEEP },
  { render: () => <SlideResume />, tint: GOLD },
  { render: () => <SlideNewChapter />, tint: GOLD_DEEP },
  { render: () => <SlideRevise />, tint: GREEN },
  { render: () => <SlideCheck />, tint: INDIGO },
  { render: () => <SlideClosing />, tint: GOLD },
];

export default function Keynote2Page() {
  return <KeynoteDeck slides={SLIDES} />;
}
