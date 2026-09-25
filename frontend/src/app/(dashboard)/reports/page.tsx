"use client";

import { useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import {
  BarChart2,
  BookOpen,
  Brain,
  Cpu,
  Zap,
  AlertCircle,
  CheckCircle2,
  Clock,
  RefreshCw,
  TrendingUp,
  Tag,
  Wifi,
  WifiOff,
  ChevronRight,
} from "lucide-react";
import { api, type TeacherReport, type UnitSummary, type UnitDetail, DEV_TEACHER_ID } from "@/lib/api";
import { cn, BLOOM_COLOURS, formatDate } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LoadingScreen } from "@/components/ui/Spinner";

// ── Constants ─────────────────────────────────────────────────────────────────

const PERIODS = [
  { value: 7,   label: "7 days" },
  { value: 30,  label: "30 days" },
  { value: 90,  label: "90 days" },
  { value: 365, label: "1 year" },
] as const;

type Period = 7 | 30 | 90 | 365;

const BLOOM_ORDER = ["remember", "understand", "apply", "analyze", "evaluate", "create"] as const;

const SYNC_HEALTH_CONFIG: Record<string, { label: string; colour: string; dot: string }> = {
  healthy:  { label: "Healthy",  colour: "text-green-600",  dot: "bg-green-500" },
  degraded: { label: "Degraded", colour: "text-yellow-600", dot: "bg-yellow-400" },
  offline:  { label: "Offline",  colour: "text-red-600",    dot: "bg-red-500" },
  unknown:  { label: "Unknown",  colour: "text-slate-400",  dot: "bg-slate-300" },
};

const CONCEPT_TYPE_COLOURS: Record<string, string> = {
  prerequisite_gap:  "bg-red-100 text-red-700",
  incomplete_topic:  "bg-yellow-100 text-yellow-700",
  skipped:           "bg-slate-100 text-slate-600",
};

// ── Micro-components ──────────────────────────────────────────────────────────

function StatCard({
  label, value, sub, icon, colour = "text-slate-900",
}: {
  label: string;
  value: number | string;
  sub?: string;
  icon: React.ReactNode;
  colour?: string;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs text-slate-500">{label}</p>
          <p className={cn("mt-1 text-2xl font-bold tabular-nums", colour)}>{value}</p>
          {sub && <p className="mt-0.5 text-[0.6875rem] text-slate-400">{sub}</p>}
        </div>
        <div className="mt-0.5 text-slate-300">{icon}</div>
      </div>
    </Card>
  );
}

/** CSS-only horizontal bar chart row */
function BarRow({
  label, value, max, colour = "bg-indigo-500", badge,
}: {
  label: string;
  value: number;
  max: number;
  colour?: string;
  badge?: React.ReactNode;
}) {
  const pct = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  return (
    <div className="flex items-center gap-3">
      <span className="w-28 shrink-0 text-xs text-slate-600 truncate" title={label}>{label}</span>
      <div className="flex-1 h-2.5 rounded-full bg-slate-100 overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all", colour)}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-8 shrink-0 text-right text-xs font-medium text-slate-700 tabular-nums">
        {value}
      </span>
      {badge}
    </div>
  );
}

/** Sessions sparkline — tiny 7×7 grid of dots sized by count */
function SparkGrid({ data, period }: { data: { date: string; count: number }[]; period: Period }) {
  const max = Math.max(...data.map(d => d.count), 1);
  // For long periods show weekly buckets
  const buckets: { label: string; count: number }[] = [];

  if (period <= 30) {
    // Show every day
    for (const d of data) {
      const label = new Date(d.date).toLocaleDateString("en-IN", { month: "short", day: "numeric" });
      buckets.push({ label, count: d.count });
    }
  } else {
    // Bucket into weeks
    let weekCount = 0;
    let weekLabel = "";
    data.forEach((d, i) => {
      weekCount += d.count;
      if (i % 7 === 0) {
        weekLabel = new Date(d.date).toLocaleDateString("en-IN", { month: "short", day: "numeric" });
      }
      if ((i + 1) % 7 === 0 || i === data.length - 1) {
        buckets.push({ label: weekLabel, count: weekCount });
        weekCount = 0;
      }
    });
  }

  const bucketMax = Math.max(...buckets.map(b => b.count), 1);

  return (
    <div className="flex items-end gap-1 h-16 overflow-x-auto pb-1">
      {buckets.map((b, i) => {
        const heightPct = b.count > 0 ? Math.max(15, Math.round((b.count / bucketMax) * 100)) : 4;
        return (
          <div key={i} className="flex flex-col items-center gap-1 shrink-0 group relative">
            <div
              className={cn(
                "w-4 rounded-sm transition-all",
                b.count > 0 ? "bg-indigo-400 group-hover:bg-indigo-600" : "bg-slate-100"
              )}
              style={{ height: `${heightPct}%` }}
            />
            {/* Tooltip on hover */}
            <div className="absolute bottom-full mb-1 left-1/2 -translate-x-1/2 hidden group-hover:block z-10">
              <div className="rounded bg-slate-800 px-1.5 py-0.5 text-[0.625rem] text-white whitespace-nowrap">
                {b.label}: {b.count}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Sections ──────────────────────────────────────────────────────────────────

function SummaryCards({ report, period }: { report: TeacherReport; period: Period }) {
  const syncTotal = report.sync_pending + report.sync_failed + report.sync_completed;
  const syncPct = syncTotal > 0 ? Math.round((report.sync_completed / syncTotal) * 100) : 0;

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <StatCard
        label="Sessions"
        value={report.sessions_total}
        sub={`+${report.sessions_this_period} this period`}
        icon={<BookOpen className="h-5 w-5" />}
        colour="text-slate-900"
      />
      <StatCard
        label="Topics Covered"
        value={report.topics_count}
        sub="distinct quiz topics"
        icon={<Tag className="h-5 w-5" />}
        colour="text-indigo-600"
      />
      <StatCard
        label="AI Outputs"
        value={report.ai_outputs_total}
        sub={`+${report.ai_outputs_this_period} this period`}
        icon={<Brain className="h-5 w-5" />}
        colour="text-purple-600"
      />
      <StatCard
        label="Quizzes"
        value={report.quizzes_generated}
        sub={`${report.quizzes_exported_to_tiqer} exported to TiQer`}
        icon={<Cpu className="h-5 w-5" />}
        colour="text-sky-600"
      />
      <StatCard
        label="Missing Concepts"
        value={report.missing_concepts_total}
        sub={`${report.missing_concepts_resolved} resolved`}
        icon={<AlertCircle className="h-5 w-5" />}
        colour={report.missing_concepts_total > 0 ? "text-orange-500" : "text-slate-900"}
      />
      <StatCard
        label="Sync"
        value={`${syncPct}%`}
        sub={`${report.sync_pending} pending · ${report.sync_failed} failed`}
        icon={report.sync_failed > 0 ? <WifiOff className="h-5 w-5" /> : <Wifi className="h-5 w-5" />}
        colour={report.sync_failed > 0 ? "text-orange-500" : "text-green-600"}
      />
    </div>
  );
}

function SessionsTimeline({ report, period }: { report: TeacherReport; period: Period }) {
  const total = report.sessions_over_time.reduce((s, d) => s + d.count, 0);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Sessions Over Time</CardTitle>
        <span className="text-sm text-slate-400">{total} sessions in last {period} days</span>
      </CardHeader>
      <CardContent>
        <SparkGrid data={report.sessions_over_time} period={period} />
      </CardContent>
    </Card>
  );
}

function SubjectBreakdown({ report }: { report: TeacherReport }) {
  const max = Math.max(...report.subject_breakdown.map(s => s.count), 1);
  if (report.subject_breakdown.length === 0) {
    return (
      <Card>
        <CardHeader><CardTitle>Subject Breakdown</CardTitle></CardHeader>
        <CardContent>
          <p className="text-sm text-slate-400">No subject data yet.</p>
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>Subject Breakdown</CardTitle>
        <span className="text-sm text-slate-400">{report.subject_breakdown.length} subjects</span>
      </CardHeader>
      <CardContent className="space-y-2">
        {report.subject_breakdown.map(s => (
          <BarRow
            key={s.subject}
            label={s.subject}
            value={s.count}
            max={max}
            colour="bg-indigo-400"
          />
        ))}
      </CardContent>
    </Card>
  );
}

function TopicsCovered({ report }: { report: TeacherReport }) {
  const [expanded, setExpanded] = useState(false);
  const items = expanded ? report.topics_covered : report.topics_covered.slice(0, 12);
  const max = Math.max(...report.topics_covered.map(t => t.frequency), 1);

  if (report.topics_covered.length === 0) {
    return (
      <Card>
        <CardHeader><CardTitle>Topics Covered</CardTitle></CardHeader>
        <CardContent>
          <p className="text-sm text-slate-400">
            No topics yet — topics are extracted from quiz questions.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Topics Covered</CardTitle>
        <span className="text-sm text-slate-400">{report.topics_covered.length} distinct topics</span>
      </CardHeader>
      <CardContent className="space-y-2">
        {items.map(t => (
          <BarRow
            key={t.topic}
            label={t.topic}
            value={t.frequency}
            max={max}
            colour="bg-sky-400"
            badge={
              <span className="text-[0.625rem] text-slate-400 whitespace-nowrap">
                {t.frequency} q{t.frequency !== 1 ? "s" : ""}
              </span>
            }
          />
        ))}
        {report.topics_covered.length > 12 && (
          <button
            onClick={() => setExpanded(v => !v)}
            className="text-xs text-indigo-500 hover:underline mt-1"
          >
            {expanded ? "Show less" : `Show all ${report.topics_covered.length} topics`}
          </button>
        )}
      </CardContent>
    </Card>
  );
}

function BloomDistribution({ report }: { report: TeacherReport }) {
  // Merge server list into a full 6-level map
  const distMap: Record<string, number> = {};
  for (const level of BLOOM_ORDER) distMap[level] = 0;
  for (const b of report.bloom_distribution) distMap[b.bloom_level] = b.count;
  const max = Math.max(...Object.values(distMap), 1);
  const total = Object.values(distMap).reduce((a, b) => a + b, 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Bloom Distribution</CardTitle>
        <span className="text-sm text-slate-400">{total} questions total</span>
      </CardHeader>
      <CardContent className="space-y-2">
        {BLOOM_ORDER.map(level => {
          const count = distMap[level] ?? 0;
          const colourClass = BLOOM_COLOURS[level]?.split(" ")[0]?.replace("text-", "bg-") ?? "bg-slate-200";
          return (
            <div key={level} className="flex items-center gap-3">
              <span className="w-20 shrink-0 text-xs text-slate-600 capitalize">{level}</span>
              <div className="flex-1 h-2.5 rounded-full bg-slate-100 overflow-hidden">
                <div
                  className={cn("h-full rounded-full transition-all", colourClass)}
                  style={{ width: max > 0 ? `${Math.max(count > 0 ? 2 : 0, Math.round((count / max) * 100))}%` : "0%" }}
                />
              </div>
              <span className="w-6 shrink-0 text-right text-xs font-medium text-slate-700 tabular-nums">
                {count}
              </span>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function SyncHealth({ report }: { report: TeacherReport }) {
  const total = report.sync_breakdown.pending + report.sync_breakdown.syncing +
                report.sync_breakdown.synced + report.sync_breakdown.failed;

  const rows = [
    { label: "Synced",  value: report.sync_breakdown.synced,  colour: "bg-green-500" },
    { label: "Pending", value: report.sync_breakdown.pending, colour: "bg-slate-300" },
    { label: "Syncing", value: report.sync_breakdown.syncing, colour: "bg-blue-400" },
    { label: "Failed",  value: report.sync_breakdown.failed,  colour: "bg-orange-400" },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Sync Health</CardTitle>
        <span className="text-sm text-slate-400">{total} sessions total</span>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Stacked bar */}
        <div className="flex h-3 rounded-full overflow-hidden gap-0.5">
          {rows.filter(r => r.value > 0).map(r => (
            <div
              key={r.label}
              className={cn("h-full first:rounded-l-full last:rounded-r-full", r.colour)}
              style={{ width: total > 0 ? `${(r.value / total) * 100}%` : "0%" }}
            />
          ))}
          {total === 0 && <div className="h-full w-full rounded-full bg-slate-100" />}
        </div>

        <div className="grid grid-cols-2 gap-2">
          {rows.map(r => (
            <div key={r.label} className="flex items-center gap-2">
              <span className={cn("h-2.5 w-2.5 rounded-full shrink-0", r.colour)} />
              <span className="text-xs text-slate-600">{r.label}</span>
              <span className="ml-auto text-xs font-medium tabular-nums text-slate-900">{r.value}</span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function MissingConcepts({ report }: { report: TeacherReport }) {
  if (report.recent_missing_concepts.length === 0) {
    return (
      <Card>
        <CardHeader><CardTitle>Missing Concepts</CardTitle></CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 text-sm text-green-600">
            <CheckCircle2 className="h-4 w-4" />
            No unresolved missing concepts — great coverage!
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Unresolved Gaps</CardTitle>
        <span className="text-sm text-slate-400">
          {report.missing_concepts_total - report.missing_concepts_resolved} unresolved ·{" "}
          {report.missing_concepts_resolved} resolved
        </span>
      </CardHeader>
      <CardContent className="p-0">
        <ul className="divide-y divide-slate-100">
          {report.recent_missing_concepts.map(mc => (
            <li key={mc.concept_id} className="flex items-start gap-3 px-5 py-3">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5 text-orange-400" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-slate-800 leading-snug">{mc.concept}</p>
                {mc.description && (
                  <p className="text-xs text-slate-400 mt-0.5 line-clamp-2">{mc.description}</p>
                )}
                <div className="mt-1.5 flex items-center gap-1.5 flex-wrap">
                  <Badge className={cn("text-[0.625rem]", CONCEPT_TYPE_COLOURS[mc.concept_type] ?? "bg-slate-100 text-slate-500")}>
                    {mc.concept_type.replace("_", " ")}
                  </Badge>
                  {mc.session_subject && (
                    <span className="text-[0.625rem] text-slate-400">{mc.session_subject}</span>
                  )}
                  <span className="text-[0.625rem] text-slate-300">{formatDate(mc.created_at)}</span>
                </div>
              </div>
              <Link href={`/sessions/${mc.session_id}/missing-concepts`}>
                <ChevronRight className="h-4 w-4 text-slate-300 hover:text-indigo-500 shrink-0 mt-0.5" />
              </Link>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function QuizSessions({ report }: { report: TeacherReport }) {
  if (report.quiz_sessions.length === 0) {
    return null;
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>Quizzes Generated</CardTitle>
        <span className="text-sm text-slate-400">{report.quizzes_generated} sessions with quizzes</span>
      </CardHeader>
      <CardContent className="p-0">
        <ul className="divide-y divide-slate-100">
          {report.quiz_sessions.map(qs => (
            <li key={qs.session_id} className="flex items-center gap-3 px-5 py-3">
              <Cpu className="h-4 w-4 shrink-0 text-sky-400" />
              <div className="min-w-0 flex-1">
                <p className="text-sm text-slate-800">
                  {qs.subject ?? "Untitled"}{qs.grade ? ` · ${qs.grade}` : ""}
                </p>
                <p className="text-xs text-slate-400">{formatDate(qs.created_at)}</p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Badge className="text-[0.625rem] bg-sky-100 text-sky-700">
                  {qs.question_count} Qs
                </Badge>
                {qs.exported_to_tiqer > 0 && (
                  <Badge className="text-[0.625rem] bg-indigo-100 text-indigo-700 gap-1">
                    <Zap className="h-2.5 w-2.5" />
                    TiQer
                  </Badge>
                )}
              </div>
              <Link href={`/sessions/${qs.session_id}/quiz`}>
                <ChevronRight className="h-4 w-4 text-slate-300 hover:text-indigo-500" />
              </Link>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

// ── Admin / CSR future-ready panels ──────────────────────────────────────────

function AdminReadyPanel() {
  return (
    <Card className="border-dashed border-slate-200 bg-slate-50/50">
      <CardContent className="py-6">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-200">
            <BarChart2 className="h-5 w-5 text-slate-500" />
          </div>
          <div>
            <p className="text-sm font-semibold text-slate-700">Admin & CSR Reports</p>
            <p className="text-xs text-slate-400 mt-0.5">
              School-level summaries, teacher usage, concept coverage, and connectivity
              reports are available via{" "}
              <code className="bg-slate-100 rounded px-1 text-[0.6875rem]">
                GET /dashboard/admin/&#123;school_id&#125;/report
              </code>
              {" "}and{" "}
              <code className="bg-slate-100 rounded px-1 text-[0.6875rem]">
                GET /dashboard/csr/&#123;program_id&#125;/report
              </code>
              . Admin and CSR dashboards are planned for Phase 2.
            </p>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { icon: BookOpen, label: "School/Session Summary",    desc: "Sessions per school, active classrooms" },
            { icon: TrendingUp, label: "Teacher Usage",           desc: "Activity, AI outputs, TiQer exports" },
            { icon: Tag, label: "Concept Coverage",               desc: "Topics taught across the program" },
            { icon: Wifi,  label: "Connectivity / Sync Status",   desc: "Sync failure rates, pending uploads" },
          ].map(item => (
            <div key={item.label} className="flex items-start gap-2 rounded-lg bg-white border border-slate-200 p-3">
              <item.icon className="h-4 w-4 shrink-0 mt-0.5 text-slate-400" />
              <div>
                <p className="text-xs font-medium text-slate-700">{item.label}</p>
                <p className="text-[0.6875rem] text-slate-400 mt-0.5">{item.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

// ── Unit View ─────────────────────────────────────────────────────────────────

function UnitSessionTimeline({ sessions }: { sessions: UnitDetail["sessions"] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Session timeline</CardTitle>
        <span className="text-sm text-slate-400">{sessions.length} sessions</span>
      </CardHeader>
      <CardContent>
        <div className="relative pl-5">
          <div className="absolute left-[0.4375rem] top-2 bottom-2 w-px bg-slate-200" />
          <div className="space-y-5">
            {sessions.map((s, i) => {
              const isLatest = i === sessions.length - 1;
              return (
                <div key={s.session_id} className="relative">
                  <span className={cn(
                    "absolute -left-[1.125rem] top-1 h-2.5 w-2.5 rounded-full border-2 border-white",
                    isLatest ? "bg-indigo-500" : "bg-emerald-400"
                  )} />
                  <div className="flex items-baseline justify-between gap-2">
                    <span className={cn("text-sm font-medium", isLatest ? "text-indigo-700" : "text-slate-800")}>
                      {isLatest ? "Latest · " : ""}{s.date}
                    </span>
                    {s.title && <span className="text-xs text-slate-400 truncate max-w-[10rem]">{s.title}</span>}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {s.topics_covered.slice(0, 4).map((t, j) => (
                      <span key={j} className="rounded-full bg-emerald-50 px-2.5 py-0.5 text-[0.6875rem] font-medium text-emerald-700">
                        {t}
                      </span>
                    ))}
                    {s.gaps.slice(0, 2).map((g, j) => (
                      <span key={j} className={cn(
                        "rounded-full px-2.5 py-0.5 text-[0.6875rem] font-medium",
                        isLatest ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-700"
                      )}>
                        {g} {isLatest ? "✗" : "⚠"}
                      </span>
                    ))}
                  </div>
                  {s.topics_covered.length === 0 && s.gaps.length === 0 && (
                    <p className="mt-1 text-xs text-slate-400 italic">No AI analysis yet</p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function UnitDetailPanel({ teacherId, unit }: { teacherId: string; unit: UnitSummary }) {
  const { data, isLoading } = useSWR(
    ["unit-detail", teacherId, unit.subject, unit.grade],
    () => api.getTeacherUnitDetail(teacherId, unit.subject, unit.grade),
    { revalidateOnFocus: false }
  );

  if (isLoading) return (
    <div className="flex items-center justify-center h-40 text-slate-400 text-sm">
      <RefreshCw className="h-4 w-4 animate-spin mr-2" /> Loading unit…
    </div>
  );
  if (!data) return null;

  return (
    <div className="space-y-4">
      <div className="flex items-baseline gap-3">
        <h2 className="text-base font-semibold text-slate-900">{data.subject} · {data.grade}</h2>
        <span className="text-xs text-slate-400">{unit.session_count} sessions · {unit.first_date} → {unit.last_date}</span>
      </div>

      <UnitSessionTimeline sessions={data.sessions} />

      <div className="grid gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Recurring gaps</CardTitle>
            <span className="text-sm text-slate-400">Missed in 2+ sessions</span>
          </CardHeader>
          <CardContent>
            {data.recurring_gaps.length === 0 ? (
              <div className="flex items-center gap-2 text-sm text-emerald-600">
                <CheckCircle2 className="h-4 w-4" /> No recurring gaps — great coverage!
              </div>
            ) : (
              <div className="space-y-2">
                {data.recurring_gaps.map((g, i) => (
                  <div key={i} className="flex items-center justify-between">
                    <span className="text-sm text-slate-800">{g.concept}</span>
                    <span className={cn(
                      "text-[0.6875rem] rounded-full px-2.5 py-0.5 font-medium",
                      g.count >= 3 ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"
                    )}>
                      {g.count} sessions
                    </span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Continue from here</CardTitle>
            <span className="text-sm text-slate-400">Suggested by last session</span>
          </CardHeader>
          <CardContent>
            {data.continue_from_here.length === 0 ? (
              <p className="text-sm text-slate-400 italic">No suggestions yet — run Classroom Insights on the latest session.</p>
            ) : (
              <ul className="space-y-2">
                {data.continue_from_here.map((s, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-slate-800">
                    <ChevronRight className="h-4 w-4 shrink-0 mt-0.5 text-indigo-400" />
                    {s}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="flex justify-end">
        <Link href={`/sessions/${data.sessions[data.sessions.length - 1]?.session_id}/missing-concepts`}>
          <Button variant="secondary" size="sm">
            Open latest session <ChevronRight className="h-3.5 w-3.5 ml-1" />
          </Button>
        </Link>
      </div>
    </div>
  );
}

function UnitViewTab({ teacherId }: { teacherId: string }) {
  const [selectedUnit, setSelectedUnit] = useState<UnitSummary | null>(null);

  const { data: units, isLoading } = useSWR(
    ["teacher-units", teacherId],
    () => api.getTeacherUnits(teacherId),
    { revalidateOnFocus: false }
  );

  if (isLoading) return <LoadingScreen label="Loading units…" />;

  if (!units || units.length === 0) {
    return (
      <Card className="border-dashed border-slate-200">
        <CardContent className="py-10 text-center">
          <BookOpen className="h-8 w-8 text-slate-300 mx-auto mb-3" />
          <p className="text-sm font-medium text-slate-600">No units yet</p>
          <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">
            Units are created automatically once sessions have a subject and grade filled in.
            Set up your classroom profile to get started.
          </p>
        </CardContent>
      </Card>
    );
  }

  const active = selectedUnit ?? units[0];

  return (
    <div className="grid gap-5 lg:grid-cols-[220px_1fr]">
      <div className="space-y-2">
        <p className="text-[0.6875rem] font-semibold uppercase tracking-wider text-slate-400 px-1">Your units</p>
        {units.map(u => {
          const isActive = active.subject === u.subject && active.grade === u.grade;
          return (
            <button
              key={`${u.subject}|${u.grade}`}
              onClick={() => setSelectedUnit(u)}
              className={cn(
                "w-full rounded-lg border px-3 py-2.5 text-left transition-colors",
                isActive
                  ? "border-indigo-300 bg-indigo-50"
                  : "border-slate-200 bg-white hover:bg-slate-50"
              )}
            >
              <p className={cn("text-sm font-medium", isActive ? "text-indigo-800" : "text-slate-800")}>{u.subject}</p>
              <p className={cn("text-xs mt-0.5", isActive ? "text-indigo-500" : "text-slate-500")}>
                {u.grade} · {u.session_count} session{u.session_count !== 1 ? "s" : ""}
              </p>
              <p className="text-[0.6875rem] text-slate-400 mt-0.5">{u.first_date} → {u.last_date}</p>
            </button>
          );
        })}
        <div className="rounded-lg border border-dashed border-slate-200 p-3 mt-2">
          <p className="text-[0.6875rem] text-slate-400 text-center">Sessions without subject won't appear here</p>
        </div>
      </div>

      <UnitDetailPanel teacherId={teacherId} unit={active} />
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

type PageTab = "overview" | "units";

export default function ReportsPage() {
  const [period, setPeriod] = useState<Period>(30);
  const [tab, setTab] = useState<PageTab>("overview");

  const { data: report, error, isLoading, mutate } = useSWR(
    ["teacher-report", DEV_TEACHER_ID, period],
    () => api.getTeacherReport(DEV_TEACHER_ID, period),
    { refreshInterval: 60_000, shouldRetryOnError: false }
  );

  return (
    <div className="space-y-6">
      {/* ── Header ── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-600">
            <BarChart2 className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-900">Reports</h1>
            <p className="text-sm text-slate-500 mt-0.5">
              Sessions, topics, AI outputs, quizzes, and sync health
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Tab selector */}
          <div className="flex rounded-lg border border-slate-200 overflow-hidden">
            {(["overview", "units"] as PageTab[]).map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={cn(
                  "px-3 py-1.5 text-xs font-medium transition-colors capitalize",
                  tab === t
                    ? "bg-indigo-600 text-white"
                    : "bg-white text-slate-600 hover:bg-slate-50"
                )}
              >
                {t === "units" ? "Unit View" : "Overview"}
              </button>
            ))}
          </div>

          {tab === "overview" && (
            <>
              {/* Period selector */}
              <div className="flex rounded-lg border border-slate-200 overflow-hidden">
                {PERIODS.map(p => (
                  <button
                    key={p.value}
                    onClick={() => setPeriod(p.value)}
                    className={cn(
                      "px-3 py-1.5 text-xs font-medium transition-colors",
                      period === p.value
                        ? "bg-slate-700 text-white"
                        : "bg-white text-slate-600 hover:bg-slate-50"
                    )}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              <Button variant="secondary" size="sm" onClick={() => mutate()} disabled={isLoading}>
                <RefreshCw className={cn("h-3.5 w-3.5", isLoading && "animate-spin")} />
              </Button>
            </>
          )}
        </div>
      </div>

      {/* ── Unit View tab ── */}
      {tab === "units" && <UnitViewTab teacherId={DEV_TEACHER_ID} />}

      {/* ── Overview tab ── */}
      {tab === "overview" && (
        <>
          {isLoading && !report && <LoadingScreen label="Loading report…" />}

          {error && !report && (
            <Card className="border-orange-200 bg-orange-50 p-5">
              <div className="flex items-center gap-2 text-orange-700">
                <AlertCircle className="h-5 w-5 shrink-0" />
                <div>
                  <p className="font-medium">Could not load report</p>
                  <p className="text-xs mt-0.5">
                    Make sure the backend is running at{" "}
                    <code className="bg-orange-100 rounded px-1">{process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/v1"}</code>
                  </p>
                </div>
              </div>
            </Card>
          )}

          {report && (
            <>
              <SummaryCards report={report} period={period} />
              <div className="grid gap-5 lg:grid-cols-2">
                <SessionsTimeline report={report} period={period} />
                <SubjectBreakdown report={report} />
              </div>
              <div className="grid gap-5 lg:grid-cols-3">
                <div className="lg:col-span-2"><TopicsCovered report={report} /></div>
                <div className="space-y-5">
                  <BloomDistribution report={report} />
                  <SyncHealth report={report} />
                </div>
              </div>
              <div className="grid gap-5 lg:grid-cols-2">
                <MissingConcepts report={report} />
                <QuizSessions report={report} />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wide mb-3">
                  Admin &amp; CSR (Phase 2)
                </h2>
                <AdminReadyPanel />
              </div>
            </>
          )}

          {report && isLoading && (
            <div className="fixed bottom-4 right-4 flex items-center gap-2 rounded-lg bg-white border border-slate-200 shadow-lg px-3 py-2 text-xs text-slate-500">
              <RefreshCw className="h-3.5 w-3.5 animate-spin text-indigo-500" />
              Refreshing report…
            </div>
          )}
        </>
      )}
    </div>
  );
}
