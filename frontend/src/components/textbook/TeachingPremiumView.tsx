"use client";

/**
 * The premium redesign of the Teaching page — same brief as
 * TeachingClassicView (same props, renders only, owns no state), so the
 * classic/premium toggle can never affect audio, voice recognition,
 * check-understanding, or any other behavior — only how it looks. See
 * useDesignVersion for the toggle this is gated behind.
 */

import Link from "next/link";
import {
  ArrowLeft, ChevronLeft, Loader2, Mic, MicOff, PartyPopper, Volume2, VolumeX, AlertTriangle,
  Maximize2, Minimize2, HelpCircle, CheckCircle2, Lightbulb,
  Compass, Search, Eye, Sparkles, Languages,
} from "lucide-react";
import { getTextbookFigureUrl, type TextbookChapterDetail, type QuestPhase } from "@/lib/api";
import { DiagramView } from "@/components/textbook/DiagramView";
import type { TeachingViewProps } from "@/components/textbook/TeachingClassicView";
import { cn } from "@/lib/utils";

const QUEST_STEPS: QuestPhase[] = ["guess", "investigate", "observe", "infer"];
const QUEST_LABEL: Record<QuestPhase, string> = { guess: "Guess", investigate: "Investigate", observe: "Observe", infer: "Infer" };
// A distinct icon per quest phase — a visual anchor for each teaching beat
// so a long segment reads as "the Investigate part" rather than an
// undifferentiated wall of text.
const QUEST_ICON: Record<QuestPhase, typeof Sparkles> = { guess: Sparkles, investigate: Search, observe: Eye, infer: Compass };

const VOICE_STYLE_LABEL = { neutral: "Standard accent", indian: "Indian accent" } as const;

function QuestStepper({ current, dark }: { current: QuestPhase | null; dark?: boolean }) {
  const idx = current ? QUEST_STEPS.indexOf(current) : -1;
  const line = dark ? "rgba(245,241,231,0.16)" : "rgba(23,22,27,0.08)";
  const faint = dark ? "#B9B4C4" : "#9A968A";
  return (
    <div className="flex items-center justify-center">
      {QUEST_STEPS.map((step, i) => {
        const active = i === idx;
        const done = i < idx;
        return (
          <div key={step} className="flex items-center">
            <div className="flex flex-col items-center gap-1.5">
              <div
                className={cn("rounded-full", active && "tp-pulse")}
                style={
                  active
                    ? { width: "0.75rem", height: "0.75rem", background: "#D7A24E", boxShadow: "0 0 0 0.3125rem rgba(215,162,78,0.22), 0 0 1rem rgba(215,162,78,0.55)" }
                    : { width: "0.5625rem", height: "0.5625rem", background: done ? "#B97F2C" : line }
                }
              />
              <span className="text-[0.71875rem] font-semibold" style={{ color: active ? "#B97F2C" : faint }}>
                {QUEST_LABEL[step]}
              </span>
            </div>
            {i < QUEST_STEPS.length - 1 && <div className="w-12 h-[0.09375rem] mb-5" style={{ background: line }} />}
          </div>
        );
      })}
    </div>
  );
}

function CheckPanel(p: TeachingViewProps & { full?: boolean }) {
  const { checkQuestion, checkRevealed, handleRevealAnswer, dismissCheck, full } = p;
  if (!checkQuestion) return null;
  return (
    <div
      className={`bg-[#17161B]/28 backdrop-blur-sm flex items-center justify-center z-10 p-4 ${
        full ? "fixed inset-0 z-[70]" : "absolute inset-0 rounded-[1.625rem]"
      }`}
    >
      <div className="w-full max-w-xl max-h-full overflow-y-auto bg-white rounded-[1.625rem] p-6 sm:p-10 shadow-[0_30px_70px_rgba(23,22,27,0.28)]">
        <div className="flex items-center gap-2 text-[#8A5D1E] mb-4">
          <HelpCircle className="h-4 w-4" />
          <span className="text-xs font-bold tracking-wide">CHECK UNDERSTANDING</span>
        </div>
        <p className="font-serif text-xl sm:text-2xl font-semibold leading-snug mb-5 text-slate-900" style={{ fontFamily: "var(--font-fraunces), Georgia, serif" }}>
          {checkQuestion.question}
        </p>
        <ul className="flex flex-col gap-2.5 mb-5">
          {checkQuestion.options.map((opt, i) => {
            const isCorrect = checkRevealed && i === checkQuestion.correct_index;
            return (
              <li
                key={i}
                className={`flex items-start gap-3 rounded-2xl border px-4 py-3.5 text-sm ${
                  isCorrect ? "border-emerald-300 bg-emerald-50 text-emerald-800 font-semibold" : "border-slate-200 text-slate-700"
                }`}
              >
                <span className="font-bold text-slate-400 shrink-0">{String.fromCharCode(65 + i)}</span>
                <span className="flex-1">{opt}</span>
                {isCorrect && <CheckCircle2 className="h-[1.125rem] w-[1.125rem] text-emerald-600 shrink-0" />}
              </li>
            );
          })}
        </ul>
        {checkRevealed && checkQuestion.explanation && (
          <p className="text-sm text-slate-600 leading-relaxed border-l-[3px] border-[#D7A24E] pl-4 mb-6">
            {checkQuestion.explanation}
          </p>
        )}
        <div className="flex items-center gap-3">
          {!checkRevealed ? (
            <>
              <button onClick={handleRevealAnswer} className="bg-[#241F49] hover:bg-[#332B6B] transition-colors text-white px-6 py-3 rounded-2xl text-sm font-bold">Show answer</button>
              <button onClick={dismissCheck} className="text-sm font-medium text-slate-400 hover:text-slate-600">Cancel</button>
            </>
          ) : (
            <button onClick={dismissCheck} className="bg-[#241F49] hover:bg-[#332B6B] transition-colors text-white px-6 py-3 rounded-2xl text-sm font-bold">Continue teaching</button>
          )}
        </div>
      </div>
    </div>
  );
}

// Shown once, the first time Continue is tapped in a visit where this
// chapter already had progress from before — a condensed "here's what we
// covered" recap, so resuming a lesson (or revising before an exam) never
// just drops back in with no reminder of where things left off.
function RevisionPanel(p: TeachingViewProps & { full?: boolean }) {
  const { revisionRecap, dismissRevisionRecap, full } = p;
  if (!revisionRecap) return null;
  return (
    <div
      className={`bg-[#17161B]/28 backdrop-blur-sm flex items-center justify-center z-10 p-4 ${
        full ? "fixed inset-0 z-[70]" : "absolute inset-0 rounded-[1.625rem]"
      }`}
    >
      <div className="w-full max-w-xl max-h-full overflow-y-auto bg-white rounded-[1.625rem] p-6 sm:p-10 shadow-[0_30px_70px_rgba(23,22,27,0.28)]">
        <div className="flex items-center gap-2 text-[#453B87] mb-4">
          <Lightbulb className="h-4 w-4" />
          <span className="text-xs font-bold tracking-wide">QUICK RECAP</span>
        </div>
        <p className="font-serif text-xl sm:text-2xl font-semibold leading-snug mb-5 text-slate-900" style={{ fontFamily: "var(--font-fraunces), Georgia, serif" }}>
          What we&rsquo;ve covered so far
        </p>
        <ul className="flex flex-col gap-2.5 mb-6">
          {revisionRecap.map((point, i) => (
            <li key={i} className="flex items-start gap-3 rounded-2xl border border-[#EDEAF9] bg-[#F7F5FC] px-4 py-3.5 text-sm text-slate-700">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[#453B87]" />
              <span className="flex-1">{point}</span>
            </li>
          ))}
        </ul>
        <div className="flex items-center gap-3">
          <button onClick={dismissRevisionRecap} className="bg-[#241F49] hover:bg-[#332B6B] transition-colors text-white px-6 py-3 rounded-2xl text-sm font-bold">Continue</button>
          <button onClick={dismissRevisionRecap} className="text-sm font-medium text-slate-400 hover:text-slate-600">Skip</button>
        </div>
      </div>
    </div>
  );
}

function StageContent({
  chapter, textbookId, segmentIndex, segmentText, revealedText, stillRevealing, figureId, figureCaption, diagramSpec, speaking, loading, questPhase, dark,
}: TeachingViewProps & { dark: boolean }) {
  const textColor = dark ? "#F5F1E7" : "#17161B";
  // A long segment reads as a denser wall of text than a short one — pull
  // the size and line-height in a little so it still feels composed rather
  // than overwhelming, instead of one fixed size for every length. Uses
  // whichever text is actually on screen right now.
  const long = (revealedText || segmentText).length > 420;
  const PhaseIcon = chapter.pedagogy === "quest" && questPhase ? QUEST_ICON[questPhase] : null;
  const textStyle = {
    fontFamily: "var(--font-fraunces), Georgia, serif" as const,
    // This is the actual lesson text a teacher/student reads — was a
    // vw-based clamp() capped at a 27-34px MAX regardless of viewport
    // width (so it never grew past that on any screen, however large) in
    // dark/fullscreen mode, and a flat, completely non-scaling hardcoded
    // px value outside fullscreen — confirmed 2026-09-22 as the reason a
    // 70"+ display still showed unreadably small lesson content even
    // though the Continue/other buttons (ordinary rem-based Tailwind
    // classes) scaled correctly. Plain rem now, same as everywhere else —
    // scales with the root font-size breakpoints in globals.css.
    fontSize: long ? "1.375rem" : "1.75rem",
    lineHeight: long ? 1.45 : 1.5,
    color: textColor,
  };
  return (
    <div className="flex flex-col items-center gap-6 sm:gap-7 max-w-3xl mx-auto px-4">
      {stillRevealing ? (
        // Lesson text arriving live from teach-next-stream, or already
        // fully arrived and still being typed out — takes over from
        // whatever the PREVIOUS segment was still showing (see fetchNext)
        // the moment any of it has arrived, so "Continue" doesn't sit on a
        // spinner for the whole generation. No key/remount here: this
        // block stays mounted and its own text node just grows, which is
        // what makes it look like live typing instead of the fade-in
        // flashing on every incoming chunk. revealedText/stillRevealing are
        // owned by the page component, not computed here — see its comment
        // for why (this component remounts on the isFullscreen toggle,
        // which would otherwise reset the paced reveal mid-stream).
        <div className="tp-rise flex flex-col items-center gap-6 sm:gap-7 w-full">
          <p className="text-center font-normal" style={textStyle}>{revealedText}</p>
        </div>
      ) : loading && !segmentText ? (
        <div className="flex flex-col items-center gap-3 py-10">
          <Loader2 className={`h-8 w-8 animate-spin ${dark ? "text-amber-300" : "text-indigo-500"}`} />
          <p className={dark ? "text-sm text-[#B9B4C4]" : "text-sm text-slate-500"}>Getting the lesson ready…</p>
        </div>
      ) : (
        // Keyed on the segment INDEX (not the text) so this re-mounts —
        // and plays its fade+rise entrance — exactly once per real new
        // segment, not once per streamed-in chunk.
        <div key={segmentIndex} className="tp-rise flex flex-col items-center gap-6 sm:gap-7 w-full">
          {PhaseIcon && !figureId && !diagramSpec && (
            <div
              className="w-11 h-11 rounded-full flex items-center justify-center"
              style={{ background: dark ? "rgba(215,162,78,0.14)" : "#F6EAD3", color: dark ? "#D7A24E" : "#8A5D1E" }}
            >
              <PhaseIcon className="h-5 w-5" />
            </div>
          )}
          {figureId && (
            <figure className={`w-full max-w-md rounded-3xl p-5 ${dark ? "bg-white/5 border border-white/10 backdrop-blur" : "bg-white shadow-[0_16px_40px_rgba(23,22,27,0.07)]"}`}>
              <img
                src={getTextbookFigureUrl(textbookId, figureId)}
                alt={figureCaption || "Diagram from the textbook"}
                className="w-full h-auto max-h-64 object-contain rounded-xl"
              />
              {figureCaption && (
                <figcaption
                  className="mt-2.5 text-center text-[0.84375rem] italic"
                  style={{ fontFamily: "var(--font-fraunces), Georgia, serif", color: dark ? "#B9B4C4" : "#9A968A" }}
                >
                  {figureCaption}
                </figcaption>
              )}
            </figure>
          )}
          {!figureId && diagramSpec && (
            <div className={`w-full max-w-md rounded-3xl p-5 ${dark ? "bg-white/5 border border-white/10 backdrop-blur" : "bg-white shadow-[0_16px_40px_rgba(23,22,27,0.07)]"}`}>
              <DiagramView spec={diagramSpec} />
            </div>
          )}
          <p className="text-center font-normal" style={textStyle}>
            {segmentText}
          </p>
          <div className="flex items-center gap-2.5">
            <div className={`w-7 h-7 rounded-full flex items-center justify-center ${dark ? "bg-amber-400/15" : "bg-indigo-50"}`}>
              <Volume2 className={`h-[0.8125rem] w-[0.8125rem] ${dark ? "text-amber-300" : "text-indigo-700"}`} />
            </div>
            {speaking && (
              <div className="flex items-end gap-[0.1875rem] h-4">
                {[0, 0.15, 0.3, 0.45].map((delay) => (
                  <span
                    key={delay}
                    className="w-[0.1875rem] rounded-sm animate-[eq_1.1s_ease-in-out_infinite]"
                    style={{ background: dark ? "#D7A24E" : "#B97F2C", animationDelay: `${delay}s` }}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function TeachingPremiumView(p: TeachingViewProps) {
  const {
    sessionId, chapter, isLastSegment, questPhase, error, muted, listening,
    isFullscreen, voiceStyle, checkQuestion, checkLoading, hasSpeechRecognition,
    hasPrevious, goToPrevious, revisionRecap, fetchNext, stopSpeaking, setMuted, cycleVoiceStyle, setIsFullscreen,
    startListening, stopListening, handleCheckUnderstanding, loading,
    designToggle,
  } = p;

  if (isFullscreen) return <PremiumStage {...p} />;

  return (
    // pb-24/pb-28 gives the sticky Continue bar below room to fully "catch"
    // and clear the content above it before the page runs out of room to
    // scroll — without it, a long segment (6-7+ sentences) scrolls its last
    // lines directly UNDER the sticky bar with nowhere further to scroll to
    // reveal them (position: sticky reserves no extra runway on its own).
    // PremiumStage (fullscreen) already does the equivalent via its own
    // pb-40/pb-48 padding; this brings the normal in-page view in line with
    // it. Confirmed 2026-09-22.
    <div className="space-y-6 pb-24 sm:pb-28">
      <style>{`
        @keyframes eq{0%,100%{height:5px}50%{height:16px}}
        @keyframes tp-rise-kf{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
        @keyframes tp-pulse-kf{0%,100%{box-shadow:0 0 0 5px rgba(215,162,78,0.22),0 0 16px rgba(215,162,78,0.55)}50%{box-shadow:0 0 0 7px rgba(215,162,78,0.14),0 0 24px rgba(215,162,78,0.7)}}
        .tp-rise{animation:tp-rise-kf 520ms cubic-bezier(0.16,1,0.3,1) both}
        .tp-pulse{animation:tp-pulse-kf 2.2s ease-in-out infinite}
        @media (prefers-reduced-motion: reduce){.tp-rise,.tp-pulse{animation:none!important}}
      `}</style>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href={`/sessions/${sessionId}/textbook`} className="flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-700">
          <ArrowLeft className="h-3.5 w-3.5" /> Textbook
        </Link>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {designToggle}
          <button onClick={() => setIsFullscreen(true)} className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-500 hover:bg-slate-50">
            <Maximize2 className="h-3.5 w-3.5" /> <span className="hidden sm:inline">Full screen</span>
          </button>
          <button onClick={cycleVoiceStyle} title="Switch voice accent" className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-500 hover:bg-slate-50">
            <Languages className="h-3.5 w-3.5" /> <span className="hidden sm:inline">{VOICE_STYLE_LABEL[voiceStyle]}</span>
          </button>
          <button
            onClick={() => { if (p.speaking) stopSpeaking(); setMuted((m) => !m); }}
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-500 hover:bg-slate-50"
          >
            {muted ? <VolumeX className="h-3.5 w-3.5" /> : <Volume2 className="h-3.5 w-3.5" />}
            <span className="hidden sm:inline">{muted ? "Muted" : "Sound on"}</span>
          </button>
        </div>
      </div>

      <div className="text-center">
        <h1
          className="font-semibold tracking-tight text-slate-900"
          style={{ fontFamily: "var(--font-fraunces), Georgia, serif", fontSize: "1.75rem" }}
        >
          {chapter.title}
        </h1>
        {chapter.pedagogy === "quest" && questPhase ? (
          <div className="mt-4 overflow-x-auto"><QuestStepper current={questPhase} /></div>
        ) : (
          <p className="text-[0.8125rem] text-slate-400 mt-2">
            Pages {chapter.start_page}–{chapter.end_page}
            {p.segmentIndex !== null && <> &middot; Part {p.segmentIndex + 1}</>}
          </p>
        )}
      </div>

      <div className="relative bg-gradient-to-b from-[#FBFAF7] to-[#F7F5F0] rounded-[1.75rem] py-10 sm:py-12 min-h-[17.5rem] flex items-center justify-center">
        <StageContent {...p} dark={false} />
        {checkQuestion && <CheckPanel {...p} />}
        {revisionRecap && <RevisionPanel {...p} />}
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertTriangle className="h-4 w-4 shrink-0" /> {error}
        </div>
      )}

      {/* Sticky so a long segment never pushes it out of easy reach — it
          floats near the bottom of the viewport once you scroll past it,
          instead of only living at the very end of the page. */}
      {!checkQuestion && !revisionRecap && !isLastSegment && (
        <div className="sticky bottom-3 sm:bottom-4 z-20 flex justify-center px-1">
          <div className="flex flex-col items-center gap-2 bg-white/95 backdrop-blur-xl border border-slate-200/70 rounded-3xl shadow-[0_20px_50px_rgba(23,22,27,0.16)] px-3.5 py-3 sm:px-5 sm:py-4 max-w-full">
            <div className="flex flex-wrap items-center justify-center gap-2 sm:gap-3">
              {hasPrevious && (
                <button
                  onClick={goToPrevious}
                  disabled={loading}
                  className="flex items-center gap-1.5 rounded-2xl border border-slate-200 bg-white px-4 sm:px-5 py-3 sm:py-3.5 text-sm font-semibold text-slate-600 hover:bg-slate-50 disabled:opacity-40"
                >
                  <ChevronLeft className="h-4 w-4" /> Previous
                </button>
              )}
              <button
                onClick={fetchNext}
                disabled={loading}
                className="bg-[#241F49] hover:bg-[#332B6B] disabled:opacity-60 transition-colors text-white px-6 sm:px-8 py-3 sm:py-3.5 rounded-2xl text-sm sm:text-[0.9375rem] font-bold flex items-center gap-2"
              >
                {loading ? <><Loader2 className="h-4 w-4 animate-spin" /> Thinking…</> : "Continue"}
              </button>
              {hasSpeechRecognition && (
                <button
                  onClick={() => (listening ? stopListening() : startListening())}
                  disabled={loading}
                  className={`flex items-center gap-2 rounded-2xl border px-4 sm:px-5 py-3 sm:py-3.5 text-sm font-semibold transition-colors ${
                    listening ? "border-indigo-300 bg-indigo-50 text-indigo-700" : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  {listening ? <Mic className="h-4 w-4 animate-pulse" /> : <MicOff className="h-4 w-4" />}
                  Say &ldquo;Continue&rdquo;
                </button>
              )}
              {chapter.taught_log.length > 0 && (
                <button
                  onClick={handleCheckUnderstanding}
                  disabled={checkLoading}
                  className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 sm:px-5 py-3 sm:py-3.5 text-sm font-semibold text-slate-600 hover:bg-slate-50"
                >
                  {checkLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <HelpCircle className="h-4 w-4" />}
                  Check understanding
                </button>
              )}
            </div>
            <p className="text-[0.6875rem] sm:text-xs text-slate-400 text-center">Tap Continue, or say &ldquo;continue&rdquo; when you&rsquo;re ready for the next part.</p>
          </div>
        </div>
      )}
      {!checkQuestion && isLastSegment && (
        <div className="flex flex-col items-center gap-3 py-6 text-center">
          <PartyPopper className="h-10 w-10 text-amber-500" />
          <p className="font-semibold text-lg text-slate-900" style={{ fontFamily: "var(--font-fraunces), Georgia, serif" }}>Chapter complete!</p>
          <div className="flex items-center gap-3">
            {hasPrevious && (
              <button onClick={goToPrevious} className="flex items-center gap-1.5 border border-slate-200 text-slate-600 px-5 py-3 rounded-2xl text-sm font-semibold hover:bg-slate-50">
                <ChevronLeft className="h-4 w-4" /> Previous
              </button>
            )}
            {chapter.taught_log.length > 0 && (
              <button onClick={handleCheckUnderstanding} disabled={checkLoading} className="border border-slate-200 text-slate-600 px-5 py-3 rounded-2xl text-sm font-semibold hover:bg-slate-50">
                Check understanding
              </button>
            )}
            <Link href={`/sessions/${sessionId}/textbook`} className="border border-slate-200 text-slate-600 px-5 py-3 rounded-2xl text-sm font-semibold hover:bg-slate-50">
              Back to Textbook
            </Link>
          </div>
        </div>
      )}

      {chapter.taught_log.length > 0 && (
        <details className="rounded-2xl border border-slate-200 bg-white p-5">
          <summary className="cursor-pointer text-sm font-semibold text-slate-700">
            What we&rsquo;ve covered so far ({chapter.taught_log.length})
          </summary>
          <ul className="mt-3 space-y-1.5 text-sm text-slate-600 list-disc list-inside">
            {chapter.taught_log.map((line, i) => <li key={i}>{line}</li>)}
          </ul>
        </details>
      )}
    </div>
  );
}

function PremiumStage(p: TeachingViewProps) {
  const {
    chapter, isLastSegment, questPhase, muted, listening,
    checkQuestion, checkLoading, hasSpeechRecognition, hasPrevious, goToPrevious,
    revisionRecap, fetchNext, stopSpeaking,
    setMuted, setIsFullscreen, startListening, stopListening,
    handleCheckUnderstanding, loading, error,
  } = p;

  const showControls = !checkQuestion && !revisionRecap;
  // The bottom bar is fixed to the viewport, not the flex flow, so a long
  // segment can never push Continue / Check understanding out of reach —
  // this was the exact bug reported: lots of text meant the controls sat
  // below the fold with no obvious way back (especially with an airmouse,
  // where "just scroll down" isn't discoverable).
  const bottomBarSafePad = { paddingBottom: "max(1.25rem, env(safe-area-inset-bottom, 0px))" };

  return (
    <div
      className="fixed inset-0 z-50 overflow-hidden"
      style={{ background: "radial-gradient(ellipse 900px 560px at 50% 34%, #1C1833, #131022 68%)", color: "#F5F1E7" }}
    >
      <style>{`
        @keyframes eq{0%,100%{height:6px}50%{height:20px}}
        @keyframes tp-rise-kf{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
        @keyframes tp-pulse-kf{0%,100%{box-shadow:0 0 0 5px rgba(215,162,78,0.22),0 0 16px rgba(215,162,78,0.55)}50%{box-shadow:0 0 0 7px rgba(215,162,78,0.14),0 0 24px rgba(215,162,78,0.7)}}
        @keyframes tp-drift-kf{0%,100%{transform:translate(-50%,-50%) scale(1)}50%{transform:translate(-46%,-54%) scale(1.08)}}
        .tp-rise{animation:tp-rise-kf 520ms cubic-bezier(0.16,1,0.3,1) both}
        .tp-pulse{animation:tp-pulse-kf 2.2s ease-in-out infinite}
        .tp-drift{animation:tp-drift-kf 16s ease-in-out infinite}
        @media (prefers-reduced-motion: reduce){.tp-rise,.tp-pulse,.tp-drift{animation:none!important}}
      `}</style>

      {/* Ambient motion — the same slow-drifting glow used in the keynote
          deck, so the immersive stage and the unveiling it's shown in feel
          like one continuous world rather than two different products. */}
      <div className="tp-drift pointer-events-none absolute left-1/2 top-1/3 h-[32.5rem] w-[32.5rem] -translate-x-1/2 -translate-y-1/2 rounded-full opacity-[0.14] blur-[110px]" style={{ background: "#D7A24E" }} />

      <button
        onClick={() => setIsFullscreen(false)}
        className="fixed top-4 right-4 sm:top-6 sm:right-6 z-[60] flex items-center gap-2 rounded-full bg-white/8 border border-white/20 backdrop-blur-md text-white pl-3.5 pr-4 sm:pl-4 sm:pr-5 py-2.5 sm:py-3 text-xs sm:text-sm font-semibold hover:bg-white/14 transition-colors"
      >
        <Minimize2 className="h-4 w-4" /> <span className="hidden sm:inline">Exit full screen</span>
      </button>

      {/* The only scrolling region — header/footer chrome stays fixed to
          the viewport around it, so scrolling here never hides them. */}
      <div className="absolute inset-0 overflow-y-auto">
        <div className="min-h-full flex flex-col items-center justify-center gap-8 px-4 pt-20 sm:pt-24 pb-40 sm:pb-48">
          {chapter.pedagogy === "quest" && questPhase ? (
            <QuestStepper current={questPhase} dark />
          ) : (
            <p className="text-center text-[0.8125rem] text-[#B9B4C4]">
              Pages {chapter.start_page}–{chapter.end_page}
              {p.segmentIndex !== null && <> &middot; Part {p.segmentIndex + 1}</>}
            </p>
          )}

          <StageContent {...p} dark={true} />

          {error && (
            <div className="flex items-center gap-2 rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
              <AlertTriangle className="h-4 w-4 shrink-0" /> {error}
            </div>
          )}
        </div>
      </div>

      {checkQuestion && <CheckPanel {...p} full />}
      {revisionRecap && <RevisionPanel {...p} full />}

      {showControls && !isLastSegment && (
        // pointer-events-none on this wrapper, -auto on the pill inside:
        // this div spans the FULL viewport width (inset-x-0) so its bottom
        // control pill can center itself, but the pill itself is much
        // narrower — the empty space around/below it was still capturing
        // hit-testing (elementFromPoint), which broke the airmouse's
        // edge-of-screen auto-scroll (useEdgeAutoScroll.ts): hovering that
        // "dead space" near the bottom edge resolved to THIS div, and
        // walking up its real DOM ancestors (it's a sibling of, not nested
        // inside, this stage's own scroll container) landed on the
        // dashboard layout's own <main> instead — invisible behind this
        // fullscreen overlay, so scrolling it did nothing the teacher could
        // see. Confirmed 2026-09-22. Letting hit-testing pass through the
        // empty space fixes this without touching the shared hook.
        <div className="fixed bottom-0 inset-x-0 z-[60] flex justify-center px-4 pb-6 sm:pb-11 pointer-events-none" style={bottomBarSafePad}>
          <div className="pointer-events-auto flex flex-wrap items-center justify-center gap-1.5 sm:gap-2 bg-white/7 border border-white/20 backdrop-blur-xl p-2 sm:p-2.5 rounded-full shadow-[0_20px_60px_rgba(0,0,0,0.45)] max-w-full">
            {hasPrevious && (
              <button
                onClick={goToPrevious}
                disabled={loading}
                aria-label="Previous"
                className="w-10 h-10 sm:w-11 sm:h-11 rounded-full flex items-center justify-center text-white hover:bg-white/10 transition-colors disabled:opacity-40"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
            )}
            <button
              onClick={fetchNext}
              disabled={loading}
              className="px-6 sm:px-8 py-3 sm:py-3.5 rounded-full text-sm font-bold disabled:opacity-60"
              style={{ background: "linear-gradient(135deg,#D7A24E,#B97F2C)", color: "#1C1200" }}
            >
              {loading ? "Thinking…" : "Continue"}
            </button>
            {hasSpeechRecognition && (
              <button
                onClick={() => (listening ? stopListening() : startListening())}
                disabled={loading}
                className="flex items-center gap-2 px-4 sm:px-5 py-3 sm:py-3.5 rounded-full text-sm font-semibold text-white hover:bg-white/10 transition-colors"
              >
                {listening ? <Mic className="h-4 w-4 animate-pulse" /> : <MicOff className="h-4 w-4" />}
                <span className="hidden sm:inline">Say &ldquo;Continue&rdquo;</span>
              </button>
            )}
            <div className="w-px h-5 bg-white/20 hidden sm:block" />
            {chapter.taught_log.length > 0 && (
              <button
                onClick={handleCheckUnderstanding}
                disabled={checkLoading}
                aria-label="Check understanding"
                className="w-10 h-10 sm:w-11 sm:h-11 rounded-full flex items-center justify-center hover:bg-white/10 transition-colors"
              >
                {checkLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <HelpCircle className="h-4 w-4" />}
              </button>
            )}
            <button
              onClick={() => { if (p.speaking) stopSpeaking(); setMuted((m) => !m); }}
              aria-label={muted ? "Unmute" : "Mute"}
              className="w-10 h-10 sm:w-11 sm:h-11 rounded-full flex items-center justify-center hover:bg-white/10 transition-colors"
            >
              {muted ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
            </button>
          </div>
        </div>
      )}
      {showControls && isLastSegment && (
        // Same pointer-events split as the bar above — see that comment.
        <div className="fixed bottom-0 inset-x-0 z-[60] flex justify-center px-4 pb-6 sm:pb-11 pointer-events-none" style={bottomBarSafePad}>
          <div className="pointer-events-auto flex flex-col items-center gap-2.5 bg-white/7 border border-white/20 backdrop-blur-xl px-7 sm:px-8 py-4 sm:py-5 rounded-3xl shadow-[0_20px_60px_rgba(0,0,0,0.45)] text-center">
            <PartyPopper className="h-9 w-9 sm:h-10 sm:w-10" style={{ color: "#D7A24E" }} />
            <p className="font-semibold text-base sm:text-lg" style={{ fontFamily: "var(--font-fraunces), Georgia, serif" }}>Chapter complete!</p>
            <div className="flex items-center gap-2.5">
              {hasPrevious && (
                <button onClick={goToPrevious} className="flex items-center gap-1.5 bg-white/10 border border-white/20 text-white px-5 py-2.5 sm:py-3 rounded-2xl text-sm font-semibold hover:bg-white/16">
                  <ChevronLeft className="h-4 w-4" /> Previous
                </button>
              )}
              <button onClick={() => setIsFullscreen(false)} className="bg-white/10 border border-white/20 text-white px-5 py-2.5 sm:py-3 rounded-2xl text-sm font-semibold hover:bg-white/16">
                Back to panel view
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
