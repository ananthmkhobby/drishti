"use client";

import { use, useEffect, useState } from "react";
import useSWR from "swr";
import {
  BookOpen, Cpu, Clock, Target, FlaskConical,
  Search, Lightbulb, Palette, CheckCircle2,
  Loader2, AlertTriangle, RefreshCw, Download, ChevronRight,
} from "lucide-react";
import { api } from "@/lib/api";
import { fetchOutputsCached } from "@/lib/cached-fetchers";
import { useEventPoller } from "@/hooks/useEventPoller";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { LoadingScreen } from "@/components/ui/Spinner";
import { useTranslation } from "@/hooks/useTranslation";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

interface HomeworkTask {
  task: string;
  type: "practice" | "explore" | "research" | "creative";
  bloom_level: string;
  estimated_minutes: number;
  topic: string;
  // Optional — absent on homework generated before this existed.
  answer?: string;
  explanation?: string;
}

// ─── Task type config ─────────────────────────────────────────────────────────

const TYPE_CONFIG: Record<string, { label: string; icon: React.ReactNode; colour: string; bg: string; border: string }> = {
  practice:  { label: "Practice",  icon: <Target className="h-3.5 w-3.5" />,      colour: "text-blue-700",   bg: "bg-blue-50",   border: "border-blue-200"   },
  explore:   { label: "Explore",   icon: <Search className="h-3.5 w-3.5" />,       colour: "text-teal-700",   bg: "bg-teal-50",   border: "border-teal-200"   },
  research:  { label: "Research",  icon: <FlaskConical className="h-3.5 w-3.5" />, colour: "text-indigo-700", bg: "bg-indigo-50", border: "border-indigo-200" },
  creative:  { label: "Creative",  icon: <Palette className="h-3.5 w-3.5" />,      colour: "text-rose-700",   bg: "bg-rose-50",   border: "border-rose-200"   },
};

const BLOOM_COLOURS: Record<string, string> = {
  remember:   "bg-slate-200 text-slate-700",
  understand: "bg-blue-100 text-blue-700",
  apply:      "bg-teal-100 text-teal-700",
  analyze:    "bg-indigo-100 text-indigo-700",
  evaluate:   "bg-purple-100 text-purple-700",
  create:     "bg-pink-100 text-pink-700",
};

// ─── Task card ────────────────────────────────────────────────────────────────

function TaskCard({ task, index, t }: { task: HomeworkTask; index: number; t: (s: string) => string }) {
  const [showAnswer, setShowAnswer] = useState(false);
  const cfg = TYPE_CONFIG[task.type] ?? TYPE_CONFIG.practice;
  const bloomKey = task.bloom_level?.toLowerCase();
  const bloomClass = BLOOM_COLOURS[bloomKey] ?? "bg-slate-100 text-slate-600";
  const hasAnswer = !!(task.answer || task.explanation);

  return (
    <div className={cn(
      "rounded-2xl border p-4 transition-all duration-200 hover:shadow-md",
      cfg.bg, cfg.border
    )}>
      {/* Header row */}
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          <span className={cn(
            "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm font-bold text-white",
            task.type === "practice" ? "bg-blue-500" :
            task.type === "explore"  ? "bg-teal-500" :
            task.type === "research" ? "bg-indigo-500" : "bg-rose-500"
          )}>
            {index + 1}
          </span>
          <span className={cn("flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold", cfg.colour, cfg.bg, cfg.border, "border")}>
            {cfg.icon}
            {cfg.label}
          </span>
        </div>
        <div className="flex items-center gap-1 rounded-full bg-white/70 px-2 py-1 text-xs text-slate-500">
          <Clock className="h-3 w-3" />
          <span>{task.estimated_minutes} min</span>
        </div>
      </div>

      {/* Task text */}
      <p className={cn("text-sm font-medium leading-relaxed mb-3", cfg.colour)}>
        {t(task.task)}
      </p>

      {/* Footer chips */}
      <div className="flex flex-wrap items-center gap-2">
        {task.topic && (
          <span className="rounded-full bg-white/80 border border-slate-200 px-2.5 py-0.5 text-[0.6875rem] text-slate-600">
            {t(task.topic)}
          </span>
        )}
        {bloomKey && (
          <span className={cn("rounded-full px-2.5 py-0.5 text-[0.6875rem] font-semibold capitalize", bloomClass)}>
            {bloomKey}
          </span>
        )}
      </div>

      {/* Answer + explanation — collapsed by default so the card grid stays scannable */}
      {hasAnswer && (
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setShowAnswer((v) => !v)}
            aria-expanded={showAnswer}
            className="flex items-center gap-1.5 rounded-full border border-slate-200 bg-white/80 px-2.5 py-1 text-[0.6875rem] font-semibold text-slate-600 transition-colors hover:bg-white"
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
            {showAnswer ? t("Hide answer") : t("Show answer")}
            <ChevronRight className={cn("h-3 w-3 transition-transform", showAnswer && "rotate-90")} />
          </button>

          {showAnswer && (
            <div className="mt-2 space-y-2 rounded-xl border border-white/60 bg-white/70 p-3">
              {task.answer && (
                <div>
                  <p className="mb-0.5 text-[0.625rem] font-bold uppercase tracking-wide text-slate-400">{t("Answer")}</p>
                  <p className="whitespace-pre-wrap text-sm font-medium leading-relaxed text-slate-800">{t(task.answer)}</p>
                </div>
              )}
              {task.explanation && (
                <div>
                  <p className="mb-0.5 text-[0.625rem] font-bold uppercase tracking-wide text-slate-400">{t("Explanation")}</p>
                  <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-600">{t(task.explanation)}</p>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Summary stats ────────────────────────────────────────────────────────────

function HWStats({ tasks }: { tasks: HomeworkTask[] }) {
  const totalMin = tasks.reduce((s, t) => s + (t.estimated_minutes || 0), 0);
  const typeCount = tasks.reduce<Record<string, number>>((acc, t) => {
    acc[t.type] = (acc[t.type] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <StatBox label="Total tasks" value={String(tasks.length)} colour="bg-indigo-50 text-indigo-700" />
      <StatBox label="Est. time" value={`~${totalMin} min`} colour="bg-amber-50 text-amber-700" />
      <StatBox label="Practice" value={String(typeCount.practice || 0)} colour="bg-blue-50 text-blue-700" />
      <StatBox label="Explore/Research" value={String((typeCount.explore || 0) + (typeCount.research || 0) + (typeCount.creative || 0))} colour="bg-teal-50 text-teal-700" />
    </div>
  );
}

function StatBox({ label, value, colour }: { label: string; value: string; colour: string }) {
  return (
    <div className={cn("rounded-xl p-3 text-center", colour)}>
      <p className="text-xl font-bold">{value}</p>
      <p className="text-[0.6875rem] font-medium opacity-80 mt-0.5">{label}</p>
    </div>
  );
}

// ─── PDF export ───────────────────────────────────────────────────────────────

function downloadHomeworkPDF(tasks: HomeworkTask[], subject: string, grade: string, t: (s: string) => string) {
  const totalMin = tasks.reduce((s, t) => s + (t.estimated_minutes || 0), 0);
  const typeColours: Record<string, string> = {
    practice: "#3b82f6", explore: "#14b8a6", research: "#6366f1", creative: "#f43f5e",
  };

  const html = `<!DOCTYPE html><html><head><meta charset="UTF-8"/><title>Homework — ${subject || "Class"}</title>
<style>
  body{font-family:Arial,sans-serif;max-width:680px;margin:0 auto;padding:32px 40px;color:#1e293b;font-size:14px}
  h1{font-size:20px;color:#312e81;margin:0 0 4px}
  .meta{font-size:12px;color:#64748b;margin-bottom:20px;border-bottom:2px solid #6366f1;padding-bottom:10px;display:flex;justify-content:space-between}
  .stats{display:flex;gap:12px;margin-bottom:20px}
  .stat{flex:1;background:#f0f4ff;border-radius:8px;padding:10px;text-align:center}
  .stat-val{font-size:20px;font-weight:800;color:#4338ca}
  .stat-lbl{font-size:10px;color:#64748b;margin-top:2px}
  .task{border-radius:10px;padding:14px 16px;margin-bottom:12px;border:1px solid #e2e8f0}
  .task-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
  .type-badge{display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;color:white}
  .time{font-size:11px;color:#64748b;background:#f8fafc;border:1px solid #e2e8f0;padding:3px 8px;border-radius:20px}
  .task-text{font-size:13px;font-weight:500;color:#1e293b;margin:0 0 8px;line-height:1.6}
  .chips{display:flex;flex-wrap:wrap;gap:6px}
  .chip{font-size:10px;padding:2px 8px;border-radius:12px;background:#f1f5f9;color:#475569;border:1px solid #e2e8f0}
  .bloom{background:#ede9fe;color:#5b21b6}
  .footer{margin-top:24px;padding-top:8px;border-top:1px solid #e2e8f0;font-size:11px;color:#94a3b8;text-align:center}
</style></head><body>
<h1>📚 Homework — ${subject || "Class"}</h1>
<div class="meta">
  <span>${grade ? grade + " · " : ""}${tasks.length} tasks · ~${totalMin} minutes total</span>
  <span>Drishti</span>
</div>
<div class="stats">
  <div class="stat"><div class="stat-val">${tasks.length}</div><div class="stat-lbl">Tasks</div></div>
  <div class="stat"><div class="stat-val">${totalMin}</div><div class="stat-lbl">Minutes</div></div>
</div>
${tasks.map((task, i) => `
<div class="task">
  <div class="task-header">
    <div style="display:flex;align-items:center;gap:8px">
      <span style="background:#e0e7ff;color:#3730a3;border-radius:50%;width:22px;height:22px;display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:800">${i+1}</span>
      <span class="type-badge" style="background:${typeColours[task.type] || "#6366f1"}">${task.type.charAt(0).toUpperCase() + task.type.slice(1)}</span>
    </div>
    <span class="time">⏱ ${task.estimated_minutes} min</span>
  </div>
  <p class="task-text">${t(task.task)}</p>
  <div class="chips">
    ${task.topic ? `<span class="chip">${t(task.topic)}</span>` : ""}
    ${task.bloom_level ? `<span class="chip bloom">${task.bloom_level}</span>` : ""}
  </div>
</div>`).join("")}
<div class="footer">Generated by Drishti</div>
</body></html>`;

  const win = window.open("", "_blank");
  if (!win) return;
  win.document.write(html);
  win.document.close();
  win.focus();
  setTimeout(() => win.print(), 400);
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function HomeworkPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  const [generating, setGenerating] = useState(false);
  const [genMsg, setGenMsg] = useState("");
  const { t } = useTranslation();

  const { data: outputs, isLoading, mutate } = useSWR(
    ["outputs", sessionId],
    () => fetchOutputsCached(sessionId),
    {
      refreshInterval: (data) => {
        const hw = (data as { outputs?: { homework?: { status?: string } } } | undefined)?.outputs?.homework;
        return hw?.status === "processing" || hw?.status === "pending" ? 4000 : 0;
      },
    },
  );

  useEventPoller({ sessionId, onOutputReady: () => mutate() });

  const { data: session } = useSWR(["session", sessionId], () => api.getSession(sessionId), { revalidateOnFocus: false });

  async function handleGenerate() {
    setGenerating(true);
    setGenMsg("");
    try {
      await api.triggerGeneration(sessionId, ["homework"]);
      setGenMsg("Generating homework tasks…");
      mutate();
    } catch (err: unknown) {
      setGenMsg(err instanceof Error ? err.message : "Failed to generate.");
    } finally {
      setGenerating(false);
    }
  }

  const hwOutput = outputs?.outputs?.homework;
  const rawHwData = hwOutput?.data as { homework?: HomeworkTask[] } | HomeworkTask[] | undefined;
  const tasks: HomeworkTask[] = Array.isArray(rawHwData) ? rawHwData : (rawHwData?.homework ?? []);
  const isProcessing = hwOutput?.status === "processing" || hwOutput?.status === "pending";

  useEffect(() => {
    const handler = () => {
      if (tasks.length === 0) return;
      downloadHomeworkPDF(tasks, session?.subject ?? "", session?.grade ?? "", t);
    };
    window.addEventListener("classroom-brain:download_pdf", handler);
    return () => window.removeEventListener("classroom-brain:download_pdf", handler);
  }, [tasks, session, t]);

  if (isLoading) return <LoadingScreen label="Loading homework…" />;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 text-white">
            <BookOpen className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-900">Homework Tasks</h1>
            <p className="text-xs text-slate-500 mt-0.5">AI-suggested tasks based on today's lesson</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {tasks.length > 0 && (
            <button
              onClick={() => downloadHomeworkPDF(tasks, session?.subject ?? "", session?.grade ?? "", t)}
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 shadow-sm transition-colors"
            >
              <Download className="h-3.5 w-3.5" /> Download PDF
            </button>
          )}
          <Button variant="secondary" size="sm" onClick={() => mutate()}>
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
          <Button size="sm" loading={generating} onClick={handleGenerate}>
            <Cpu className="h-4 w-4" /> {tasks.length ? "Re-generate" : "Generate Homework"}
          </Button>
        </div>
      </div>

      {genMsg && (
        <div className="rounded-lg bg-indigo-50 border border-indigo-100 px-4 py-3 text-sm text-indigo-700">{genMsg}</div>
      )}

      {/* Processing */}
      {isProcessing && (
        <Card>
          <CardContent className="flex items-center justify-center gap-3 py-12 text-indigo-600">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span className="font-medium">Generating homework tasks…</span>
          </CardContent>
        </Card>
      )}

      {/* Failed */}
      {hwOutput?.status === "failed" && (
        <Card>
          <CardContent className="flex items-center gap-3 py-8 text-red-600">
            <AlertTriangle className="h-5 w-5 shrink-0" />
            <div>
              <p className="font-medium">Generation failed</p>
              <p className="text-xs text-red-400 mt-0.5">Click "Generate Homework" to try again.</p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Empty state */}
      {!isProcessing && tasks.length === 0 && hwOutput?.status !== "failed" && (
        <Card>
          <CardContent className="flex flex-col items-center gap-4 py-16 text-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-indigo-50">
              <BookOpen className="h-8 w-8 text-indigo-400" />
            </div>
            <div>
              <p className="font-semibold text-slate-700">No homework tasks yet</p>
              <p className="text-sm text-slate-400 mt-1 max-w-xs">
                Generate AI homework suggestions based on what was taught on the board today.
              </p>
            </div>
            <Button size="sm" loading={generating} onClick={handleGenerate}>
              <Cpu className="h-4 w-4" /> Generate Homework
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Tasks */}
      {tasks.length > 0 && !isProcessing && (
        <div className="space-y-4">
          {/* Stats */}
          <HWStats tasks={tasks} />

          {/* Task type legend */}
          <div className="flex flex-wrap gap-2">
            {Object.entries(TYPE_CONFIG).map(([key, cfg]) => (
              <span key={key} className={cn("flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium", cfg.colour, cfg.border, cfg.bg)}>
                {cfg.icon} {cfg.label}
              </span>
            ))}
          </div>

          {/* Cards grid */}
          <div className="grid gap-3 sm:grid-cols-2">
            {tasks.map((task, i) => (
              <TaskCard key={i} task={task} index={i} t={t} />
            ))}
          </div>

          {/* Teacher tip */}
          <Card>
            <CardContent className="flex items-start gap-3 py-4">
              <Lightbulb className="h-4 w-4 shrink-0 text-amber-500 mt-0.5" />
              <div className="text-sm text-slate-600 leading-relaxed">
                <strong className="text-slate-800">Teacher tip:</strong> Mix task types — one recall (Practice), one hands-on (Explore), and one open-ended (Research/Creative) gives students a balanced homework set.
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
