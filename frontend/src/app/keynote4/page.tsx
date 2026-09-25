"use client";

/**
 * Keynote 4 — Case 3: Capture — image, audio, and video, all reached from
 * one tab. Same shell as /keynote2 and /keynote3.
 */

import {
  Camera, Mic, Play, Upload, Video, Square,
} from "lucide-react";
import {
  KeynoteDeck, Kicker, ClickCount, VoiceLine, StepFlow,
  SERIF, GOLD, GOLD_DEEP, INDIGO, GREEN, INK, INK_DIM,
} from "@/components/keynote/KeynoteShell";

// ── Slide 1 — cold open ──────────────────────────────────────────────────

function SlideTitle() {
  return (
    <div className="flex flex-col items-center text-center px-6">
      <div className="kn-rise text-[0.6875rem] sm:text-xs font-bold uppercase tracking-[0.4em]" style={{ color: INK_DIM }}>
        Case three
      </div>
      <h1
        className="kn-rise mt-6 font-semibold tracking-tight"
        style={{ ...SERIF, color: INK, fontSize: "clamp(40px, 8vw, 96px)", lineHeight: 1.02, animationDelay: "90ms" }}
      >
        Capture anything.
      </h1>
      <p className="kn-rise mt-7 max-w-lg text-base sm:text-xl" style={{ color: INK_DIM, animationDelay: "180ms" }}>
        A board, a voice, a demonstration — all in reach from one tab.
      </p>
    </div>
  );
}

// ── Slide 2 — statement ──────────────────────────────────────────────────

function SlideStatement() {
  return (
    <div className="flex flex-col items-center text-center px-6 gap-3">
      <p className="kn-rise text-xl sm:text-3xl" style={{ ...SERIF, color: INK_DIM, animationDelay: "40ms" }}>One tab.</p>
      <p className="kn-rise text-xl sm:text-3xl" style={{ ...SERIF, color: INK_DIM, animationDelay: "160ms" }}>Three ways in.</p>
      <p
        className="kn-rise mt-3 font-semibold"
        style={{ ...SERIF, color: GOLD, fontSize: "clamp(40px, 8vw, 96px)", lineHeight: 1.05, animationDelay: "320ms" }}
      >
        Point and tap.
      </p>
    </div>
  );
}

// ── Slide 3 — image capture ──────────────────────────────────────────────

const IMAGE_STEPS = [
  { label: "Capture", icon: Camera },
  { label: "Start Camera", icon: Camera },
  { label: "Shutter", icon: Camera },
  { label: "Use Photo", icon: Upload },
];

function SlideImage() {
  return (
    <div className="flex w-full max-w-2xl flex-col items-center px-6 text-center">
      <Kicker>The board, in seconds</Kicker>
      <h2 className="kn-rise font-semibold" style={{ ...SERIF, color: INK, fontSize: "clamp(32px, 6vw, 60px)", animationDelay: "100ms" }}>
        Photograph the board.
      </h2>

      <div className="mt-9"><ClickCount n={4} /></div>
      <div className="mt-8"><StepFlow steps={IMAGE_STEPS} /></div>

      <div className="mt-8"><VoiceLine text="Take a photo of the board" caption="jumps straight to the shutter" /></div>
    </div>
  );
}

// ── Slide 4 — audio recording ────────────────────────────────────────────

const AUDIO_STEPS = [
  { label: "Capture", icon: Mic },
  { label: "Start Recording", icon: Mic },
  { label: "Stop & Upload", icon: Square },
];

function SlideAudio() {
  return (
    <div className="flex w-full max-w-xl flex-col items-center px-6 text-center">
      <Kicker tint={GOLD_DEEP}>Capture the conversation</Kicker>
      <h2 className="kn-rise font-semibold" style={{ ...SERIF, color: INK, fontSize: "clamp(32px, 6vw, 60px)", animationDelay: "100ms" }}>
        Record the room.
      </h2>

      <div className="mt-9"><ClickCount n={3} /></div>
      <div className="mt-8"><StepFlow steps={AUDIO_STEPS} /></div>

      <div className="mt-8"><VoiceLine text="Start recording audio" caption="then, when you're done" /></div>
      <div className="mt-3"><VoiceLine text="Stop recording" caption="" /></div>
    </div>
  );
}

// ── Slide 5 — video recording ────────────────────────────────────────────

const VIDEO_STEPS = [
  { label: "Capture", icon: Video },
  { label: "Video tab", icon: Video },
  { label: "Start Recording", icon: Play },
];

function SlideVideo() {
  return (
    <div className="flex w-full max-w-xl flex-col items-center px-6 text-center">
      <Kicker tint={GREEN}>Show, don&rsquo;t just tell</Kicker>
      <h2 className="kn-rise font-semibold" style={{ ...SERIF, color: INK, fontSize: "clamp(32px, 6vw, 60px)", animationDelay: "100ms" }}>
        Record a demonstration.
      </h2>

      <div className="mt-9"><ClickCount n={3} /></div>
      <div className="mt-8"><StepFlow steps={VIDEO_STEPS} /></div>

      <div className="mt-8"><VoiceLine text="Record a video of this experiment" /></div>
    </div>
  );
}

// ── Slide 6 — closing ─────────────────────────────────────────────────────

const CLOSING_TILES: { icon: typeof Camera; label: string; count: string; tint: string }[] = [
  { icon: Camera, label: "Photo", count: "4 taps", tint: GOLD },
  { icon: Mic, label: "Audio", count: "3 taps", tint: GOLD_DEEP },
  { icon: Video, label: "Video", count: "3 taps", tint: GREEN },
];

function SlideClosing() {
  return (
    <div className="flex flex-col items-center text-center px-6">
      <h2
        className="kn-rise font-semibold"
        style={{ ...SERIF, color: INK, fontSize: "clamp(36px, 7vw, 84px)", lineHeight: 1.05, animationDelay: "80ms" }}
      >
        Point. Tap. Done.
      </h2>
      <p className="kn-rise mt-4 text-base sm:text-lg" style={{ color: GOLD, animationDelay: "160ms", ...SERIF }}>
        Every mode, one tab away — and every one voice-shortcuttable.
      </p>

      <div className="kn-rise mt-10 flex flex-wrap items-center justify-center gap-4" style={{ animationDelay: "260ms" }}>
        {CLOSING_TILES.map((t) => (
          <div key={t.label} className="flex w-32 flex-col items-center gap-2 rounded-2xl p-5" style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)" }}>
            <div className="flex h-10 w-10 items-center justify-center rounded-full" style={{ background: "rgba(215,162,78,0.16)" }}>
              <t.icon className="h-4.5 w-4.5" style={{ color: t.tint }} />
            </div>
            <span className="text-sm font-semibold" style={{ color: INK }}>{t.label}</span>
            <span className="text-xs font-bold" style={{ color: t.tint }}>{t.count}</span>
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
  { render: () => <SlideImage />, tint: GOLD },
  { render: () => <SlideAudio />, tint: GOLD_DEEP },
  { render: () => <SlideVideo />, tint: GREEN },
  { render: () => <SlideClosing />, tint: INDIGO },
];

export default function Keynote4Page() {
  return <KeynoteDeck slides={SLIDES} />;
}
