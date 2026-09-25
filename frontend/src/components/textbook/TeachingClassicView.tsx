"use client";

/**
 * The original Teaching page UI, extracted verbatim (same markup, same
 * classNames) so it keeps working exactly as before — this is the
 * guaranteed fallback if the premium redesign (TeachingPremiumView) ever
 * has a problem in real classroom use. Every prop here is state or a
 * handler owned by the parent page; this component renders only, it
 * never creates its own state, so there is nothing about "how teaching
 * behaves" for the design toggle to affect — only how it looks.
 */

import Link from "next/link";
import {
  ArrowLeft, ChevronLeft, Loader2, Mic, MicOff, PartyPopper, Volume2, VolumeX, AlertTriangle,
  Maximize2, Minimize2, HelpCircle, CheckCircle2, Lightbulb,
  Compass, Search, Eye, Sparkles, Languages,
} from "lucide-react";
import { getTextbookFigureUrl, type TextbookChapterDetail, type TextbookDiagramSpec, type QuestPhase, type CheckUnderstandingResponse } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { DiagramView } from "@/components/textbook/DiagramView";
import type { VoiceStyle } from "@/components/textbook/teachingVoice";

const QUEST_PHASE_META: Record<QuestPhase, { label: string; icon: typeof Compass }> = {
  guess: { label: "Guess", icon: Sparkles },
  investigate: { label: "Investigate", icon: Search },
  observe: { label: "Observe", icon: Eye },
  infer: { label: "Infer", icon: Lightbulb },
};

const VOICE_STYLE_LABEL: Record<VoiceStyle, string> = { neutral: "Standard accent", indian: "Indian accent" };

export interface TeachingViewProps {
  sessionId: string;
  textbookId: string;
  chapter: TextbookChapterDetail;
  segmentIndex: number | null;
  segmentText: string;
  // Lesson text arriving live from teach-next-stream, before the segment
  // is fully generated/committed — non-empty only while `loading` is true
  // for a Continue (not the very first segment of a chapter, which has no
  // prior text to show anything alongside). Once the stream finishes,
  // this clears and segmentText takes over. See fetchNext in the page
  // component and StageContent's render for how the two hand off.
  streamingText: string;
  // Paced reveal of streamingText||segmentText, and whether it's still
  // catching up — owned by the page component (see its comment) so it
  // survives the isFullscreen toggle remounting these view components.
  revealedText: string;
  stillRevealing: boolean;
  isLastSegment: boolean;
  figureId: string | null;
  figureCaption: string | null;
  diagramSpec: TextbookDiagramSpec | null;
  questPhase: QuestPhase | null;
  loading: boolean;
  error: string | null;
  speaking: boolean;
  muted: boolean;
  listening: boolean;
  isFullscreen: boolean;
  voiceStyle: VoiceStyle;
  checkQuestion: CheckUnderstandingResponse | null;
  checkLoading: boolean;
  checkRevealed: boolean;
  hasSpeechRecognition: boolean;
  hasPrevious: boolean;
  goToPrevious: () => void;
  revisionRecap: string[] | null;
  dismissRevisionRecap: () => void;
  fetchNext: () => void;
  stopSpeaking: () => void;
  setMuted: (updater: (m: boolean) => boolean) => void;
  cycleVoiceStyle: () => void;
  setIsFullscreen: (v: boolean) => void;
  startListening: () => void;
  stopListening: () => void;
  handleCheckUnderstanding: () => void;
  handleRevealAnswer: () => void;
  dismissCheck: () => void;
  designToggle: React.ReactNode;
}

export function TeachingClassicView(p: TeachingViewProps) {
  const {
    sessionId, textbookId, chapter, segmentIndex, segmentText, revealedText, stillRevealing, isLastSegment,
    figureId, figureCaption, diagramSpec, questPhase, loading, error, speaking,
    muted, listening, isFullscreen, voiceStyle, checkQuestion, checkLoading,
    checkRevealed, hasSpeechRecognition, hasPrevious, goToPrevious,
    revisionRecap, dismissRevisionRecap, fetchNext, stopSpeaking, setMuted,
    cycleVoiceStyle, setIsFullscreen, startListening, stopListening,
    handleCheckUnderstanding, handleRevealAnswer, dismissCheck, designToggle,
  } = p;

  return (
    <div className={isFullscreen ? "fixed inset-0 z-50 bg-white overflow-y-auto p-6 md:p-10 space-y-5" : "space-y-5"}>
      {isFullscreen && (
        <button
          onClick={() => setIsFullscreen(false)}
          className="fixed top-4 right-4 z-[60] flex items-center gap-2 rounded-full bg-slate-900/90 text-white pl-4 pr-5 py-3 text-sm font-semibold shadow-lg hover:bg-slate-900 transition-colors"
        >
          <Minimize2 className="h-5 w-5" /> Exit full screen
        </button>
      )}

      <div className="flex items-center justify-between gap-3">
        {!isFullscreen ? (
          <Link
            href={`/sessions/${sessionId}/textbook`}
            className="flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-700"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> Textbook
          </Link>
        ) : <span />}
        <div className="flex items-center gap-2">
          {!isFullscreen && designToggle}
          {!isFullscreen && (
            <button
              onClick={() => setIsFullscreen(true)}
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-500 hover:bg-slate-50"
            >
              <Maximize2 className="h-3.5 w-3.5" /> Full screen
            </button>
          )}
          <button
            onClick={cycleVoiceStyle}
            title="Switch voice accent"
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-500 hover:bg-slate-50"
          >
            <Languages className="h-3.5 w-3.5" />
            {VOICE_STYLE_LABEL[voiceStyle]}
          </button>
          <button
            onClick={() => {
              if (speaking) stopSpeaking();
              setMuted((m) => !m);
            }}
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-500 hover:bg-slate-50"
          >
            {muted ? <VolumeX className="h-3.5 w-3.5" /> : <Volume2 className="h-3.5 w-3.5" />}
            {muted ? "Muted" : "Sound on"}
          </button>
        </div>
      </div>

      <div className="text-center">
        <h1 className={isFullscreen ? "text-3xl font-bold text-slate-900" : "text-2xl font-bold text-slate-900"}>{chapter.title}</h1>
        <p className="text-xs text-slate-400 mt-1">
          Pages {chapter.start_page}–{chapter.end_page}
          {segmentIndex !== null && <> · Part {segmentIndex + 1}</>}
          {chapter.language_name && chapter.language_name !== "English" && <> · {chapter.language_name}</>}
        </p>
        {chapter.pedagogy === "quest" && questPhase && (
          <div className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-amber-50 border border-amber-200 px-3 py-1 text-xs font-semibold text-amber-700">
            {(() => { const Icon = QUEST_PHASE_META[questPhase].icon; return <Icon className="h-3.5 w-3.5" />; })()}
            {QUEST_PHASE_META[questPhase].label}
          </div>
        )}
      </div>

      {/* ── Main teaching surface ── */}
      <div className={
        isFullscreen
          ? "flex flex-col items-center justify-center gap-6 py-6"
          : "rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50/60 to-white shadow-sm p-8 md:p-10 min-h-[15rem] flex flex-col items-center justify-center gap-6"
      }>
        {stillRevealing ? (
          // Lesson text arriving live from teach-next-stream, or already
          // fully arrived and still being typed out — see the matching
          // comment in TeachingPremiumView.tsx's StageContent for why this
          // takes priority over the (possibly stale) previous segment the
          // moment any of it has arrived.
          <p className={
            isFullscreen
              ? "text-2xl md:text-4xl leading-relaxed text-slate-800 text-center max-w-4xl"
              : "text-xl md:text-2xl leading-relaxed text-slate-800 text-center max-w-2xl"
          }>
            {revealedText}
          </p>
        ) : loading && !segmentText ? (
          <div className="flex flex-col items-center gap-3 text-center">
            <Loader2 className="h-8 w-8 text-indigo-500 animate-spin" />
            <p className="text-sm text-slate-500">Getting the lesson ready…</p>
          </div>
        ) : (
          // Keyed on the segment INDEX so a new segment mounts this block
          // fresh rather than reusing the previous segment's DOM node —
          // display:contents keeps it a layout no-op in the parent flex
          // column.
          <div key={segmentIndex} className="contents">
            {figureId && (
              <figure className="w-full max-w-md">
                <img
                  src={getTextbookFigureUrl(textbookId, figureId)}
                  alt={figureCaption || "Diagram from the textbook"}
                  className="w-full h-auto max-h-72 object-contain rounded-xl border border-indigo-100 bg-white"
                />
                {figureCaption && (
                  <figcaption className="mt-2 text-center text-xs text-slate-400 italic">{figureCaption}</figcaption>
                )}
              </figure>
            )}
            {!figureId && diagramSpec && (
              <div className="w-full max-w-md rounded-xl border border-indigo-100 bg-white p-4">
                <DiagramView spec={diagramSpec} />
              </div>
            )}
            <p className={
              isFullscreen
                ? "text-2xl md:text-4xl leading-relaxed text-slate-800 text-center max-w-4xl"
                : "text-xl md:text-2xl leading-relaxed text-slate-800 text-center max-w-2xl"
            }>
              {segmentText}
              {speaking && <span className="inline-block ml-2 h-2.5 w-2.5 rounded-full bg-indigo-500 animate-pulse align-middle" />}
            </p>
          </div>
        )}
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertTriangle className="h-4 w-4 shrink-0" /> {error}
        </div>
      )}

      {/* ── Check understanding ── */}
      {checkQuestion && (
        <div className="rounded-2xl border border-amber-200 bg-amber-50/60 shadow-sm p-6 space-y-4">
          <div className="flex items-center gap-2 text-amber-700">
            <HelpCircle className="h-5 w-5" />
            <p className="text-xs font-semibold uppercase tracking-wide">Check understanding</p>
          </div>
          <p className="text-lg font-semibold text-slate-800">{checkQuestion.question}</p>
          <ul className="space-y-2">
            {checkQuestion.options.map((opt, i) => {
              const isCorrect = checkRevealed && i === checkQuestion.correct_index;
              return (
                <li
                  key={i}
                  className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-sm ${
                    isCorrect ? "border-emerald-300 bg-emerald-50 text-emerald-800" : "border-slate-200 bg-white text-slate-700"
                  }`}
                >
                  <span className="font-semibold shrink-0">{String.fromCharCode(65 + i)}.</span>
                  <span className="flex-1">{opt}</span>
                  {isCorrect && <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0" />}
                </li>
              );
            })}
          </ul>
          {checkRevealed && checkQuestion.explanation && (
            <p className="text-sm text-amber-800 leading-relaxed border-l-4 border-amber-300 pl-3">
              {checkQuestion.explanation}
            </p>
          )}
          <div className="flex items-center gap-3">
            {!checkRevealed ? (
              <Button onClick={handleRevealAnswer} size="sm">Show answer</Button>
            ) : (
              <Button onClick={dismissCheck} size="sm">Continue teaching</Button>
            )}
            {!checkRevealed && (
              <button onClick={dismissCheck} className="text-xs text-slate-400 hover:text-slate-600">Cancel</button>
            )}
          </div>
        </div>
      )}

      {/* ── Revision recap — shown once, the first time Continue is tapped in a
          visit where this chapter already had progress from before ── */}
      {revisionRecap && (
        <div className="rounded-2xl border border-indigo-200 bg-indigo-50/60 shadow-sm p-6 space-y-4">
          <div className="flex items-center gap-2 text-indigo-700">
            <Lightbulb className="h-5 w-5" />
            <p className="text-xs font-semibold uppercase tracking-wide">Quick recap — what we&rsquo;ve covered so far</p>
          </div>
          <ul className="space-y-2">
            {revisionRecap.map((point, i) => (
              <li key={i} className="flex items-start gap-2 rounded-lg border border-indigo-100 bg-white px-3 py-2 text-sm text-slate-700">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-indigo-400" />
                <span className="flex-1">{point}</span>
              </li>
            ))}
          </ul>
          <div className="flex items-center gap-3">
            <Button onClick={dismissRevisionRecap} size="sm">Continue</Button>
            <button onClick={dismissRevisionRecap} className="text-xs text-slate-400 hover:text-slate-600">Skip</button>
          </div>
        </div>
      )}

      {/* ── Controls ── */}
      {!checkQuestion && !revisionRecap && !isLastSegment && (
        <div className="flex flex-col items-center gap-3">
          <div className="flex flex-wrap items-center justify-center gap-3">
            {hasPrevious && (
              <button
                onClick={goToPrevious}
                disabled={loading}
                className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-xs font-medium text-slate-500 hover:bg-slate-50 disabled:opacity-40"
              >
                <ChevronLeft className="h-4 w-4" /> Previous
              </button>
            )}
            <Button onClick={fetchNext} disabled={loading} size="lg">
              {loading ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Thinking…</> : "Continue"}
            </Button>
            {hasSpeechRecognition && (
              <button
                onClick={() => (listening ? stopListening() : startListening())}
                disabled={loading}
                className={`flex items-center gap-1.5 rounded-lg border px-3 py-2.5 text-xs font-medium transition-colors ${
                  listening
                    ? "border-indigo-300 bg-indigo-50 text-indigo-700"
                    : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
                }`}
              >
                {listening ? <Mic className="h-4 w-4 animate-pulse" /> : <MicOff className="h-4 w-4" />}
                {listening ? "Listening for “Continue”" : "Say “Continue”"}
              </button>
            )}
            {chapter.taught_log.length > 0 && (
              <button
                onClick={handleCheckUnderstanding}
                disabled={checkLoading}
                className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-xs font-medium text-slate-500 hover:bg-slate-50"
              >
                {checkLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <HelpCircle className="h-4 w-4" />}
                Check understanding
              </button>
            )}
          </div>
          <p className="text-xs text-slate-400">Tap Continue, or say "continue" when you're ready for the next part.</p>
        </div>
      )}
      {!checkQuestion && isLastSegment && (
        <div className="flex flex-col items-center gap-3 py-6 text-center">
          <PartyPopper className="h-10 w-10 text-amber-500" />
          <p className="text-lg font-semibold text-slate-800">Chapter complete!</p>
          <div className="flex items-center gap-3">
            {hasPrevious && (
              <Button onClick={goToPrevious} variant="secondary">
                <ChevronLeft className="h-4 w-4 mr-2" /> Previous
              </Button>
            )}
            {chapter.taught_log.length > 0 && (
              <Button onClick={handleCheckUnderstanding} disabled={checkLoading} variant="secondary">
                {checkLoading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <HelpCircle className="h-4 w-4 mr-2" />}
                Check understanding
              </Button>
            )}
            <Link href={`/sessions/${sessionId}/textbook`}>
              <Button variant="secondary">Back to Textbook</Button>
            </Link>
          </div>
        </div>
      )}

      {/* ── Recap so far ── */}
      {chapter.taught_log.length > 0 && (
        <details className="rounded-xl border border-slate-200 bg-white p-4">
          <summary className="cursor-pointer text-sm font-medium text-slate-700">
            What we've covered so far ({chapter.taught_log.length})
          </summary>
          <ul className="mt-3 space-y-1.5 text-sm text-slate-600 list-disc list-inside">
            {chapter.taught_log.map((line, i) => <li key={i}>{line}</li>)}
          </ul>
        </details>
      )}
    </div>
  );
}
