"use client";

import { use, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import {
  BookOpen, Upload, CheckCircle2, AlertTriangle, XCircle,
  Loader2, RefreshCw, Lightbulb, Target, FileText, BarChart3, Download,
} from "lucide-react";
import { api, type LessonPlan, type LessonPlanCoverage } from "@/lib/api";
import { fetchOutputsCached } from "@/lib/cached-fetchers";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { LoadingScreen } from "@/components/ui/Spinner";
import { LanguageSelector } from "@/components/ui/LanguageSelector";
import { useTranslation } from "@/hooks/useTranslation";

// ─── Coverage score ring ───────────────────────────────────────────────────────

function CoverageRing({ score }: { score: number }) {
  const pct = Math.min(100, Math.max(0, score));
  const r = 38;
  const circ = 2 * Math.PI * r;
  const dash = (pct / 100) * circ;
  const colour = pct >= 70 ? "#10b981" : pct >= 40 ? "#f59e0b" : "#ef4444";
  const label = pct >= 70 ? "Good" : pct >= 40 ? "Partial" : "Low";

  return (
    <div className="flex flex-col items-center gap-2">
      <svg width={92} height={92} className="-rotate-90">
        <circle cx={46} cy={46} r={r} fill="none" stroke="#e2e8f0" strokeWidth={7} />
        <circle
          cx={46} cy={46} r={r} fill="none"
          stroke={colour} strokeWidth={7}
          strokeDasharray={`${dash} ${circ}`}
          strokeLinecap="round"
        />
      </svg>
      <div className="text-center -mt-2">
        <p className="text-2xl font-extrabold" style={{ color: colour }}>{pct}%</p>
        <p className="text-xs text-slate-500 font-medium">{label} Coverage</p>
        <p className="text-[0.6875rem] text-slate-400">Lesson Plan vs Board</p>
      </div>
    </div>
  );
}

// ─── Upload zone ───────────────────────────────────────────────────────────────

function UploadZone({
  onFile,
  loading,
}: {
  onFile: (f: File) => void;
  loading: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDrag(false);
    const f = e.dataTransfer.files?.[0];
    if (f) onFile(f);
  }

  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={handleDrop}
      className={`
        flex flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed
        cursor-pointer transition-colors p-12 text-center
        ${drag ? "border-indigo-400 bg-indigo-50" : "border-slate-300 bg-slate-50 hover:bg-slate-100"}
      `}
    >
      {loading ? (
        <Loader2 className="h-12 w-12 text-indigo-500 animate-spin" />
      ) : (
        <Upload className="h-12 w-12 text-slate-400" />
      )}
      <div>
        <p className="font-semibold text-slate-700">
          {loading ? "Extracting topics…" : "Upload Lesson Plan"}
        </p>
        <p className="text-xs text-slate-500 mt-1">PDF, JPEG, or PNG · max 20 MB</p>
      </div>
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
    </div>
  );
}

// ─── Topic chip list ───────────────────────────────────────────────────────────

function TopicChips({ topics, colour }: { topics: string[]; colour: "slate" | "green" | "amber" | "red" }) {
  const cls = {
    slate:  "bg-slate-100 text-slate-700",
    green:  "bg-emerald-100 text-emerald-700",
    amber:  "bg-amber-100 text-amber-700",
    red:    "bg-red-100 text-red-700",
  }[colour];
  return (
    <div className="flex flex-wrap gap-2">
      {topics.map((t, i) => (
        <span key={i} className={`rounded-full px-3 py-1 text-xs font-medium ${cls}`}>{t}</span>
      ))}
    </div>
  );
}

// ─── PDF export ───────────────────────────────────────────────────────────────

function downloadCoveragePDF(coverage: LessonPlanCoverage, subject: string, language: string) {
  const langNote = language !== "english" ? ` · ${language.charAt(0).toUpperCase() + language.slice(1)}` : "";
  const pct = coverage.coverage_score ?? 0;
  const colour = pct >= 70 ? "#10b981" : pct >= 40 ? "#f59e0b" : "#ef4444";

  const topicRow = (cls: string, label: string, icon: string, items: { topic: string; sub?: string }[]) =>
    items.length === 0 ? "" : `
    <div class="section">
      <div class="section-title">${icon} ${label} (${items.length})</div>
      ${items.map(it => `<div class="item ${cls}"><strong>${it.topic}</strong>${it.sub ? `<div style="font-size:12px;margin-top:3px">${it.sub}</div>` : ""}</div>`).join("")}
    </div>`;

  const html = `<!DOCTYPE html><html><head><meta charset="UTF-8"/><title>Lesson Plan Coverage${langNote}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Sans:wght@400;600;700&family=Noto+Sans+Devanagari:wght@400;600;700&family=Noto+Sans+Kannada:wght@400;600;700&family=Noto+Sans+Telugu:wght@400;600;700&family=Noto+Sans+Tamil:wght@400;600;700&display=swap');
  body{font-family:'Noto Sans',Arial,sans-serif;max-width:760px;margin:0 auto;padding:32px 40px;color:#1e293b;font-size:14px}
  h1{font-size:20px;color:#312e81;margin:0 0 4px}
  .meta{font-size:12px;color:#64748b;margin-bottom:28px;border-bottom:2px solid #6366f1;padding-bottom:12px}
  .score-ring{text-align:center;margin-bottom:24px}
  .score-val{font-size:36px;font-weight:900}
  .section{margin-bottom:20px}
  .section-title{font-size:14px;font-weight:700;color:#4338ca;border-left:4px solid #6366f1;padding-left:8px;margin:0 0 8px}
  .item{padding:8px 12px;border-radius:6px;margin-bottom:6px;font-size:13px}
  .covered{background:#ecfdf5;border:1px solid #86efac;color:#065f46}
  .partial{background:#fffbeb;border:1px solid #fde68a;color:#78350f}
  .missing{background:#fef2f2;border:1px solid #fca5a5;color:#7f1d1d}
  .summary{background:#f0f4ff;border:1px solid #c7d2fe;border-radius:8px;padding:14px;font-size:13px;color:#3730a3;line-height:1.7;margin-bottom:20px}
  .footer{margin-top:28px;padding-top:10px;border-top:1px solid #e2e8f0;font-size:11px;color:#94a3b8;text-align:center}
  @media print{body{padding:16px}}
</style></head><body>
<h1>${subject || "Lesson Plan"} — Coverage Report${langNote}</h1>
<div class="meta">Drishti</div>
<div class="score-ring"><div class="score-val" style="color:${colour}">${pct}%</div><div style="color:#64748b;font-size:13px">Coverage Score</div></div>
${coverage.summary ? `<div class="summary">${coverage.summary}</div>` : ""}
${topicRow("covered", "Covered", "✅", (coverage.covered ?? []).map(c => ({ topic: c.topic, sub: c.evidence })))}
${topicRow("partial", "Partially Covered", "⚠️", (coverage.partial ?? []).map(p => ({ topic: p.topic, sub: [p.covered_aspect ? `✓ ${p.covered_aspect}` : "", p.missing_aspect ? `✗ ${p.missing_aspect}` : ""].filter(Boolean).join("<br>") })))}
${topicRow("missing", "Missing", "❌", (coverage.missing ?? []).map(m => ({ topic: m })))}
${coverage.suggestions ? `<div class="section"><div class="section-title">💡 Suggestions</div><div class="summary" style="background:#fffbeb;border-color:#fde68a;color:#78350f">${coverage.suggestions}</div></div>` : ""}
<div class="footer">Generated by Drishti</div>
</body></html>`;

  const win = window.open("", "_blank");
  if (!win) return;
  win.document.write(html);
  win.document.close();
  win.focus();
  setTimeout(() => { win.print(); }, 400);
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function LessonPlanPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  const [uploading, setUploading] = useState(false);
  const [analysing, setAnalysing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { language, setLanguage, translating, translate, t } = useTranslation();

  // Fetch existing lesson plan (null = not uploaded yet)
  const {
    data: plan,
    isLoading: planLoading,
    mutate: mutatePlan,
  } = useSWR(
    ["lesson-plan", sessionId],
    async () => {
      try {
        return await api.getLessonPlan(sessionId);
      } catch {
        return null;
      }
    },
    { revalidateOnFocus: false }
  );

  // Poll outputs for coverage result
  const { data: outputs, isLoading: outputsLoading, mutate: mutateOutputs } = useSWR(
    ["outputs", sessionId],
    () => fetchOutputsCached(sessionId),
    { refreshInterval: analysing ? 5000 : 0 }
  );

  const coverageOutput = outputs?.outputs?.lesson_plan_coverage;
  const coverageData = coverageOutput?.data as LessonPlanCoverage | undefined;
  const isProcessing = coverageOutput?.status === "processing" || coverageOutput?.status === "pending";

  // Stop polling once done
  useEffect(() => {
    if (analysing && coverageOutput?.status === "ready") {
      setAnalysing(false);
    }
  }, [analysing, coverageOutput?.status]);

  async function handleUpload(file: File) {
    setError(null);
    setUploading(true);
    try {
      const updated = await api.uploadLessonPlan(sessionId, file);
      await mutatePlan(updated as LessonPlan, false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleAnalyse() {
    setError(null);
    setAnalysing(true);
    try {
      await api.triggerGeneration(sessionId, ["lesson_plan_coverage"]);
      await mutateOutputs();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to start analysis");
      setAnalysing(false);
    }
  }

  const { data: session } = useSWR(["session", sessionId], () => api.getSession(sessionId), { revalidateOnFocus: false });

  const isLoading = planLoading || outputsLoading;

  // Collect and translate all AI-generated strings
  useEffect(() => {
    if (!coverageData && !plan) return;
    const strings = [
      ...(plan?.topics ?? []),
      coverageData?.summary,
      coverageData?.suggestions,
      ...(coverageData?.covered ?? []).flatMap(c => [c.topic, c.evidence]),
      ...(coverageData?.partial ?? []).flatMap(p => [p.topic, p.covered_aspect, p.missing_aspect]),
      ...(coverageData?.missing ?? []),
    ].filter((s): s is string => Boolean(s));
    translate(strings);
  }, [language, coverageData, plan, translate]);

  useEffect(() => {
    const handler = () => {
      if (!coverageData) return;
      const tCoverage: LessonPlanCoverage = {
        ...coverageData,
        summary: t(coverageData.summary),
        suggestions: t(coverageData.suggestions),
        covered: (coverageData.covered ?? []).map(c => ({ ...c, topic: t(c.topic), evidence: t(c.evidence) })),
        partial: (coverageData.partial ?? []).map(p => ({ ...p, topic: t(p.topic), covered_aspect: t(p.covered_aspect), missing_aspect: t(p.missing_aspect) })),
        missing: (coverageData.missing ?? []).map(m => t(m)),
      };
      downloadCoveragePDF(tCoverage, session?.subject ?? "", language);
    };
    window.addEventListener("classroom-brain:download_pdf", handler);
    return () => window.removeEventListener("classroom-brain:download_pdf", handler);
  }, [coverageData, session, language, t]);

  return (
    <div className="space-y-5">

      {/* ── Header ── */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white">
            <BookOpen className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-900">Lesson Plan Coverage</h1>
            <p className="text-xs text-slate-500 mt-0.5">
              Upload your lesson plan to check which topics were covered on the board
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <LanguageSelector value={language} onChange={setLanguage} translating={translating} />
          {coverageData && (
            <button
              onClick={() => {
                const tCoverage: LessonPlanCoverage = {
                  ...coverageData,
                  summary: t(coverageData.summary),
                  suggestions: t(coverageData.suggestions),
                  covered: (coverageData.covered ?? []).map(c => ({ ...c, topic: t(c.topic), evidence: t(c.evidence) })),
                  partial: (coverageData.partial ?? []).map(p => ({ ...p, topic: t(p.topic), covered_aspect: t(p.covered_aspect), missing_aspect: t(p.missing_aspect) })),
                  missing: (coverageData.missing ?? []).map(m => t(m)),
                };
                downloadCoveragePDF(tCoverage, session?.subject ?? "", language);
              }}
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 shadow-sm transition-colors"
            >
              <Download className="h-3.5 w-3.5" /> Download PDF
            </button>
          )}
        </div>
      </div>

      {isLoading && <LoadingScreen label="Loading lesson plan…" />}

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {/* ── State A: No plan uploaded ── */}
      {!isLoading && !plan && (
        <UploadZone onFile={handleUpload} loading={uploading} />
      )}

      {/* ── State B: Plan uploaded ── */}
      {!isLoading && plan && (
        <div className="space-y-5">

          {/* Plan summary row */}
          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-indigo-600" />
                  <CardTitle>Uploaded Lesson Plan</CardTitle>
                  <span className="ml-auto text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full font-bold capitalize">
                    {plan.file_type}
                  </span>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex items-center justify-between text-xs text-slate-500">
                  <span>{plan.topic_count} topic{plan.topic_count !== 1 ? "s" : ""} extracted</span>
                  {plan.updated_at && (
                    <span>Updated {new Date(plan.updated_at).toLocaleDateString()}</span>
                  )}
                </div>
                {plan.topics && plan.topics.length > 0 && (
                  <TopicChips topics={plan.topics.map(tp => t(tp))} colour="slate" />
                )}
                {(!plan.topics || plan.topics.length === 0) && (
                  <p className="text-xs text-slate-400 italic">No topics extracted — try re-uploading a clearer document.</p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <BarChart3 className="h-4 w-4 text-emerald-600" />
                  <CardTitle>Coverage Analysis</CardTitle>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {!coverageData && (
                  <>
                    <p className="text-sm text-slate-600">
                      Compare your lesson plan against the board content captured in this session.
                    </p>
                    <Button
                      onClick={handleAnalyse}
                      disabled={analysing || isProcessing || !plan.topics?.length}
                      className="w-full"
                    >
                      {(analysing || isProcessing) ? (
                        <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Analysing…</>
                      ) : (
                        "Analyse Coverage"
                      )}
                    </Button>
                    {!plan.topics?.length && (
                      <p className="text-xs text-amber-600">Upload a plan with extractable topics first.</p>
                    )}
                  </>
                )}
                {coverageData && (
                  <>
                    <div className="flex justify-center">
                      <CoverageRing score={coverageData.coverage_score} />
                    </div>
                    {coverageOutput && coverageOutput.tokens_used > 0 && (
                      <p className="text-center text-[0.6875rem] text-slate-400">
                        {coverageOutput.tokens_used.toLocaleString()} tokens used
                      </p>
                    )}
                    <Button
                      onClick={handleAnalyse}
                      disabled={analysing || isProcessing}
                      size="sm"
                      variant="secondary"
                      className="w-full"
                    >
                      <RefreshCw className="h-3.5 w-3.5 mr-1.5" /> Re-analyse
                    </Button>
                  </>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Re-upload row */}
          <div className="flex items-center gap-2">
            <p className="text-xs text-slate-400">Upload a different lesson plan?</p>
            <label className="cursor-pointer text-xs text-indigo-600 hover:underline font-medium">
              Replace file
              <input
                type="file"
                className="hidden"
                accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) handleUpload(f);
                  e.target.value = "";
                }}
              />
            </label>
            {uploading && <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-500" />}
          </div>

          {/* ── State C: Analysis results ── */}
          {coverageData && (
            <div className="space-y-4">

              {/* Summary card */}
              {coverageData.summary && (
                <Card>
                  <CardHeader>
                    <div className="flex items-center gap-2">
                      <BookOpen className="h-4 w-4 text-slate-600" />
                      <CardTitle>Analysis Summary</CardTitle>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm text-slate-700 leading-relaxed border-l-4 border-indigo-200 pl-3 italic">
                      {t(coverageData.summary)}
                    </p>
                  </CardContent>
                </Card>
              )}

              {/* Three-column breakdown */}
              <div className="grid gap-4 md:grid-cols-3">

                {/* Covered */}
                <Card>
                  <CardHeader>
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                      <CardTitle className="text-emerald-700">Covered</CardTitle>
                      <span className="ml-auto text-xs bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded-full font-bold">
                        {coverageData.covered?.length ?? 0}
                      </span>
                    </div>
                  </CardHeader>
                  <CardContent>
                    {!coverageData.covered?.length ? (
                      <p className="text-xs text-slate-400 italic">None detected.</p>
                    ) : (
                      <ul className="space-y-2">
                        {coverageData.covered.map((item, i) => (
                          <li key={i} className="rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2.5">
                            <p className="text-sm font-semibold text-emerald-800">{t(item.topic)}</p>
                            {item.evidence && (
                              <p className="text-xs text-emerald-600 mt-0.5 leading-relaxed">{t(item.evidence)}</p>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </CardContent>
                </Card>

                {/* Partial */}
                <Card>
                  <CardHeader>
                    <div className="flex items-center gap-2">
                      <AlertTriangle className="h-4 w-4 text-amber-500" />
                      <CardTitle className="text-amber-700">Partially Covered</CardTitle>
                      <span className="ml-auto text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-bold">
                        {coverageData.partial?.length ?? 0}
                      </span>
                    </div>
                  </CardHeader>
                  <CardContent>
                    {!coverageData.partial?.length ? (
                      <p className="text-xs text-slate-400 italic">None.</p>
                    ) : (
                      <ul className="space-y-2">
                        {coverageData.partial.map((item, i) => (
                          <li key={i} className="rounded-lg border border-amber-100 bg-amber-50 px-3 py-2.5">
                            <p className="text-sm font-semibold text-amber-800">{t(item.topic)}</p>
                            {item.covered_aspect && (
                              <p className="text-xs text-emerald-600 mt-0.5">✓ {t(item.covered_aspect)}</p>
                            )}
                            {item.missing_aspect && (
                              <p className="text-xs text-red-500 mt-0.5">✗ {t(item.missing_aspect)}</p>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </CardContent>
                </Card>

                {/* Missing */}
                <Card>
                  <CardHeader>
                    <div className="flex items-center gap-2">
                      <XCircle className="h-4 w-4 text-red-500" />
                      <CardTitle className="text-red-700">Missing</CardTitle>
                      <span className="ml-auto text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-bold">
                        {coverageData.missing?.length ?? 0}
                      </span>
                    </div>
                  </CardHeader>
                  <CardContent>
                    {!coverageData.missing?.length ? (
                      <p className="text-xs text-slate-400 italic">All planned topics were covered!</p>
                    ) : (
                      <ul className="space-y-2">
                        {coverageData.missing.map((topic, i) => (
                          <li key={i} className="rounded-lg border border-red-100 bg-red-50 px-3 py-2.5">
                            <p className="text-sm text-red-800">{t(topic)}</p>
                          </li>
                        ))}
                      </ul>
                    )}
                  </CardContent>
                </Card>
              </div>

              {/* Teaching notes for missing topics */}
              {(coverageData as any).teaching_notes?.length > 0 && (
                <Card className="border-amber-200 bg-amber-50/50">
                  <CardHeader>
                    <div className="flex items-center gap-2">
                      <FileText className="h-4 w-4 text-amber-600" />
                      <CardTitle className="text-amber-800">Teaching Notes for Missing Topics</CardTitle>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <ul className="space-y-3">
                      {(coverageData as any).teaching_notes.map((note: { topic: string; note: string }, i: number) => (
                        <li key={i} className="rounded-lg border border-amber-200 bg-white px-3 py-2.5">
                          <p className="text-sm font-semibold text-amber-900 mb-0.5">{note.topic}</p>
                          <p className="text-xs text-slate-600 leading-relaxed">{note.note}</p>
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              )}

              {/* Suggestions */}
              {coverageData.suggestions && (
                <Card className="bg-gradient-to-br from-indigo-50 to-purple-50 border-indigo-200">
                  <CardHeader>
                    <div className="flex items-center gap-2">
                      <Lightbulb className="h-4 w-4 text-indigo-600" />
                      <CardTitle className="text-indigo-700">Suggestions for Next Class</CardTitle>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm text-indigo-800 leading-relaxed">{t(coverageData.suggestions)}</p>
                  </CardContent>
                </Card>
              )}
            </div>
          )}

          {/* Processing state */}
          {(analysing || isProcessing) && !coverageData && (
            <div className="flex flex-col items-center gap-3 py-12 text-center">
              <Loader2 className="h-10 w-10 text-indigo-500 animate-spin" />
              <p className="text-sm font-medium text-slate-700">Analysing coverage against board scans…</p>
              <p className="text-xs text-slate-400">This usually takes 20–40 seconds.</p>
            </div>
          )}
        </div>
      )}

      {/* ── Footer ── */}
      {plan && (
        <div className="flex flex-wrap gap-3 pt-2 border-t border-slate-100">
          <Link href={`/sessions/${sessionId}`}>
            <Button size="sm" variant="secondary">
              <Target className="h-3.5 w-3.5 mr-1.5" /> Session Overview
            </Button>
          </Link>
          <Link href={`/sessions/${sessionId}/missing-concepts`}>
            <Button size="sm" variant="secondary">Gap Analysis →</Button>
          </Link>
        </div>
      )}
    </div>
  );
}
