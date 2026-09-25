"use client";

import { use, useEffect, useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import {
  Mic, Cpu, CheckCircle2, AlertTriangle, BarChart3,
  MessageSquare, ChevronRight, Lightbulb, Clock,
  TrendingUp, TrendingDown, Minus, Activity, Users, Download,
  ScanLine, Video, Eye, Camera,
} from "lucide-react";
import { api } from "@/lib/api";
import { fetchOutputsCached } from "@/lib/cached-fetchers";
import { useEventPoller } from "@/hooks/useEventPoller";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { LoadingScreen } from "@/components/ui/Spinner";
import { LanguageSelector } from "@/components/ui/LanguageSelector";
import { useTranslation } from "@/hooks/useTranslation";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function PacingBadge({ rating }: { rating: string }) {
  if (rating === "fast") return (
    <span className="flex items-center gap-1 rounded-full bg-red-100 px-2.5 py-1 text-xs font-semibold text-red-700">
      <TrendingUp className="h-3 w-3" /> Fast
    </span>
  );
  if (rating === "slow") return (
    <span className="flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-700">
      <TrendingDown className="h-3 w-3" /> Slow
    </span>
  );
  return (
    <span className="flex items-center gap-1 rounded-full bg-green-100 px-2.5 py-1 text-xs font-semibold text-green-700">
      <Minus className="h-3 w-3" /> Good Pace
    </span>
  );
}

interface EngagementPoint { minute: number; words: number; level: "high" | "medium" | "low" }
function EngagementTimeline({ curve }: { curve: EngagementPoint[] }) {
  if (!curve.length) return null;
  const maxWords = Math.max(...curve.map((c) => c.words), 1);
  const colourMap = { high: "#10b981", medium: "#f59e0b", low: "#e2e8f0" };
  return (
    <div>
      <div className="flex items-end gap-0.5 h-16">
        {curve.map((point) => (
          <div
            key={point.minute}
            title={`Min ${point.minute}: ${point.words} words`}
            className="flex-1 rounded-sm min-w-0"
            style={{ height: `${Math.max(4, Math.round((point.words / maxWords) * 100))}%`, backgroundColor: colourMap[point.level] }}
          />
        ))}
      </div>
      <div className="flex justify-between mt-1 text-[0.625rem] text-slate-400">
        <span>Min 1</span><span>Min {curve.length}</span>
      </div>
    </div>
  );
}

// ─── Source section header ────────────────────────────────────────────────────

function SourceHeader({
  icon,
  title,
  available,
  subtitle,
}: {
  icon: React.ReactNode;
  title: string;
  available: boolean;
  subtitle?: string;
}) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <div className={`flex h-9 w-9 items-center justify-center rounded-full ${available ? "bg-indigo-100" : "bg-slate-100"}`}>
        <span className={available ? "text-indigo-600" : "text-slate-400"}>{icon}</span>
      </div>
      <div>
        <div className="flex items-center gap-2">
          <h3 className="font-semibold text-slate-800 text-sm">{title}</h3>
          {available ? (
            <span className="rounded-full bg-green-100 px-2 py-0.5 text-[0.625rem] font-semibold text-green-700">Available</span>
          ) : (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[0.625rem] font-semibold text-slate-500">Not used</span>
          )}
        </div>
        {subtitle && <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>}
      </div>
    </div>
  );
}

// ─── Interfaces ───────────────────────────────────────────────────────────────

interface TopicSpoken { topic: string; evidence: string; approximate_time: string; }
interface Question    { question: string; approximate_time: string; answered: boolean; }
interface KeyMoment   { description: string; approximate_time: string; }
interface EngagementHighlight { minute: number; observation: string; type: "high" | "low" | "notable"; }

interface CombinedAnalysis {
  // New source-split format
  from_board?: {
    frames_analysed: number;
    topics: string[];
    board_summary: string;
  };
  from_audio?: {
    available: boolean;
    topics_spoken: TopicSpoken[];
    questions_detected: Question[];
    student_responses_detected: boolean;
    pacing: { rating: string; explanation: string };
    engagement_highlights: EngagementHighlight[];
    audio_summary: string;
  };
  from_audience?: {
    available: boolean;
    avg_attention_pct: number | null;
    high_attention_minutes: number[];
    low_attention_minutes: number[];
    audience_summary: string;
  };
  from_video?: {
    available: boolean;
    recording_count: number;
    frames_extracted: number;
    audio_transcribed: boolean;
    video_summary: string;
  };
  complete_analysis?: {
    summary: string;
    interactivity_score: number;
    liveness_score: number;
    overall_score: number;
    topics_on_board_not_spoken: string[];
    topics_spoken_not_on_board: string[];
    key_moments: KeyMoment[];
    suggestions: string;
  };
  // Legacy flat format (backward compat)
  summary?: string;
  suggestions?: string;
  topics_spoken?: TopicSpoken[];
  topics_on_board_not_spoken?: string[];
  topics_spoken_not_on_board?: string[];
  questions_detected?: Question[];
  student_responses_detected?: boolean;
  pacing?: { rating: string; explanation: string };
  engagement_highlights?: EngagementHighlight[];
  key_moments?: KeyMoment[];
  interactivity_score?: number;
  liveness_score?: number;
  overall_score?: number;
}

// ─── PDF export ───────────────────────────────────────────────────────────────

function downloadAnalysisPDF(analysis: CombinedAnalysis, subject: string, grade: string, language: string) {
  const ca = analysis.complete_analysis;
  const fb = analysis.from_board;
  const fa = analysis.from_audio;
  const langNote = language !== "english" ? ` · ${language.charAt(0).toUpperCase() + language.slice(1)}` : "";

  const item = (s: string) => `<div class="item">${s}</div>`;
  const section = (title: string, body: string) =>
    `<div class="section"><div class="section-title">${title}</div>${body}</div>`;

  const html = `<!DOCTYPE html><html><head><meta charset="UTF-8"/><title>Classroom Snapshot${langNote}</title>
<style>
  body{font-family:Arial,sans-serif;max-width:760px;margin:0 auto;padding:32px 40px;color:#1e293b;font-size:14px}
  h1{font-size:20px;color:#312e81;margin:0 0 4px}
  .meta{font-size:12px;color:#64748b;margin-bottom:24px;border-bottom:2px solid #6366f1;padding-bottom:10px}
  .source-section{margin-bottom:20px;border:1px solid #e2e8f0;border-radius:8px;padding:16px}
  .source-header{display:flex;align-items:center;gap:8px;margin-bottom:10px}
  .source-badge{font-size:11px;font-weight:700;padding:2px 8px;border-radius:20px}
  .badge-available{background:#dcfce7;color:#166534}
  .badge-unavailable{background:#f1f5f9;color:#64748b}
  .section{margin-bottom:16px}
  .section-title{font-size:13px;font-weight:700;color:#4338ca;border-left:3px solid #6366f1;padding-left:6px;margin-bottom:8px}
  .summary{background:#f0f4ff;border:1px solid #c7d2fe;border-radius:6px;padding:12px;font-size:13px;color:#3730a3}
  .item{padding:6px 10px;border-radius:5px;margin-bottom:5px;font-size:12px;background:#f8fafc;border:1px solid #e2e8f0}
  .footer{margin-top:24px;padding-top:8px;border-top:1px solid #e2e8f0;font-size:11px;color:#94a3b8;text-align:center}
</style></head><body>
<h1>${subject || "Class"} — Classroom Snapshot${langNote}</h1>
<div class="meta">${grade ? grade + " · " : ""}Combined Analysis Report</div>

${fb ? `<div class="source-section">
<div class="source-header"><span style="font-size:14px">📋</span><strong>From Board Frames</strong>
<span class="source-badge badge-available">${fb.frames_analysed} frames</span></div>
${fb.board_summary ? `<div class="summary">${fb.board_summary}</div>` : ""}
${fb.topics.length ? section("Topics Detected", fb.topics.map(t => item(t)).join("")) : ""}
</div>` : ""}

${fa ? `<div class="source-section">
<div class="source-header"><span style="font-size:14px">🎤</span><strong>From Audio Recording</strong>
<span class="source-badge ${fa.available ? "badge-available" : "badge-unavailable"}">${fa.available ? "Transcribed" : "Not available"}</span></div>
${fa.audio_summary ? `<div class="summary">${fa.audio_summary}</div>` : ""}
${fa.available && fa.topics_spoken.length ? section("Topics Spoken", fa.topics_spoken.map(t => item(`<strong>${t.topic}</strong> — ${t.evidence}`)).join("")) : ""}
${fa.available && fa.questions_detected.length ? section("Questions Detected", fa.questions_detected.map(q => item(`${q.question} (${q.answered ? "answered" : "unanswered"})`)).join("")) : ""}
</div>` : ""}

${ca ? `<div class="source-section">
<div class="source-header"><span style="font-size:14px">✅</span><strong>Complete Analysis</strong></div>
${ca.summary ? `<div class="summary">${ca.summary}</div>` : ""}
${ca.suggestions ? section("Suggestions", `<div class="summary" style="background:#fffbeb;border-color:#fde68a;color:#78350f">${ca.suggestions}</div>`) : ""}
${ca.key_moments.length ? section("Key Moments", ca.key_moments.map(m => item(`${m.approximate_time}: ${m.description}`)).join("")) : ""}
</div>` : ""}

<div class="footer">Generated by Drishti</div>
</body></html>`;

  const win = window.open("", "_blank");
  if (!win) return;
  win.document.write(html);
  win.document.close();
  win.focus();
  setTimeout(() => win.print(), 400);
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function ClassAnalysisPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  const [analysing, setAnalysing] = useState(false);
  const { language, setLanguage, translating, translate, t } = useTranslation();

  const { data: audioData, isLoading: audioLoading, mutate: mutateAudio } = useSWR(
    ["audio", sessionId],
    () => api.getAudio(sessionId).catch(() => null),
    { revalidateOnFocus: false },
  );
  const { data: audienceData } = useSWR(
    ["audience", sessionId],
    () => api.getAudienceMetrics(sessionId).catch(() => null),
    { revalidateOnFocus: false },
  );
  const [retryingAudioId, setRetryingAudioId] = useState<string | null>(null);

  async function handleRetryTranscription(audioId: string) {
    setRetryingAudioId(audioId);
    try { await api.retryTranscription(sessionId, audioId); await mutateAudio(); }
    catch { /* ignore */ }
    finally { setRetryingAudioId(null); }
  }

  const { data: outputs, isLoading: outputsLoading, mutate: mutateOutputs } = useSWR(
    ["outputs", sessionId],
    () => fetchOutputsCached(sessionId),
    { refreshInterval: (data): number =>
        (analysing || (data as { outputs?: { combined_analysis?: { status?: string } } } | undefined)?.outputs?.combined_analysis?.status === "processing") ? 4000 : 0 },
  );

  const analysisOutput = outputs?.outputs?.combined_analysis;
  const analysis = analysisOutput?.data as CombinedAnalysis | undefined;

  useEffect(() => {
    if (analysisOutput?.status === "processing") setAnalysing(true);
    if (analysisOutput?.status === "ready" || analysisOutput?.status === "failed") setAnalysing(false);
  }, [analysisOutput?.status]);

  useEventPoller({ sessionId, onOutputReady: () => mutateOutputs(), onAudioTranscribed: () => mutateOutputs() });

  async function handleAnalyse() {
    try { await api.triggerGeneration(sessionId, ["combined_analysis"]); setAnalysing(true); mutateOutputs(); }
    catch { /* ignore */ }
  }

  const { data: session } = useSWR(["session", sessionId], () => api.getSession(sessionId), { revalidateOnFocus: false });

  // Collect translatable strings (must be before early return)
  useEffect(() => {
    if (!analysis) return;
    const ca = analysis.complete_analysis;
    const fa = analysis.from_audio;
    const strings = [
      ca?.summary, ca?.suggestions,
      analysis.summary, analysis.suggestions,
      analysis.pacing?.explanation, fa?.pacing?.explanation, fa?.audio_summary,
      analysis.from_board?.board_summary,
      ...(fa?.topics_spoken?.flatMap(ts => [ts.topic, ts.evidence]) ?? []),
      ...(analysis.topics_spoken?.flatMap(ts => [ts.topic, ts.evidence]) ?? []),
      ...(ca?.topics_on_board_not_spoken ?? []),
      ...(ca?.topics_spoken_not_on_board ?? []),
      ...(fa?.questions_detected?.map(q => q.question) ?? []),
      ...(analysis.questions_detected?.map(q => q.question) ?? []),
      ...(fa?.engagement_highlights?.map(h => h.observation) ?? []),
      ...(analysis.engagement_highlights?.map(h => h.observation) ?? []),
      ...(ca?.key_moments?.map(m => m.description) ?? []),
      ...(analysis.key_moments?.map(m => m.description) ?? []),
    ].filter((s): s is string => Boolean(s));
    translate(strings);
  }, [language, analysis, translate]);

  useEffect(() => {
    const handler = () => {
      if (!analysis) return;
      downloadAnalysisPDF(analysis, session?.subject ?? "", session?.grade ?? "", language);
    };
    window.addEventListener("classroom-brain:download_pdf", handler);
    return () => window.removeEventListener("classroom-brain:download_pdf", handler);
  }, [analysis, session, language]);

  if (audioLoading || outputsLoading) return <LoadingScreen label="Loading class data…" />;

  const recordings = audioData?.recordings ?? [];
  const transcribedRecordings = recordings.filter((r) => r.transcribed);
  const hasAudio = transcribedRecordings.length > 0;
  const totalDurationSec = recordings.reduce((sum, r) => sum + (r.duration_sec ?? 0), 0);
  const totalSegments = recordings.reduce((sum, r) => sum + (r.segments?.length ?? 0), 0);
  const isProcessing = analysisOutput?.status === "processing" || analysing;
  const rawEngagement = audioData?.engagement ?? null;

  // Determine if we have the new source-split format
  const isNewFormat = !!(analysis?.from_board || analysis?.complete_analysis);

  return (
    <div className="space-y-5">

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Classroom Snapshot</h1>
          <p className="text-sm text-slate-500 mt-0.5">Your classroom memory from today's session</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <LanguageSelector value={language} onChange={setLanguage} translating={translating} />
          {analysis && (
            <button
              onClick={() => downloadAnalysisPDF(analysis, session?.subject ?? "", session?.grade ?? "", language)}
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 shadow-sm transition-colors"
            >
              <Download className="h-3.5 w-3.5" /> Download PDF
            </button>
          )}
        </div>
      </div>

      {/* No audio yet */}
      {recordings.length === 0 && !analysis && !isProcessing && (
        <Card>
          <CardContent className="flex flex-col items-center gap-4 py-12 text-center">
            <Mic className="h-14 w-14 text-slate-200" />
            <div>
              <p className="text-base font-semibold text-slate-700">No audio recording</p>
              <p className="mt-1 text-sm text-slate-500 max-w-sm mx-auto">
                Analysis will use board content only — topics inferred from what was written on the board.
              </p>
            </div>
            <div className="flex gap-3">
              <Link href={`/sessions/${sessionId}/capture`}>
                <Button variant="secondary" size="sm">Go to Capture <ChevronRight className="h-3.5 w-3.5" /></Button>
              </Link>
              <Button onClick={handleAnalyse} size="sm">
                <Cpu className="h-3.5 w-3.5" /> Review Board Content
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* One or more recordings failed transcription — offer retry for each */}
      {recordings.some((r) => !r.transcribed) && !isProcessing && (
        <Card>
          <CardContent className="py-6 space-y-4">
            <div className="flex items-center gap-3">
              <AlertTriangle className="h-5 w-5 text-amber-500 shrink-0" />
              <div>
                <p className="text-sm font-semibold text-slate-800">
                  {hasAudio ? "Some recordings are not transcribed" : "Transcription not available"}
                </p>
                <p className="text-xs text-slate-500 mt-0.5">
                  {recordings.filter((r) => !r.transcribed).length} of {recordings.length} recording(s) missing a
                  transcript — analysis will only use the transcribed ones until these are retried.
                </p>
              </div>
            </div>
            <div className="space-y-2">
              {recordings.filter((r) => !r.transcribed).map((rec) => (
                <div key={rec.audio_id} className="flex items-center justify-between rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
                  <span className="text-xs text-slate-600">
                    {rec.source === "video" ? "Video" : "Audio"} #{rec.recording_number}
                    {rec.duration_sec ? ` · ${Math.round(rec.duration_sec)}s` : ""}
                  </span>
                  <button
                    onClick={() => handleRetryTranscription(rec.audio_id)}
                    disabled={retryingAudioId === rec.audio_id}
                    className="rounded-md bg-indigo-600 px-3 py-1 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-60"
                  >
                    {retryingAudioId === rec.audio_id ? "Retrying…" : "Retry"}
                  </button>
                </div>
              ))}
            </div>
            <div className="pt-2 border-t border-slate-100 flex items-center justify-between">
              <p className="text-xs text-slate-500">Or analyse using board content only</p>
              <Button onClick={handleAnalyse} size="sm" variant="secondary">
                <Cpu className="h-3.5 w-3.5" /> Review Board Content
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Audio transcribed, not yet analysed */}
      {hasAudio && !analysis && !isProcessing && (
        <div className="space-y-4">
          <Card>
            <CardContent className="py-8 flex flex-col items-center gap-4 text-center">
              <CheckCircle2 className="h-12 w-12 text-green-500" />
              <div>
                <p className="text-base font-semibold text-slate-800">
                  {transcribedRecordings.length} recording{transcribedRecordings.length > 1 ? "s" : ""} transcribed
                </p>
                <p className="text-sm text-slate-500 mt-1">
                  {totalDurationSec > 0 ? `${Math.round(totalDurationSec / 60)} min total · ` : ""}{totalSegments} segments detected
                </p>
              </div>
              <Button onClick={handleAnalyse}>
                <Cpu className="h-4 w-4" /> Review Today's Class
              </Button>
            </CardContent>
          </Card>
          {rawEngagement && rawEngagement.engagement_curve.length > 0 && (
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2 text-sm">
                <Activity className="h-4 w-4 text-indigo-500" /> Engagement Preview
                <span className="ml-auto text-xs font-normal text-slate-400">
                  {Math.round(rawEngagement.silence_ratio * 100)}% silence · {Math.round(rawEngagement.speech_density_wpm)} wpm
                </span>
              </CardTitle></CardHeader>
              <CardContent>
                <EngagementTimeline curve={rawEngagement.engagement_curve} />
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* Processing */}
      {isProcessing && (
        <Card>
          <CardContent className="flex items-center justify-center gap-3 py-12 text-indigo-600">
            <BarChart3 className="h-6 w-6 animate-pulse" />
            <span className="font-medium">Reviewing your classroom…</span>
          </CardContent>
        </Card>
      )}

      {/* ── Analysis results ── */}
      {analysis && (
        <div className="space-y-4">

          {/* ── Source 1: Board Frames ── */}
          <Card>
            <CardContent className="pt-5">
              <SourceHeader
                icon={<Camera className="h-4 w-4" />}
                title="From Board Frames"
                available={true}
                subtitle={isNewFormat && analysis.from_board
                  ? `${analysis.from_board.frames_analysed} frame${analysis.from_board.frames_analysed !== 1 ? "s" : ""} analysed`
                  : undefined}
              />
              {isNewFormat && analysis.from_board && (
                <div className="space-y-3">
                  {analysis.from_board.board_summary && (
                    <p className="rounded-lg bg-slate-50 border border-slate-100 px-4 py-3 text-sm text-slate-700 leading-relaxed">
                      {t(analysis.from_board.board_summary)}
                    </p>
                  )}
                  {analysis.from_board.topics.length > 0 && (
                    <div>
                      <p className="text-[0.6875rem] font-semibold text-slate-400 uppercase tracking-wide mb-2">Topics detected on board</p>
                      <div className="flex flex-wrap gap-1.5">
                        {analysis.from_board.topics.map((topic, i) => (
                          <span key={i} className="rounded-full bg-indigo-50 border border-indigo-100 px-2.5 py-0.5 text-xs text-indigo-700">
                            {t(topic)}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
              {/* Fallback for old format */}
              {!isNewFormat && analysis.topics_spoken && (
                <div className="flex flex-wrap gap-1.5">
                  {analysis.topics_spoken.map((ts, i) => (
                    <span key={i} className="rounded-full bg-indigo-50 border border-indigo-100 px-2.5 py-0.5 text-xs text-indigo-700">{t(ts.topic)}</span>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* ── Source 2: Audio Recording ── */}
          <Card>
            <CardContent className="pt-5">
              <SourceHeader
                icon={<Mic className="h-4 w-4" />}
                title="From Audio Recording"
                available={isNewFormat ? (analysis.from_audio?.available ?? false) : hasAudio}
                subtitle={
                  hasAudio && totalDurationSec > 0
                    ? `${Math.round(totalDurationSec / 60)} min · ${totalSegments} segments`
                    : undefined
                }
              />
              {isNewFormat && analysis.from_audio ? (
                <div className="space-y-4">
                  {analysis.from_audio.audio_summary && (
                    <p className="rounded-lg bg-slate-50 border border-slate-100 px-4 py-3 text-sm text-slate-700 leading-relaxed">
                      {t(analysis.from_audio.audio_summary)}
                    </p>
                  )}
                  {analysis.from_audio.available && (
                    <>
                      {analysis.from_audio.pacing && (
                        <div className="flex items-center gap-2">
                          <PacingBadge rating={analysis.from_audio.pacing.rating} />
                          <p className="text-xs text-slate-500 leading-snug max-w-xs">
                            {t(analysis.from_audio.pacing.explanation)}
                          </p>
                        </div>
                      )}
                      {analysis.from_audio.topics_spoken.length > 0 && (
                        <div>
                          <p className="text-[0.6875rem] font-semibold text-slate-400 uppercase tracking-wide mb-2">
                            Topics spoken ({analysis.from_audio.topics_spoken.length})
                          </p>
                          <div className="space-y-2">
                            {analysis.from_audio.topics_spoken.map((ts, i) => (
                              <div key={i} className="rounded-lg bg-green-50 border border-green-100 px-3 py-2">
                                <p className="text-xs font-semibold text-green-800">{t(ts.topic)}</p>
                                {ts.evidence && <p className="mt-0.5 text-[0.6875rem] text-green-600 italic">"{t(ts.evidence)}"</p>}
                                {ts.approximate_time && <p className="mt-0.5 text-[0.625rem] text-green-400">{ts.approximate_time}</p>}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                      {analysis.from_audio.questions_detected.length > 0 && (
                        <div>
                          <p className="text-[0.6875rem] font-semibold text-slate-400 uppercase tracking-wide mb-2">
                            Questions detected ({analysis.from_audio.questions_detected.length})
                          </p>
                          <div className="space-y-1.5">
                            {analysis.from_audio.questions_detected.map((q, i) => (
                              <div key={i} className="flex items-start gap-2 rounded-lg bg-slate-50 border border-slate-100 px-3 py-2">
                                <MessageSquare className="h-3.5 w-3.5 mt-0.5 shrink-0 text-indigo-400" />
                                <div>
                                  <p className="text-xs text-slate-700">{t(q.question)}</p>
                                  <p className="text-[0.625rem] text-slate-400">{q.approximate_time} · {q.answered ? "answered" : "unanswered"}</p>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                      {analysis.from_audio.engagement_highlights.length > 0 && rawEngagement && (
                        <div>
                          <p className="text-[0.6875rem] font-semibold text-slate-400 uppercase tracking-wide mb-2">Engagement timeline</p>
                          <EngagementTimeline curve={rawEngagement.engagement_curve} />
                          <div className="mt-2 space-y-1">
                            {analysis.from_audio.engagement_highlights.map((h, i) => (
                              <div key={i} className="flex items-start gap-2 text-xs text-slate-600">
                                <span className={h.type === "high" ? "text-green-500" : h.type === "low" ? "text-amber-500" : "text-indigo-400"}>
                                  {h.type === "high" ? "▲" : h.type === "low" ? "▼" : "●"}
                                </span>
                                <span><strong className="text-slate-700">Min {h.minute}:</strong> {t(h.observation)}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </div>
              ) : (
                /* Legacy flat format fallback */
                <div className="space-y-3">
                  {analysis.pacing && (
                    <div className="flex items-center gap-2">
                      <PacingBadge rating={analysis.pacing.rating} />
                      <p className="text-xs text-slate-500">{t(analysis.pacing.explanation)}</p>
                    </div>
                  )}
                  {rawEngagement && rawEngagement.engagement_curve.length > 0 && (
                    <EngagementTimeline curve={rawEngagement.engagement_curve} />
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          {/* ── Source 3: Audience Analysis ── */}
          <Card>
            <CardContent className="pt-5">
              <SourceHeader
                icon={<Users className="h-4 w-4" />}
                title="From Audience Analysis"
                available={isNewFormat
                  ? (analysis.from_audience?.available ?? false)
                  : !!(audienceData && (audienceData.minute_count ?? 0) > 0)}
                subtitle={
                  audienceData && (audienceData.minute_count ?? 0) > 0
                    ? `${audienceData.minute_count} min · avg ${audienceData.avg_attention_pct?.toFixed(0)}% attentive`
                    : undefined
                }
              />
              {isNewFormat && analysis.from_audience ? (
                <div>
                  {analysis.from_audience.audience_summary && (
                    <p className="rounded-lg bg-slate-50 border border-slate-100 px-4 py-3 text-sm text-slate-700 leading-relaxed">
                      {t(analysis.from_audience.audience_summary)}
                    </p>
                  )}
                  {analysis.from_audience.available && audienceData && (audienceData.minute_count ?? 0) > 0 && (
                    <div className="mt-3">
                      <div className="flex items-end gap-0.5 h-16">
                        {audienceData.metrics.map((m) => (
                          <div
                            key={m.minute_number}
                            className="flex-1 rounded-sm min-w-0"
                            style={{
                              height: `${Math.max(4, m.attention_pct)}%`,
                              backgroundColor: m.attention_pct >= 70 ? "#10b981" : m.attention_pct >= 40 ? "#f59e0b" : "#ef4444",
                            }}
                            title={`Min ${m.minute_number}: ${m.attention_pct.toFixed(0)}% attentive`}
                          />
                        ))}
                      </div>
                      <div className="flex justify-between text-[0.625rem] text-slate-400 mt-1">
                        <span>Min 1</span><span>Attention %</span><span>Min {audienceData.minute_count}</span>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                audienceData && (audienceData.minute_count ?? 0) > 0 ? (
                  <div>
                    <div className="flex items-end gap-0.5 h-16">
                      {audienceData.metrics.map((m) => (
                        <div
                          key={m.minute_number}
                          className="flex-1 rounded-sm min-w-0"
                          style={{
                            height: `${Math.max(4, m.attention_pct)}%`,
                            backgroundColor: m.attention_pct >= 70 ? "#10b981" : m.attention_pct >= 40 ? "#f59e0b" : "#ef4444",
                          }}
                          title={`Min ${m.minute_number}: ${m.attention_pct.toFixed(0)}%`}
                        />
                      ))}
                    </div>
                    <p className="text-xs text-slate-400 mt-1.5">Avg {audienceData.avg_attention_pct?.toFixed(0)}% attention</p>
                  </div>
                ) : (
                  <p className="text-xs text-slate-400">Enable audience mode during recording to track student attention.</p>
                )
              )}
            </CardContent>
          </Card>

          {/* ── Source 4: Video Recording ── */}
          <Card>
            <CardContent className="pt-5">
              {(() => {
                const videoRecs = recordings.filter(r => r.source === "video");
                const fromVideo = analysis.from_video;
                const hasVideoData = isNewFormat ? fromVideo?.available : videoRecs.length > 0;
                return (
                  <>
                    <SourceHeader
                      icon={<Video className="h-4 w-4" />}
                      title="From Video Recording"
                      available={!!hasVideoData}
                      subtitle={videoRecs.length > 0
                        ? `${videoRecs.length} recording${videoRecs.length !== 1 ? "s" : ""} · frames + audio extracted`
                        : undefined}
                    />
                    {isNewFormat && fromVideo ? (
                      <div className="space-y-3">
                        {fromVideo.video_summary && (
                          <p className="rounded-lg bg-slate-50 border border-slate-100 px-4 py-3 text-sm text-slate-700 leading-relaxed">
                            {t(fromVideo.video_summary)}
                          </p>
                        )}
                        {fromVideo.available && (
                          <div className="flex gap-4">
                            <div className="rounded-lg bg-indigo-50 border border-indigo-100 px-3 py-2">
                              <p className="text-[0.625rem] text-indigo-400 uppercase tracking-wide">Frames extracted</p>
                              <p className="text-sm font-bold text-indigo-700">{fromVideo.frames_extracted}</p>
                            </div>
                            <div className="rounded-lg bg-indigo-50 border border-indigo-100 px-3 py-2">
                              <p className="text-[0.625rem] text-indigo-400 uppercase tracking-wide">Audio transcribed</p>
                              <p className="text-sm font-bold text-indigo-700">{fromVideo.audio_transcribed ? "Yes" : "No"}</p>
                            </div>
                          </div>
                        )}
                      </div>
                    ) : (
                      videoRecs.length > 0 ? (
                        <div className="space-y-2">
                          {videoRecs.map((rec) => (
                            <div key={rec.audio_id} className="rounded-lg bg-slate-50 border border-slate-100 px-3 py-2 text-xs text-slate-600">
                              Video #{rec.recording_number}
                              {rec.duration_sec ? ` · ${Math.round(rec.duration_sec)}s` : ""}
                              {rec.transcribed ? " · transcribed ✓" : ""}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-slate-400">No video recording for this session. Record video from the Capture page.</p>
                      )
                    )}
                  </>
                );
              })()}
            </CardContent>
          </Card>

          {/* ── Complete Analysis ── */}
          <Card className="border-indigo-200">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base text-indigo-700">
                <ScanLine className="h-4 w-4" /> Complete Analysis
                <span className="ml-auto text-[0.6875rem] font-normal text-slate-400">
                  {(analysisOutput?.tokens_used ?? 0) > 0 ? `${analysisOutput!.tokens_used.toLocaleString()} tokens` : ""}
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Summary */}
              {(() => {
                const summary = isNewFormat
                  ? analysis.complete_analysis?.summary
                  : analysis.summary;
                return summary ? (
                  <p className="rounded-xl bg-indigo-50 border border-indigo-100 px-4 py-3 text-sm text-indigo-900 leading-relaxed">
                    {t(summary)}
                  </p>
                ) : null;
              })()}

              {/* Cross-source topic gaps */}
              {isNewFormat && analysis.complete_analysis && (
                <>
                  {(analysis.complete_analysis.topics_on_board_not_spoken.length > 0 ||
                    analysis.complete_analysis.topics_spoken_not_on_board.length > 0) && (
                    <div className="grid gap-3 md:grid-cols-2">
                      {analysis.complete_analysis.topics_on_board_not_spoken.length > 0 && (
                        <div>
                          <p className="text-[0.6875rem] font-semibold text-amber-600 uppercase tracking-wide mb-2">
                            On board, not spoken ({analysis.complete_analysis.topics_on_board_not_spoken.length})
                          </p>
                          <div className="space-y-1">
                            {analysis.complete_analysis.topics_on_board_not_spoken.map((topic, i) => (
                              <div key={i} className="rounded-lg bg-amber-50 border border-amber-100 px-3 py-1.5">
                                <p className="text-xs text-amber-800">{t(topic)}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                      {analysis.complete_analysis.topics_spoken_not_on_board.length > 0 && (
                        <div>
                          <p className="text-[0.6875rem] font-semibold text-indigo-600 uppercase tracking-wide mb-2">
                            Spoken, not on board ({analysis.complete_analysis.topics_spoken_not_on_board.length})
                          </p>
                          <div className="space-y-1">
                            {analysis.complete_analysis.topics_spoken_not_on_board.map((topic, i) => (
                              <div key={i} className="rounded-lg bg-indigo-50 border border-indigo-100 px-3 py-1.5">
                                <p className="text-xs text-indigo-800">{t(topic)}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Key moments */}
                  {analysis.complete_analysis.key_moments.length > 0 && (
                    <div>
                      <p className="text-[0.6875rem] font-semibold text-slate-400 uppercase tracking-wide mb-2">Key moments</p>
                      <div className="space-y-1.5">
                        {analysis.complete_analysis.key_moments.map((m, i) => (
                          <div key={i} className="flex items-start gap-2 text-sm">
                            <Clock className="h-3.5 w-3.5 mt-0.5 shrink-0 text-slate-400" />
                            <div>
                              <p className="text-slate-700">{t(m.description)}</p>
                              <p className="text-[0.6875rem] text-slate-400">{m.approximate_time}</p>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}

              {/* Legacy format fallbacks */}
              {!isNewFormat && (
                <>
                  {analysis.pacing && (
                    <div className="flex items-center gap-2">
                      <PacingBadge rating={analysis.pacing.rating} />
                      <p className="text-xs text-slate-500">{t(analysis.pacing.explanation)}</p>
                    </div>
                  )}
                  {(analysis.key_moments ?? []).length > 0 && (
                    <div className="space-y-1.5">
                      {(analysis.key_moments ?? []).map((m, i) => (
                        <div key={i} className="flex items-start gap-2 text-sm">
                          <Clock className="h-3.5 w-3.5 mt-0.5 shrink-0 text-slate-400" />
                          <div>
                            <p className="text-slate-700">{t(m.description)}</p>
                            <p className="text-[0.6875rem] text-slate-400">{m.approximate_time}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}

              {/* Suggestions */}
              {(() => {
                const suggestions = isNewFormat
                  ? analysis.complete_analysis?.suggestions
                  : analysis.suggestions;
                return suggestions ? (
                  <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
                    <Lightbulb className="h-4 w-4 shrink-0 text-amber-500 mt-0.5" />
                    <p className="text-sm text-amber-800 leading-relaxed">{t(suggestions)}</p>
                  </div>
                ) : null;
              })()}
            </CardContent>
          </Card>

        </div>
      )}
    </div>
  );
}
