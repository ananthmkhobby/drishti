"use client";

/**
 * Live "teach me this chapter" view — displays one AI-generated teaching
 * segment at a time (large, readable) with synced TTS narration, and pauses
 * for the student to tap or say "continue" before advancing. Mirrors the
 * OpenAI-TTS-with-browser-speechSynthesis-fallback pattern and the
 * SpeechRecognition stop-word listener already used in ClassroomBrain.tsx,
 * kept local to this page rather than imported since neither is exported
 * from there.
 */

import { use, useCallback, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { AlertTriangle, History, Sparkles } from "lucide-react";
import { api, type TextbookDiagramSpec, type QuestPhase, type CheckUnderstandingResponse } from "@/lib/api";
import { LoadingScreen } from "@/components/ui/Spinner";
import { useDesignVersion } from "@/hooks/useDesignVersion";
import { useTypewriter } from "@/hooks/useTypewriter";
import { TeachingClassicView } from "@/components/textbook/TeachingClassicView";
import { TeachingPremiumView } from "@/components/textbook/TeachingPremiumView";
import type { VoiceStyle } from "@/components/textbook/teachingVoice";

// Same shape/using-pattern as ClassroomBrain.tsx's SpeechRecognitionLike —
// duplicated locally since that file doesn't export it.
interface SpeechRecognitionResultLike { isFinal: boolean; 0: { transcript: string } }
interface SpeechRecognitionEventLike { resultIndex: number; results: ArrayLike<SpeechRecognitionResultLike> }
interface SpeechRecognitionLike {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

function getSpeechRecognition(): SpeechRecognitionLike | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  return Ctor ? new Ctor() : null;
}

// One BCP-47 tag per supported textbook language, for both
// SpeechRecognition.lang and picking a matching browser TTS voice.
const LOCALE_BY_LANGUAGE: Record<string, string> = {
  en: "en-IN", hi: "hi-IN", kn: "kn-IN", te: "te-IN", mr: "mr-IN", ta: "ta-IN",
};

// "Continue" trigger words per detected textbook language — common,
// widely-recognized words for continuing/being ready, not exhaustive
// phrasing. Worth a native-speaker pass before relying on this heavily;
// the on-screen Continue button always works regardless of language.
const CONTINUE_PATTERNS: Record<string, RegExp> = {
  en: /\b(continue|go on|next|ready|yes please|keep going)\b/i,
  hi: /(आगे|जारी|अगला|तैयार)/,
  kn: /(ಮುಂದುವರಿಸಿ|ಮುಂದೆ|ಸಿದ್ಧ)/,
  te: /(కొనసాగించు|తరువాత|తర్వాత|సిద్ధం)/,
  mr: /(पुढे|सुरू ठेवा|तयार)/,
  ta: /(தொடரவும்|அடுத்து|தயார்)/,
};

// Steers gpt-4o-mini-tts toward a warm, expressive delivery for the
// Teaching page specifically — other callers of /voice/speak (quick
// assistant answers elsewhere) keep the flatter default tone. There is no
// SSML or break-tag support in this API — `instructions` free text is the
// ONLY lever available, so it has to be concrete and vivid rather than a
// short generic adjective list; a terse instruction ("speak warmly") was
// confirmed to still come out as one flat, continuous read with no real
// pausing. Remembered per-device via localStorage since it's a listening
// preference, not something that needs to sync across devices.
const VOICE_STYLE_STORAGE_KEY = "aci_textbook_voice_style";
const BASE_VOICE_INSTRUCTIONS =
  "Voice: a warm, animated schoolteacher speaking live to a class of children — " +
  "not a narrator reading a script aloud. Do NOT deliver this as one continuous, " +
  "evenly-paced stream of words; that reads as robotic no matter how friendly the " +
  "tone is.\n" +
  "Pacing: vary your speed on purpose. Slow down and land slightly harder on key " +
  "terms, numbers, and the words right before or after a comma. Speed up slightly " +
  "through small connecting words (\"and\", \"so\", \"now\"). Take a real, audible " +
  "half-beat breath-pause at every comma and full stop — not a rushed comma, an " +
  "actual brief silence — and a longer pause (like a teacher letting a point sink " +
  "in) at an ellipsis or before revealing an answer.\n" +
  "Pitch: let your pitch genuinely rise through a question and fall at the end of " +
  "a statement, the way a real voice does when actually thinking and reacting in " +
  "the moment, not a flat reading register.\n" +
  "Emotion: sound genuinely curious and a little delighted by the subject, as if " +
  "watching the class's faces for a spark of understanding as you go.";
const VOICE_INSTRUCTIONS: Record<VoiceStyle, string> = {
  neutral: BASE_VOICE_INSTRUCTIONS,
  indian: BASE_VOICE_INSTRUCTIONS +
    "\nAccent: speak with the natural rhythm, intonation, and accent of an Indian " +
    "English-medium school teacher — the melodic rise-and-fall and syllable-timed " +
    "cadence a student in an Indian classroom would recognize as their own " +
    "teacher's voice, clearly articulated. Not an American or British accent.",
};

function loadStoredVoiceStyle(): VoiceStyle {
  if (typeof window === "undefined") return "neutral";
  try {
    const stored = window.localStorage.getItem(VOICE_STYLE_STORAGE_KEY);
    return stored === "indian" ? "indian" : "neutral";
  } catch {
    return "neutral";
  }
}

let voicesPromise: Promise<SpeechSynthesisVoice[]> | null = null;
function loadVoices(): Promise<SpeechSynthesisVoice[]> {
  if (typeof window === "undefined" || !window.speechSynthesis) return Promise.resolve([]);
  if (voicesPromise) return voicesPromise;
  voicesPromise = new Promise((resolve) => {
    const existing = window.speechSynthesis.getVoices();
    if (existing.length) { resolve(existing); return; }
    window.speechSynthesis.onvoiceschanged = () => resolve(window.speechSynthesis.getVoices());
    setTimeout(() => resolve(window.speechSynthesis.getVoices()), 500);
  });
  return voicesPromise;
}

async function speakWithBrowser(text: string, locale: string, onDone: () => void) {
  if (typeof window === "undefined" || !window.speechSynthesis) { onDone(); return; }
  const utter = new SpeechSynthesisUtterance(text);
  const voices = await loadVoices();
  const exact = voices.find((v) => v.lang === locale);
  const sameLang = voices.find((v) => v.lang?.startsWith(locale.split("-")[0]));
  const enFallback = voices.find((v) => v.lang?.startsWith("en"));
  const chosen = exact ?? sameLang ?? enFallback;
  if (chosen) utter.voice = chosen;
  utter.rate = 0.95;
  utter.onend = onDone;
  utter.onerror = onDone;
  window.speechSynthesis.speak(utter);
}

export default function TeachingPage({
  params,
}: {
  params: Promise<{ sessionId: string; textbookId: string; chapterId: string }>;
}) {
  const { sessionId, textbookId, chapterId } = use(params);

  const [segmentIndex, setSegmentIndex] = useState<number | null>(null);
  const [segmentText, setSegmentText] = useState<string>("");
  const [streamingText, setStreamingText] = useState<string>("");
  const [isLastSegment, setIsLastSegment] = useState(false);
  const [figureId, setFigureId] = useState<string | null>(null);
  const [figureCaption, setFigureCaption] = useState<string | null>(null);
  const [diagramSpec, setDiagramSpec] = useState<TextbookDiagramSpec | null>(null);
  const [questPhase, setQuestPhase] = useState<QuestPhase | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [speaking, setSpeaking] = useState(false);
  const [muted, setMuted] = useState(false);
  const [listening, setListening] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [voiceStyle, setVoiceStyle] = useState<VoiceStyle>("neutral");
  const { version, toggle: toggleDesign } = useDesignVersion("teaching");

  // Owned here, not inside the view components, because toggling
  // isFullscreen swaps between two ENTIRELY separate JSX subtrees inside
  // TeachingPremiumView (the inline StageContent call vs. the one inside
  // PremiumStage) — React unmounts one and mounts the other, which would
  // wipe any reveal-progress state living inside that component. Keeping it
  // here, in the component that never remounts across that toggle, is what
  // makes the paced reveal survive a fullscreen toggle instead of visibly
  // restarting from the beginning — confirmed 2026-09-23 this was exactly
  // why "Full screen" mid-stream looked like it regenerated the segment.
  // Only paces text that's genuinely arriving live from fetchNext's stream
  // — a plain page load/resume (the effect below) or jumping to an
  // already-generated segment (advanceToIndex) show their text instantly,
  // same as before this feature existed. Without this distinction, opening
  // a chapter you'd already been teaching sat through the SAME ~25s paced
  // reveal as a fresh generation for content that was already fully known
  // the instant the page loaded — confirmed 2026-09-23 live (635 chars at
  // ~40ms/char). A ref, not state: it only needs to be correct at the
  // moment each setSegmentText/setStreamingText call it accompanies is
  // read back during the render that follows, not on its own schedule.
  const isLiveStreamRef = useRef(false);
  const revealTarget = streamingText || segmentText;
  const revealedText = useTypewriter(revealTarget, { intervalMs: 40, enabled: isLiveStreamRef.current });
  const stillRevealing = isLiveStreamRef.current && revealTarget.length > 0 && revealedText.length < revealTarget.length;

  useEffect(() => { setVoiceStyle(loadStoredVoiceStyle()); }, []);

  const cycleVoiceStyle = useCallback(() => {
    setVoiceStyle((current) => {
      const next: VoiceStyle = current === "neutral" ? "indian" : "neutral";
      try { window.localStorage.setItem(VOICE_STYLE_STORAGE_KEY, next); } catch { /* private mode etc. — fine, just won't persist */ }
      return next;
    });
  }, []);

  const [checkQuestion, setCheckQuestion] = useState<CheckUnderstandingResponse | null>(null);
  const [checkLoading, setCheckLoading] = useState(false);
  const [checkRevealed, setCheckRevealed] = useState(false);

  // Revision recap — a condensed "here's what we covered" bullet list shown
  // once, the first time Continue is pressed during a visit where the
  // chapter already had progress from before (picking a lesson back up,
  // revising before an exam) — not for a chapter just started fresh in
  // this same sitting. See hadPriorProgressRef below and goToNext.
  const [revisionRecap, setRevisionRecap] = useState<string[] | null>(null);
  const revisionShownRef = useRef(false);
  const hadPriorProgressRef = useRef<boolean | null>(null);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const spokenIndexRef = useRef<number | null>(null);
  // Bumped every time playback is (re)started or explicitly stopped — lets
  // an in-flight speak() call notice it's been superseded by a newer one
  // (e.g. Previous tapped again before the TTS fetch for the last tap even
  // came back) and drop its result instead of playing it. Without this, two
  // speak() calls racing on the network could both eventually reach "play
  // the audio" and you'd hear two voices talking over each other.
  const speakTokenRef = useRef(0);

  const { data: chapter, isLoading: chapterLoading, mutate: mutateChapter } = useSWR(
    ["textbook-chapter", textbookId, chapterId],
    () => api.getTextbookChapter(textbookId, chapterId),
    { revalidateOnFocus: false }
  );

  const stopSpeaking = useCallback(() => {
    speakTokenRef.current += 1;
    window.speechSynthesis?.cancel();
    if (audioRef.current) { audioRef.current.pause(); audioRef.current = null; }
    setSpeaking(false);
  }, []);

  // Stop any voice still playing if the teacher navigates away from this
  // page entirely (a different tab, back to the session, etc.) — otherwise
  // the audio element / speechSynthesis utterance keeps going in the
  // background since nothing else would ever pause it once this component
  // unmounts.
  useEffect(() => stopSpeaking, [stopSpeaking]);

  const locale = LOCALE_BY_LANGUAGE[chapter?.language_code ?? "en"] ?? "en-IN";

  const speak = useCallback(async (text: string) => {
    if (muted) return;
    stopSpeaking();
    const myToken = speakTokenRef.current; // captured right after the bump above — the freshest call owns playback until superseded
    setSpeaking(true);
    try {
      // Streamed (see api.streamSpeechToAudio) — starts on the first audio
      // chunk instead of waiting for the whole narration to generate, which
      // matters more here than almost anywhere else: a chapter segment can
      // run to several sentences, so the old buffer-the-whole-clip approach
      // meant a real, multi-second silent wait before each one started.
      const audio = await api.streamSpeechToAudio(text, VOICE_INSTRUCTIONS[voiceStyle]);
      if (speakTokenRef.current !== myToken) return; // superseded while the TTS request was in flight — drop it, don't play
      const url = audio.src;
      audioRef.current = audio;
      audio.onended = () => { URL.revokeObjectURL(url); setSpeaking(false); };
      audio.onerror = () => { URL.revokeObjectURL(url); setSpeaking(false); };
      await audio.play();
      if (speakTokenRef.current !== myToken) { audio.pause(); URL.revokeObjectURL(url); return; } // superseded while play() itself was resolving
    } catch {
      if (speakTokenRef.current !== myToken) return;
      await speakWithBrowser(text, locale, () => setSpeaking(false));
    }
  }, [muted, stopSpeaking, locale, voiceStyle]);

  // Load the chapter's furthest-taught segment on mount (resume), without
  // consuming a new one — a page refresh shouldn't silently skip ahead.
  useEffect(() => {
    if (!chapter) return;
    if (chapter.last_segment_text) {
      isLiveStreamRef.current = false;
      setSegmentIndex(chapter.current_segment_index - 1);
      setSegmentText(chapter.last_segment_text);
      setIsLastSegment(chapter.is_last_segment);
      setFigureId(chapter.last_segment_figure_id);
      setFigureCaption(chapter.last_segment_figure_caption);
      setDiagramSpec(chapter.last_segment_diagram_spec);
      setQuestPhase(chapter.last_segment_quest_phase);
    }
    // Captured ONCE, the first time chapter data arrives — whether this
    // chapter already had taught content BEFORE this visit (picking up a
    // lesson from before) vs. starting fresh right now. Deliberately not
    // re-derived from chapter.taught_log on every render, since that grows
    // as fetchNext() is called during THIS visit and would otherwise make
    // the revision recap fire mid-lesson too, not just on genuine resume.
    if (hadPriorProgressRef.current === null) {
      hadPriorProgressRef.current = (chapter.taught_log?.length ?? 0) > 0;
    }
  }, [chapter]);

  // Speak whenever the displayed segment changes (including the very first
  // load of a freshly-started chapter) — but only once per segment index.
  useEffect(() => {
    if (segmentIndex === null || !segmentText) return;
    if (spokenIndexRef.current === segmentIndex) return;
    spokenIndexRef.current = segmentIndex;
    speak(segmentText);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [segmentIndex, segmentText]);

  const fetchNext = useCallback(async () => {
    setError(null);
    stopSpeaking();
    setLoading(true);
    setStreamingText("");
    isLiveStreamRef.current = true;
    try {
      // Streams the lesson text in live (see StageContent's render: once
      // streamingText has anything in it, it takes over from whatever the
      // PREVIOUS segment was still showing) instead of the "Continue"
      // button just sitting on "Thinking…" for the whole ~5-10s
      // generation — reported 2026-09-22. segmentIndex/segmentText/etc.
      // below are still only ever set ONCE, atomically, from the final
      // "done" payload — same as the old non-streaming call — so nothing
      // downstream of them (the speak-on-new-segment effect, the taught
      // history) sees a partial/inconsistent state mid-stream.
      const seg = await api.teachNextSegmentStream(textbookId, chapterId, (delta) => {
        setStreamingText((prev) => prev + delta);
      });
      setSegmentIndex(seg.segment_index);
      setSegmentText(seg.segment_text);
      setIsLastSegment(seg.is_last_segment);
      setFigureId(seg.figure_id);
      setFigureCaption(seg.figure_caption);
      setDiagramSpec(seg.diagram_spec);
      setQuestPhase(seg.quest_phase);
      setStreamingText("");
      await mutateChapter();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not generate the next part — please try again.");
    } finally {
      setLoading(false);
    }
  }, [textbookId, chapterId, mutateChapter, stopSpeaking]);

  // Jump the displayed segment to an already-generated one from the
  // chapter's own history (chapter.segments, backed by the server's cached
  // segments array) — free, instant, no API call, since the content was
  // already generated and is just being re-shown.
  const advanceToIndex = useCallback((idx: number) => {
    // Never jump the displayed segment while a real generation is still in
    // flight — fetchNext()'s eventual response unconditionally sets the
    // segment it generated, so navigating in the meantime would just get
    // silently overwritten a moment later, which reads as "why did it jump
    // back on its own?".
    if (loading) return;
    const target = chapter?.segments?.[idx];
    if (!target) return;
    stopSpeaking();
    isLiveStreamRef.current = false;
    setSegmentIndex(target.segment_index);
    setSegmentText(target.segment_text);
    setIsLastSegment(target.is_last_segment);
    setFigureId(target.figure_id);
    setFigureCaption(target.figure_caption);
    setDiagramSpec(target.diagram_spec);
    setQuestPhase(target.quest_phase);
  }, [chapter, stopSpeaking, loading]);

  const hasPrevious = segmentIndex !== null && segmentIndex > 0;

  const goToPrevious = useCallback(() => {
    if (segmentIndex === null || segmentIndex <= 0) return;
    advanceToIndex(segmentIndex - 1);
  }, [segmentIndex, advanceToIndex]);

  // The actual "move forward" step: if we're behind the frontier (the
  // teacher stepped back earlier), just step forward through what's
  // already been generated — same cached content every time, never a
  // fresh generation for an index that's already been taught, so the class
  // never sees the segment at a given point change out from under it. Only
  // calls the real API (a fresh LLM generation, genuinely new content)
  // once we're actually at the frontier with nothing generated yet for
  // what's next. Separated from goToNext so the revision recap below can
  // trigger this same step once it's been dismissed.
  const advanceOrGenerate = useCallback(async () => {
    const segs = chapter?.segments ?? [];
    if (segmentIndex !== null && segmentIndex + 1 < segs.length) {
      advanceToIndex(segmentIndex + 1);
      return;
    }
    await fetchNext();
  }, [segmentIndex, chapter, advanceToIndex, fetchNext]);

  // Dismissing the revision recap (Skip, or Continue from inside it) always
  // proceeds with the step Continue was originally going to take.
  const dismissRevisionRecap = useCallback(() => {
    setRevisionRecap(null);
    advanceOrGenerate();
  }, [advanceOrGenerate]);

  // The "Continue" action. The first time it's pressed in a visit where
  // this chapter already had progress from before, show a condensed recap
  // of what's been covered instead of immediately advancing — a genuine
  // resume (picking a lesson back up, revising before an exam) deserves a
  // reminder of where things left off; a chapter just started fresh in
  // this same sitting does not, hence hadPriorProgressRef rather than
  // re-checking taught_log live (which grows during the visit itself).
  const goToNext = useCallback(async () => {
    if (loading) return; // a generation (or another advance) is already in flight
    if (!revisionShownRef.current && hadPriorProgressRef.current) {
      revisionShownRef.current = true;
      setLoading(true);
      try {
        const recap = await api.reviseChapter(textbookId, chapterId);
        setRevisionRecap(recap.points);
        return;
      } catch {
        // Recap generation failing shouldn't block the lesson — fall
        // through to the normal continue below.
      } finally {
        setLoading(false);
      }
    }
    await advanceOrGenerate();
  }, [loading, textbookId, chapterId, advanceOrGenerate]);

  // Auto-start a brand-new chapter (no segments taught yet).
  useEffect(() => {
    if (!chapter) return;
    if (chapter.current_segment_index === 0 && segmentIndex === null && !loading) {
      fetchNext();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapter]);

  const stopListening = useCallback(() => {
    try { recognitionRef.current?.stop(); } catch { /* already stopped */ }
    recognitionRef.current = null;
    setListening(false);
    // Hand the mic back to the wake-word detector — mirrors startListening's
    // pauseWakeWord() below; see that comment for why this pairing exists.
    api.resumeWakeWord().catch(() => {});
  }, []);

  const continuePattern = CONTINUE_PATTERNS[chapter?.language_code ?? "en"] ?? CONTINUE_PATTERNS.en;

  const startListening = useCallback(async () => {
    const recognition = getSpeechRecognition();
    if (!recognition) return;
    // The backend's "Hey XP" wake-word detector holds the Pi's only
    // microphone continuously — the exact same contention ClassroomBrain.tsx
    // already works around (see its startListening: "asking it to step
    // aside BEFORE requesting our own mic access avoids the two fighting
    // over the same hardware, which otherwise broke voice commands
    // entirely"). This page's "continue" listener never had that
    // coordination, so on the Pi (unlike a plain dev browser tab with no
    // wake-word service running) it silently never picked up any audio —
    // reported 2026-09-22 as "continue" not working once inside a chapter.
    await api.pauseWakeWord().catch(() => {});
    recognition.continuous = true;
    recognition.interimResults = false;
    recognition.lang = locale;
    recognition.onresult = (event) => {
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal && continuePattern.test(result[0].transcript)) {
          stopListening();
          goToNext();
          return;
        }
      }
    };
    recognition.onerror = () => stopListening();
    recognition.onend = () => { setListening(false); api.resumeWakeWord().catch(() => {}); };
    recognitionRef.current = recognition;
    recognition.start();
    setListening(true);
  }, [goToNext, stopListening, locale, continuePattern]);

  useEffect(() => stopListening, [stopListening]);

  const handleCheckUnderstanding = useCallback(async () => {
    setError(null);
    stopSpeaking();
    stopListening();
    setCheckRevealed(false);
    setCheckLoading(true);
    try {
      const check = await api.checkUnderstanding(textbookId, chapterId);
      setCheckQuestion(check);
      speak(check.question);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not generate a check-understanding question.");
    } finally {
      setCheckLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [textbookId, chapterId, stopSpeaking, stopListening]);

  const handleRevealAnswer = useCallback(() => {
    if (!checkQuestion) return;
    setCheckRevealed(true);
    speak(`${checkQuestion.options[checkQuestion.correct_index]}. ${checkQuestion.explanation}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [checkQuestion]);

  const dismissCheck = useCallback(() => {
    stopSpeaking();
    setCheckQuestion(null);
    setCheckRevealed(false);
  }, [stopSpeaking]);

  // Voice bridge from ClassroomBrain.tsx (the global tap-to-talk mic, not
  // this page's own always-on "continue" SpeechRecognition listener above —
  // a teacher already used to tapping the mic for every other page's voice
  // commands can do the same thing here). A bare "continue" routes here
  // instead of re-navigating since the page is already open (see
  // start_teaching's onTeachingPage branch in ClassroomBrain.tsx) — while a
  // check-understanding question is showing, "continue" dismisses it first,
  // same as tapping the on-screen "Continue teaching" button there does.
  // No check_understanding listener here anymore — that intent no longer
  // auto-opens the quiz from voice at all (see ClassroomBrain.tsx), only
  // ever from the explicit on-screen "Check understanding" tap.
  useEffect(() => {
    function onContinue() {
      if (checkQuestion) { dismissCheck(); return; }
      goToNext();
    }
    function onSetMuted(e: Event) {
      const detail = (e as CustomEvent<{ muted?: boolean }>).detail;
      if (typeof detail?.muted === "boolean") setMuted(detail.muted);
    }
    window.addEventListener("classroom-brain:teaching_continue", onContinue);
    window.addEventListener("classroom-brain:set_muted", onSetMuted);
    return () => {
      window.removeEventListener("classroom-brain:teaching_continue", onContinue);
      window.removeEventListener("classroom-brain:set_muted", onSetMuted);
    };
  }, [checkQuestion, dismissCheck, goToNext]);

  // Deliberately NOT the browser's native Fullscreen API — confirmed this is
  // unreliable in a classroom kiosk context: exiting depends on the Escape
  // key (which an airmouse/remote often can't send at all) or hunting for a
  // small in-page button whose click sometimes doesn't register cleanly once
  // real fullscreen has hidden all browser chrome. This is a pure CSS
  // "focus mode" instead — a fixed, full-viewport overlay with an always-
  // visible, large exit button in a fixed screen position, so leaving it is
  // never dependent on a keyboard or on scroll position. Escape still works
  // too, as a convenience, but is not the only way out.
  useEffect(() => {
    if (!isFullscreen) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") setIsFullscreen(false); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isFullscreen]);

  if (chapterLoading) return <LoadingScreen label="Loading chapter…" />;
  if (!chapter) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
        <AlertTriangle className="h-4 w-4 shrink-0" /> Chapter not found.
      </div>
    );
  }

  const hasSpeechRecognition = !!getSpeechRecognition();

  const viewProps = {
    sessionId, textbookId, chapter, segmentIndex, segmentText, streamingText, revealedText, stillRevealing, isLastSegment,
    figureId, figureCaption, diagramSpec, questPhase, loading, error, speaking,
    muted, listening, isFullscreen, voiceStyle, checkQuestion, checkLoading,
    checkRevealed, hasSpeechRecognition, hasPrevious, goToPrevious,
    revisionRecap, dismissRevisionRecap,
    fetchNext: goToNext, stopSpeaking, setMuted,
    cycleVoiceStyle, setIsFullscreen, startListening, stopListening,
    handleCheckUnderstanding, handleRevealAnswer, dismissCheck,
    designToggle: (
      <button
        onClick={toggleDesign}
        className="flex items-center gap-1.5 text-xs font-medium text-indigo-600 hover:text-indigo-800"
      >
        {version === "premium"
          ? <><History className="h-3.5 w-3.5" /> Classic view</>
          : <><Sparkles className="h-3.5 w-3.5" /> Try the new design</>}
      </button>
    ),
  };

  return version === "premium"
    ? <TeachingPremiumView {...viewProps} />
    : <TeachingClassicView {...viewProps} />;
}
