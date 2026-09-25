"use client";

import { use, useEffect, useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import {
  AlertTriangle, BookOpen, ArrowRight, Lightbulb, Brain,
  CheckCircle2, Target, Zap, Shield, Layers, TrendingDown,
  Users, Award, ChevronDown, ChevronRight, Download,
} from "lucide-react";
import { api } from "@/lib/api";
import { fetchOutputsCached } from "@/lib/cached-fetchers";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { LoadingScreen } from "@/components/ui/Spinner";
import { Empty } from "@/components/ui/Empty";
import { cn } from "@/lib/utils";
import { LanguageSelector } from "@/components/ui/LanguageSelector";
import { useTranslation } from "@/hooks/useTranslation";

// ─── Types ─────────────────────────────────────────────────────────────────────

interface PedagogicalGaps {
  conceptual_gaps?: string[];
  sequencing_gaps?: string[];
  reinforcement_gaps?: string[];
  assessment_gaps?: string[];
  cognitive_depth_gaps?: string[];
  accessibility_gaps?: string[];
}

interface BloomAnalysis {
  distribution?: Record<string, number>;
  dominant_level?: string;
  higher_order_missing?: boolean;
}

interface ClassroomMetrics {
  concept_density?: string;
  explanation_depth?: string;
  example_density?: string;
  assessment_density?: string;
  curriculum_alignment_score?: number | null;
  instructional_balance_score?: number | null;
  progression_coherence_score?: number | null;
  learner_readiness_score?: number | null;
}

interface StudentRiskArea {
  concept: string;
  risk_level: "high" | "medium" | "low";
  reason: string;
}

interface GapData {
  // Legacy fields (always present)
  prerequisite_gaps?: string[];
  incomplete_topics?: string[];
  suggested_next?: string;
  // New rich fields
  session_summary?: string;
  topics_detected?: string[];
  concepts_covered?: string[];
  pedagogical_gaps?: PedagogicalGaps;
  bloom_analysis?: BloomAnalysis;
  classroom_metrics?: ClassroomMetrics;
  student_risk_areas?: StudentRiskArea[];
  missing_prerequisites?: string[];
  instructional_weaknesses?: string[];
  recommended_interventions?: string[];
  suggested_next_steps?: string[];
  remediation_plan?: string;
  teaching_effectiveness_score?: number | null;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const BLOOM_COLOURS: Record<string, string> = {
  remember:  "bg-slate-400",
  understand:"bg-blue-400",
  apply:     "bg-teal-500",
  analyze:   "bg-indigo-500",
  evaluate:  "bg-purple-500",
  create:    "bg-pink-500",
};

function BloomBars({ dist }: { dist: Record<string, number> }) {
  const keys = ["remember", "understand", "apply", "analyze", "evaluate", "create"];
  const total = keys.reduce((s, k) => s + (dist[k] ?? 0), 0) || 1;
  return (
    <div className="space-y-2">
      {keys.map((k) => {
        const val = dist[k] ?? 0;
        const pct = Math.round((val / total) * 100);
        return (
          <div key={k} className="flex items-center gap-2 text-xs">
            <span className="w-20 text-slate-500 capitalize text-right shrink-0">{k}</span>
            <div className="flex-1 h-2.5 bg-slate-100 rounded-full overflow-hidden">
              <div
                className={cn("h-full rounded-full transition-all duration-700", BLOOM_COLOURS[k])}
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="w-6 text-slate-500 text-right">{val}</span>
          </div>
        );
      })}
    </div>
  );
}

function RiskBadge({ level }: { level: string }) {
  const styles: Record<string, string> = {
    high:   "bg-red-100 text-red-700 border-red-200",
    medium: "bg-amber-100 text-amber-700 border-amber-200",
    low:    "bg-emerald-100 text-emerald-700 border-emerald-200",
  };
  return (
    <span className={cn("text-[0.6875rem] font-bold px-2 py-0.5 rounded-full border uppercase tracking-wide shrink-0", styles[level] ?? styles.medium)}>
      {level}
    </span>
  );
}

function MetricScore({ label, score }: { label: string; score: number | null | undefined }) {
  const val = score ?? 0;
  const colour = val >= 7 ? "text-emerald-600" : val >= 5 ? "text-amber-600" : "text-red-500";
  const bg = val >= 7 ? "bg-emerald-50 border-emerald-200" : val >= 5 ? "bg-amber-50 border-amber-200" : "bg-red-50 border-red-200";
  return (
    <div className={cn("flex flex-col items-center justify-center rounded-xl border p-3", bg)}>
      <span className={cn("text-2xl font-extrabold", colour)}>{val}<span className="text-sm font-normal">/10</span></span>
      <span className="text-[0.6875rem] text-slate-500 text-center mt-0.5 leading-tight">{label}</span>
    </div>
  );
}

function DensityBadge({ label, value }: { label: string; value: string }) {
  const styles: Record<string, string> = {
    high:   "bg-emerald-100 text-emerald-700",
    medium: "bg-amber-100 text-amber-700",
    low:    "bg-orange-100 text-orange-700",
    none:   "bg-red-100 text-red-600",
  };
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-slate-500">{label}</span>
      <span className={cn("px-2 py-0.5 rounded-full font-semibold capitalize", styles[value?.toLowerCase()] ?? "bg-slate-100 text-slate-500")}>
        {value || "—"}
      </span>
    </div>
  );
}

// ─── Collapsible gap section ──────────────────────────────────────────────────

interface GapSectionProps {
  icon: React.ReactNode;
  title: string;
  items: string[];
  colour: "red" | "amber" | "orange" | "blue" | "purple" | "slate";
  defaultOpen?: boolean;
}

const COLOUR_MAP = {
  red:    { header: "text-red-700",    bg: "bg-red-50",    border: "border-red-100",    dot: "bg-red-400",    count: "bg-red-100 text-red-700" },
  amber:  { header: "text-amber-700",  bg: "bg-amber-50",  border: "border-amber-100",  dot: "bg-amber-400",  count: "bg-amber-100 text-amber-700" },
  orange: { header: "text-orange-700", bg: "bg-orange-50", border: "border-orange-100", dot: "bg-orange-400", count: "bg-orange-100 text-orange-700" },
  blue:   { header: "text-blue-700",   bg: "bg-blue-50",   border: "border-blue-100",   dot: "bg-blue-400",   count: "bg-blue-100 text-blue-700" },
  purple: { header: "text-purple-700", bg: "bg-purple-50", border: "border-purple-100", dot: "bg-purple-400", count: "bg-purple-100 text-purple-700" },
  slate:  { header: "text-slate-700",  bg: "bg-slate-50",  border: "border-slate-100",  dot: "bg-slate-400",  count: "bg-slate-100 text-slate-600" },
};

function GapSection({ icon, title, items, colour, defaultOpen = false }: GapSectionProps) {
  const [open, setOpen] = useState(defaultOpen);
  const c = COLOUR_MAP[colour];
  if (!items || items.length === 0) return null;
  return (
    <div className={cn("rounded-xl border overflow-hidden", c.border)}>
      <button
        onClick={() => setOpen(!open)}
        className={cn("w-full flex items-center justify-between px-4 py-3 hover:opacity-80 transition-opacity", c.bg)}
      >
        <div className="flex items-center gap-2">
          <span className={c.header}>{icon}</span>
          <span className={cn("font-semibold text-sm", c.header)}>{title}</span>
          <span className={cn("text-[0.6875rem] font-bold px-2 py-0.5 rounded-full", c.count)}>
            {items.length}
          </span>
        </div>
        {open ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />}
      </button>
      {open && (
        <ul className="px-4 py-3 space-y-2 bg-white">
          {items.map((item, i) => (
            <li key={i} className="flex items-start gap-2.5">
              <span className={cn("h-2 w-2 rounded-full mt-1.5 shrink-0", c.dot)} />
              <span className="text-sm text-slate-700 leading-snug">{item}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ─── Effectiveness ring ───────────────────────────────────────────────────────

function EffectivenessRing({ score }: { score: number | null | undefined }) {
  const val = score ?? 0;
  const pct = Math.min(100, Math.max(0, val * 10));
  const r = 38;
  const circ = 2 * Math.PI * r;
  const dash = (pct / 100) * circ;
  const colour = pct >= 70 ? "#10b981" : pct >= 40 ? "#f59e0b" : "#ef4444";
  const label = pct >= 70 ? "Strong" : pct >= 40 ? "Developing" : "Needs Work";

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
        <p className="text-2xl font-extrabold" style={{ color: colour }}>{val.toFixed(1)}</p>
        <p className="text-xs text-slate-500 font-medium">{label}</p>
        <p className="text-[0.6875rem] text-slate-400">Teaching Effectiveness</p>
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function GapAnalysisPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  const { language, setLanguage, translating, translate, t } = useTranslation();

  const { data: outputs, isLoading } = useSWR(
    ["outputs", sessionId],
    () => fetchOutputsCached(sessionId),
    { refreshInterval: 15000 }
  );

  const mcOutput = outputs?.outputs?.missing_concepts;
  const mcData   = mcOutput?.data as GapData | undefined;

  // Detect whether we have the new rich format
  const isRichFormat = !!(mcData?.pedagogical_gaps || mcData?.teaching_effectiveness_score != null);

  // Legacy fields
  const legacyGaps      = mcData?.prerequisite_gaps ?? [];
  const legacyIncomplete = mcData?.incomplete_topics ?? [];
  const legacySuggested  = mcData?.suggested_next;

  // Rich fields
  const pg = mcData?.pedagogical_gaps ?? {};
  const allGapCount = [
    ...(pg.conceptual_gaps ?? []),
    ...(pg.sequencing_gaps ?? []),
    ...(pg.reinforcement_gaps ?? []),
    ...(pg.assessment_gaps ?? []),
    ...(pg.cognitive_depth_gaps ?? []),
    ...(pg.accessibility_gaps ?? []),
  ].length;

  const hasData = isRichFormat
    ? !!(mcData?.session_summary || allGapCount > 0 || mcData?.teaching_effectiveness_score != null)
    : legacyGaps.length > 0 || legacyIncomplete.length > 0 || legacySuggested;

  useEffect(() => {
    if (!mcData) return;
    const strings = [
      mcData.session_summary,
      mcData.remediation_plan,
      mcData.suggested_next,
      ...(mcData.topics_detected ?? []),
      ...(mcData.concepts_covered ?? []),
      ...(pg.conceptual_gaps ?? []),
      ...(pg.sequencing_gaps ?? []),
      ...(pg.reinforcement_gaps ?? []),
      ...(pg.assessment_gaps ?? []),
      ...(pg.cognitive_depth_gaps ?? []),
      ...(pg.accessibility_gaps ?? []),
      ...(mcData.student_risk_areas ?? []).flatMap(r => [r.concept, r.reason]),
      ...(mcData.missing_prerequisites ?? []),
      ...(mcData.instructional_weaknesses ?? []),
      ...(mcData.recommended_interventions ?? []),
      ...(mcData.suggested_next_steps ?? []),
      ...legacyGaps,
      ...legacyIncomplete,
      legacySuggested,
    ].filter((s): s is string => Boolean(s));
    translate(strings);
  }, [language, mcData, translate]);

  return (
    <div className="space-y-5">

      {/* ── Header ── */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-red-600 text-white">
            <Brain className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-900">Learning Opportunities</h1>
            <p className="text-xs text-slate-500 mt-0.5">
              Insights from similar classrooms to help plan your next lesson
            </p>
          </div>
        </div>
        {hasData && (
          <div className="flex items-center gap-2">
            <LanguageSelector value={language} onChange={setLanguage} translating={translating} />
            <button
              onClick={() => {
                const lines: string[] = [];
                if (mcData?.session_summary) lines.push(`Summary: ${t(mcData.session_summary)}`);
                const allGaps = [
                  ...(pg.conceptual_gaps ?? []),
                  ...(pg.sequencing_gaps ?? []),
                  ...(pg.reinforcement_gaps ?? []),
                  ...(pg.assessment_gaps ?? []),
                  ...(pg.cognitive_depth_gaps ?? []),
                  ...(pg.accessibility_gaps ?? []),
                ];
                if (allGaps.length) lines.push(`\nGaps:\n${allGaps.map(g => `• ${t(g)}`).join("\n")}`);
                if (mcData?.remediation_plan) lines.push(`\nRemediation Plan: ${t(mcData.remediation_plan)}`);
                const blob = new Blob([lines.join("\n")], { type: "text/plain" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a"); a.href = url; a.download = "gap-analysis.txt"; a.click();
                URL.revokeObjectURL(url);
              }}
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 shadow-sm transition-colors"
            >
              <Download className="h-3.5 w-3.5" /> Download
            </button>
          </div>
        )}
      </div>

      {isLoading && <LoadingScreen label="Analysing pedagogical gaps…" />}

      {!isLoading && !hasData && (
        <Empty
          icon={<Brain className="h-12 w-12" />}
          title="No gap analysis yet"
          description="Generate AI outputs to unlock the full pedagogical gap analysis report."
          action={
            <Link href={`/sessions/${sessionId}`}>
              <Button size="sm" variant="secondary">Generate AI Outputs →</Button>
            </Link>
          }
        />
      )}

      {/* ── RICH FORMAT ── */}
      {hasData && isRichFormat && (
        <div className="space-y-5">

          {/* Row 1: Session summary + Effectiveness score + Bloom */}
          <div className="grid gap-4 md:grid-cols-3">

            {/* Summary */}
            <Card className="md:col-span-2">
              <CardHeader>
                <div className="flex items-center gap-2">
                  <BookOpen className="h-4 w-4 text-slate-600" />
                  <CardTitle>Session Overview</CardTitle>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {mcData?.session_summary && (
                  <p className="text-sm text-slate-700 leading-relaxed border-l-4 border-red-200 pl-3 italic">
                    {t(mcData.session_summary)}
                  </p>
                )}
                {mcData?.topics_detected && mcData.topics_detected.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Topics Detected</p>
                    <div className="flex flex-wrap gap-2">
                      {mcData.topics_detected.map((topic, i) => (
                        <span key={i} className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">{t(topic)}</span>
                      ))}
                    </div>
                  </div>
                )}
                {mcData?.concepts_covered && mcData.concepts_covered.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Concepts Covered</p>
                    <div className="flex flex-wrap gap-2">
                      {mcData.concepts_covered.map((concept, i) => (
                        <span key={i} className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-medium text-emerald-700">✓ {t(concept)}</span>
                      ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* TEACHING SCORE — hidden, unlock when ready:
              <Card>
                <CardHeader><div className="flex items-center gap-2">
                  <Award className="h-4 w-4 text-amber-500" />
                  <CardTitle>Teaching Score</CardTitle>
                </div></CardHeader>
                <CardContent className="flex justify-center pt-2">
                  <EffectivenessRing score={mcData?.teaching_effectiveness_score} />
                </CardContent>
              </Card>
            */}
          </div>

          {/* Row 2: Classroom character (density badges only — numeric scores hidden) */}
          {mcData?.classroom_metrics && (
            <Card>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <TrendingDown className="h-4 w-4 text-indigo-600" />
                  <CardTitle>Classroom Character</CardTitle>
                </div>
              </CardHeader>
              <CardContent>
                {/* NUMERIC SCORES — hidden, unlock when ready:
                  <MetricScore label="Curriculum Alignment" score={mcData.classroom_metrics.curriculum_alignment_score} />
                  <MetricScore label="Instructional Balance" score={mcData.classroom_metrics.instructional_balance_score} />
                  <MetricScore label="Progression Coherence" score={mcData.classroom_metrics.progression_coherence_score} />
                  <MetricScore label="Learner Readiness" score={mcData.classroom_metrics.learner_readiness_score} />
                */}
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 text-xs">
                  <DensityBadge label="Concept Density" value={mcData.classroom_metrics.concept_density ?? ""} />
                  <DensityBadge label="Explanation Depth" value={mcData.classroom_metrics.explanation_depth ?? ""} />
                  <DensityBadge label="Example Density" value={mcData.classroom_metrics.example_density ?? ""} />
                  <DensityBadge label="Assessment Density" value={mcData.classroom_metrics.assessment_density ?? ""} />
                </div>
              </CardContent>
            </Card>
          )}

          {/* Row 3: Gap analysis accordion */}
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-red-600" />
                <CardTitle>Areas Worth Exploring</CardTitle>
                {allGapCount > 0 && (
                  <span className="ml-auto text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full font-bold">
                    {allGapCount} opportunities
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-400">Click any category to expand</p>
            </CardHeader>
            <CardContent className="space-y-2">
              <GapSection
                icon={<Brain className="h-4 w-4" />}
                title="Conceptual Gaps"
                items={(pg.conceptual_gaps ?? []).map(s => t(s))}
                colour="red"
                defaultOpen={true}
              />
              <GapSection
                icon={<Layers className="h-4 w-4" />}
                title="Sequencing Gaps"
                items={(pg.sequencing_gaps ?? []).map(s => t(s))}
                colour="amber"
              />
              <GapSection
                icon={<TrendingDown className="h-4 w-4" />}
                title="Reinforcement Gaps"
                items={(pg.reinforcement_gaps ?? []).map(s => t(s))}
                colour="orange"
              />
              <GapSection
                icon={<Target className="h-4 w-4" />}
                title="Assessment Gaps"
                items={(pg.assessment_gaps ?? []).map(s => t(s))}
                colour="blue"
              />
              <GapSection
                icon={<Zap className="h-4 w-4" />}
                title="Cognitive Depth Gaps"
                items={(pg.cognitive_depth_gaps ?? []).map(s => t(s))}
                colour="purple"
              />
              <GapSection
                icon={<Shield className="h-4 w-4" />}
                title="Learner Accessibility Gaps"
                items={(pg.accessibility_gaps ?? []).map(s => t(s))}
                colour="slate"
              />
            </CardContent>
          </Card>

          {/* Row 4: Bloom analysis */}
          {mcData?.bloom_analysis?.distribution && (
            <Card>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <Brain className="h-4 w-4 text-purple-600" />
                  <CardTitle>Bloom's Taxonomy Analysis</CardTitle>
                </div>
                {mcData.bloom_analysis.higher_order_missing && (
                  <span className="text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded-full font-medium">
                    Higher-order thinking missing
                  </span>
                )}
              </CardHeader>
              <CardContent className="grid md:grid-cols-2 gap-6">
                <div>
                  <BloomBars dist={mcData.bloom_analysis.distribution} />
                </div>
                <div className="space-y-2">
                  {mcData.bloom_analysis.dominant_level && (
                    <div className="rounded-lg bg-purple-50 border border-purple-100 p-3">
                      <p className="text-xs text-purple-600 font-semibold uppercase tracking-wide">Dominant Level</p>
                      <p className="text-base font-bold text-purple-800 capitalize mt-0.5">{mcData.bloom_analysis.dominant_level}</p>
                    </div>
                  )}
                  {mcData.bloom_analysis.higher_order_missing && (
                    <div className="rounded-lg bg-amber-50 border border-amber-100 p-3">
                      <p className="text-xs text-amber-700 font-medium">
                        ⚠️ Teaching is focused on lower-order thinking (recall &amp; understanding).
                        Add application, analysis, and evaluation questions.
                      </p>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Row 5: Student risk areas */}
          {mcData?.student_risk_areas && mcData.student_risk_areas.length > 0 && (
            <Card>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <Users className="h-4 w-4 text-red-600" />
                  <CardTitle>Student Learning Risk Areas</CardTitle>
                  <span className="ml-auto text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-bold">
                    {mcData.student_risk_areas.length} risks
                  </span>
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {mcData.student_risk_areas.map((r, i) => (
                    <div
                      key={i}
                      className="flex items-start gap-3 rounded-xl border border-slate-100 bg-white p-3 shadow-sm"
                    >
                      <RiskBadge level={r.risk_level} />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold text-slate-800">{t(r.concept)}</p>
                        <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">{t(r.reason)}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Row 6: Missing prerequisites + Areas for Growth */}
          <div className="grid gap-4 md:grid-cols-2">
            {mcData?.missing_prerequisites && mcData.missing_prerequisites.length > 0 && (
              <Card>
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="h-4 w-4 text-blue-600" />
                    <CardTitle className="text-blue-700">Missing Prerequisites</CardTitle>
                    <span className="ml-auto text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-medium">
                      {mcData.missing_prerequisites.length}
                    </span>
                  </div>
                </CardHeader>
                <CardContent>
                  <ul className="space-y-2">
                    {mcData.missing_prerequisites.map((p, i) => (
                      <li key={i} className="flex items-center gap-2.5 rounded-lg border border-blue-100 bg-blue-50 px-3 py-2.5">
                        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-200 text-[0.625rem] font-bold text-blue-700">{i+1}</span>
                        <span className="text-sm text-blue-800 leading-snug">{t(p)}</span>
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            )}

            {mcData?.instructional_weaknesses && mcData.instructional_weaknesses.length > 0 && (
              <Card>
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <TrendingDown className="h-4 w-4 text-orange-600" />
                    <CardTitle className="text-orange-700">Areas for Growth</CardTitle>
                    <span className="ml-auto text-xs bg-orange-100 text-orange-700 px-2 py-0.5 rounded-full font-medium">
                      {mcData.instructional_weaknesses.length}
                    </span>
                  </div>
                </CardHeader>
                <CardContent>
                  <ul className="space-y-2">
                    {mcData.instructional_weaknesses.map((w, i) => (
                      <li key={i} className="flex items-start gap-2.5 rounded-lg border border-orange-100 bg-orange-50 px-3 py-2.5">
                        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-orange-200 text-[0.625rem] font-bold text-orange-700 mt-0.5">{i+1}</span>
                        <span className="text-sm text-orange-800 leading-snug">{t(w)}</span>
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            )}
          </div>

          {/* Row 7: Recommended interventions + Next steps */}
          <div className="grid gap-4 md:grid-cols-2">
            {mcData?.recommended_interventions && mcData.recommended_interventions.length > 0 && (
              <Card>
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <Lightbulb className="h-4 w-4 text-emerald-600" />
                    <CardTitle className="text-emerald-700">Recommended Interventions</CardTitle>
                  </div>
                </CardHeader>
                <CardContent>
                  <ul className="space-y-2">
                    {mcData.recommended_interventions.map((r, i) => (
                      <li key={i} className="flex items-start gap-2.5 rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2.5">
                        <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0 mt-0.5" />
                        <span className="text-sm text-emerald-800 leading-snug">{t(r)}</span>
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            )}

            {mcData?.suggested_next_steps && mcData.suggested_next_steps.length > 0 && (
              <Card>
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <ArrowRight className="h-4 w-4 text-indigo-600" />
                    <CardTitle className="text-indigo-700">Suggested Next Steps</CardTitle>
                  </div>
                </CardHeader>
                <CardContent>
                  <ul className="space-y-2">
                    {mcData.suggested_next_steps.map((s, i) => (
                      <li key={i} className="flex items-start gap-2.5 rounded-lg border border-indigo-100 bg-indigo-50 px-3 py-2.5">
                        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-indigo-200 text-[0.625rem] font-bold text-indigo-700 mt-0.5">{i+1}</span>
                        <span className="text-sm text-indigo-800 leading-snug">{t(s)}</span>
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            )}
          </div>

          {/* Row 8: Remediation plan + suggested next topic */}
          <div className="grid gap-4 md:grid-cols-2">
            {mcData?.remediation_plan && (
              <Card className="md:col-span-1 bg-gradient-to-br from-indigo-50 to-purple-50 border-indigo-200">
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <Target className="h-4 w-4 text-indigo-600" />
                    <CardTitle className="text-indigo-700">Remediation Plan</CardTitle>
                  </div>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-indigo-800 leading-relaxed">{t(mcData.remediation_plan)}</p>
                </CardContent>
              </Card>
            )}

            {mcData?.suggested_next && (
              <Card className="bg-gradient-to-br from-emerald-50 to-teal-50 border-emerald-200">
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <ArrowRight className="h-4 w-4 text-emerald-600" />
                    <CardTitle className="text-emerald-700">Next Topic to Cover</CardTitle>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="flex items-center gap-3 rounded-xl bg-white/70 p-3">
                    <ArrowRight className="h-5 w-5 text-emerald-500 shrink-0" />
                    <p className="text-sm font-semibold text-emerald-800">{t(mcData.suggested_next)}</p>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}

      {/* ── LEGACY FORMAT ── */}
      {hasData && !isRichFormat && (
        <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">

          {legacyGaps.length > 0 && (
            <Card>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-red-100">
                    <AlertTriangle className="h-4 w-4 text-red-600" />
                  </div>
                  <CardTitle>Prerequisite Gaps</CardTitle>
                </div>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2">
                  {legacyGaps.map((gap, i) => (
                    <li key={i} className="flex items-start gap-2.5 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5">
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-red-200 text-[0.625rem] font-bold text-red-700 mt-0.5">{i+1}</span>
                      <span className="text-sm text-red-800 leading-snug">{t(gap)}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          {legacyIncomplete.length > 0 && (
            <Card>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-100">
                    <BookOpen className="h-4 w-4 text-amber-600" />
                  </div>
                  <CardTitle>Incomplete Topics</CardTitle>
                </div>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2">
                  {legacyIncomplete.map((topic, i) => (
                    <li key={i} className="flex items-start gap-2.5 rounded-lg border border-amber-100 bg-amber-50 px-3 py-2.5">
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber-200 text-[0.625rem] font-bold text-amber-700 mt-0.5">{i+1}</span>
                      <span className="text-sm text-amber-800 leading-snug">{t(topic)}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          {legacySuggested && (
            <Card className="md:col-span-2 xl:col-span-1">
              <CardHeader>
                <div className="flex items-center gap-2">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-100">
                    <Lightbulb className="h-4 w-4 text-indigo-600" />
                  </div>
                  <CardTitle>Suggested Next Topic</CardTitle>
                </div>
              </CardHeader>
              <CardContent>
                <div className="flex items-start gap-3 rounded-xl bg-indigo-50 p-4">
                  <ArrowRight className="h-5 w-5 text-indigo-500 shrink-0 mt-0.5" />
                  <p className="text-sm font-medium text-indigo-800 leading-relaxed">{t(legacySuggested)}</p>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* ── Footer actions ── */}
      {hasData && (
        <div className="flex flex-wrap gap-3 pt-2 border-t border-slate-100">
          <Link href={`/sessions/${sessionId}/quiz`}>
            <Button size="sm" variant="secondary">View Quiz →</Button>
          </Link>
          <Link href={`/sessions/${sessionId}/experiments`}>
            <Button size="sm" variant="secondary">View Experiments →</Button>
          </Link>
          <Link href={`/sessions/${sessionId}/notes`}>
            <Button size="sm" variant="secondary">Curriculum Intelligence →</Button>
          </Link>
        </div>
      )}
    </div>
  );
}
