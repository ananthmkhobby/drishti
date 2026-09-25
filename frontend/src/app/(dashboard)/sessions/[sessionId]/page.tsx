"use client";

import { use, useState, useRef, useEffect } from "react";
import useSWR from "swr";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  BookOpen, Camera, FileText, HelpCircle, FlaskConical,
  AlertTriangle, Zap, CheckCircle2, Loader2, Clock,
  Cpu, RefreshCw, ChevronRight, ImageOff, ScanLine, Trash2,
  Pencil, Check, X, Coins, Sparkles, History,
} from "lucide-react";
import { api, type Session, type SessionOutputs } from "@/lib/api";
import { fetchOutputsCached } from "@/lib/cached-fetchers";
import { useEventPoller } from "@/hooks/useEventPoller";
import { useDesignVersion } from "@/hooks/useDesignVersion";
import { formatDateTime, timeAgo, STATUS_COLOURS, cn } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LoadingScreen } from "@/components/ui/Spinner";
import { CommandCenter } from "@/components/session/CommandCenter";

// ─── Output status helpers ────────────────────────────────────────────────────

const OUTPUT_META: Record<string, { label: string; icon: React.ReactNode; href: string }> = {
  notes:            { label: "Notes",           icon: <FileText className="h-4 w-4" />,     href: "notes" },
  summary:          { label: "Summary",         icon: <BookOpen className="h-4 w-4" />,     href: "notes" },
  quiz:             { label: "Quiz",            icon: <HelpCircle className="h-4 w-4" />,   href: "quiz" },
  experiments:      { label: "Experiments",     icon: <FlaskConical className="h-4 w-4" />, href: "experiments" },
  missing_concepts: { label: "Concept Gaps",    icon: <AlertTriangle className="h-4 w-4" />,href: "missing-concepts" },
  bloom:            { label: "Bloom Analysis",  icon: <Zap className="h-4 w-4" />,          href: "notes" },
  visual_cards:     { label: "Visual Cards",    icon: <ImageOff className="h-4 w-4" />,     href: "notes" },
  homework:         { label: "Homework",        icon: <BookOpen className="h-4 w-4" />,     href: "homework" },
  analogies:             { label: "Analogies",       icon: <Zap className="h-4 w-4" />,          href: "notes" },
  lesson_plan_coverage:  { label: "Lesson Plan",     icon: <BookOpen className="h-4 w-4" />,     href: "lesson-plan" },
  combined_analysis:     { label: "Classroom Snapshot", icon: <ScanLine className="h-4 w-4" />,   href: "class-analysis" },
  session_report:        { label: "Session Report",    icon: <FileText className="h-4 w-4" />,    href: "session-report" },
  absorption_map:        { label: "Absorption Map",    icon: <Zap className="h-4 w-4" />,          href: "absorption-map" },
};

const STATUS_ICON_MAP: Record<string, React.ReactNode> = {
  ready:      <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />,
  processing: <Loader2 className="h-3.5 w-3.5 text-yellow-500 animate-spin" />,
  pending:    <Clock className="h-3.5 w-3.5 text-slate-400" />,
  failed:     <AlertTriangle className="h-3.5 w-3.5 text-red-500" />,
  partial:    <AlertTriangle className="h-3.5 w-3.5 text-orange-400" />,
};

const STATUS_TEXT: Record<string, string> = {
  ready: "text-green-700", processing: "text-yellow-700",
  pending: "text-slate-500", failed: "text-red-600", partial: "text-orange-600",
};

// ─── Delete confirmation dialog ───────────────────────────────────────────────

function DeleteDialog({
  session: s,
  onConfirm,
  onCancel,
  deleting,
}: {
  session: Session;
  onConfirm: () => void;
  onCancel: () => void;
  deleting: boolean;
}) {
  const isActive = s.status === "active" || s.status === "processing";
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}
    >
      <div className="w-full max-w-sm rounded-2xl bg-white shadow-2xl">
        <div className="flex items-start gap-3 border-b border-slate-100 px-5 py-4">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-red-100">
            <Trash2 className="h-4 w-4 text-red-600" />
          </div>
          <div className="min-w-0">
            <p className="font-semibold text-slate-900">Delete session?</p>
            <p className="mt-0.5 truncate text-sm text-slate-500">
              {s.subject ?? "Untitled session"}
            </p>
          </div>
        </div>
        <div className="space-y-3 px-5 py-4">
          {isActive && (
            <div className="flex items-start gap-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2.5">
              <AlertTriangle className="h-4 w-4 shrink-0 text-amber-500 mt-0.5" />
              <p className="text-xs text-amber-700 font-medium leading-relaxed">
                This session is still <strong>active</strong>. Frames being captured
                right now will be lost.
              </p>
            </div>
          )}
          <p className="text-sm text-slate-600">This will permanently remove:</p>
          <ul className="space-y-1 text-sm text-slate-600">
            <li className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-red-400 shrink-0" />
              All {s.frame_count} captured frame{s.frame_count !== 1 ? "s" : ""}
            </li>
            <li className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-red-400 shrink-0" />
              OCR results and AI outputs
            </li>
            <li className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-red-400 shrink-0" />
              Any generated quizzes
            </li>
          </ul>
          <p className="text-xs text-slate-400 font-medium">This action cannot be undone.</p>
        </div>
        <div className="flex gap-2 border-t border-slate-100 px-5 py-4">
          <button
            onClick={onCancel}
            disabled={deleting}
            className="flex-1 rounded-xl border border-slate-200 bg-white py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 transition-colors disabled:opacity-40"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={deleting}
            className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-red-600 py-2.5 text-sm font-semibold text-white hover:bg-red-700 transition-colors disabled:opacity-50"
          >
            {deleting
              ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Deleting…</>
              : <><Trash2 className="h-3.5 w-3.5" /> Delete</>}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Session info card ────────────────────────────────────────────────────────

function InlineEdit({
  value, placeholder, onSave, className,
}: {
  value: string; placeholder: string; onSave: (v: string) => Promise<void>; className?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => { if (editing) inputRef.current?.focus(); }, [editing]);

  async function save() {
    const trimmed = draft.trim();
    if (!trimmed) { setEditing(false); return; }
    setSaving(true);
    try { await onSave(trimmed); setEditing(false); } finally { setSaving(false); }
  }

  if (editing) {
    return (
      <div className="flex items-center gap-1.5">
        <input
          ref={inputRef}
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") save(); if (e.key === "Escape") setEditing(false); }}
          className={cn("flex-1 rounded-lg border border-indigo-300 bg-white px-2.5 py-1 text-sm font-medium text-slate-900 outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500", className)}
        />
        <button onClick={save} disabled={saving} className="rounded-lg bg-indigo-600 p-1.5 text-white hover:bg-indigo-700 disabled:opacity-50">
          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
        </button>
        <button onClick={() => setEditing(false)} className="rounded-lg border border-slate-200 p-1.5 text-slate-500 hover:bg-slate-50">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    );
  }
  return (
    <button onClick={() => { setDraft(value); setEditing(true); }} className="group flex items-center gap-1.5 text-left">
      <span className={cn(value ? "" : "text-slate-400 font-normal italic", className)}>
        {value || placeholder}
      </span>
      <Pencil className="h-3.5 w-3.5 text-slate-300 group-hover:text-indigo-500 transition-colors shrink-0" />
    </button>
  );
}

function SessionInfoCard({
  session,
  onDelete,
  onSubjectSaved,
  onTitleSaved,
  onInstructorSaved,
}: {
  session: Session;
  onDelete: () => void;
  onSubjectSaved: (subject: string) => void;
  onTitleSaved: (title: string) => void;
  onInstructorSaved: (instructorName: string) => void;
}) {
  const isActive = session.status === "active" || session.status === "processing";

  return (
    <Card>
      <CardContent className="pt-4 sm:pt-5">
        <div className="flex items-start gap-3 sm:gap-4">
          <div className={cn(
            "flex h-10 w-10 sm:h-12 sm:w-12 shrink-0 items-center justify-center rounded-xl text-white",
            session.status === "ai_complete" ? "bg-purple-600"
              : isActive ? "bg-green-600" : "bg-indigo-600",
          )}>
            <BookOpen className="h-5 w-5 sm:h-6 sm:w-6" />
          </div>
          <div className="flex-1 min-w-0">
            {/* Session title (prominent, editable) */}
            <div className="flex flex-wrap items-start justify-between gap-2 mb-1">
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <InlineEdit
                    value={session.title ?? ""}
                    placeholder="Tap to set session name…"
                    className="text-base sm:text-lg font-bold text-slate-900 leading-snug"
                    onSave={async (v) => {
                      await api.patchSession(session.session_id, { title: v });
                      onTitleSaved(v);
                    }}
                  />
                  <Badge className={cn("gap-1", STATUS_COLOURS[session.status] ?? "bg-slate-100 text-slate-600")}>
                    {session.status === "active" && <Loader2 className="h-3 w-3 animate-spin" />}
                    {session.status === "ai_complete" && <Cpu className="h-3 w-3" />}
                    {session.status === "completed" && <CheckCircle2 className="h-3 w-3" />}
                    {session.status.replace("_", " ")}
                  </Badge>
                </div>
                {/* Subject + instructor (smaller, editable) */}
                <div className="mt-1 flex flex-wrap items-center gap-x-1.5">
                  <InlineEdit
                    value={session.subject ?? ""}
                    placeholder="Add subject…"
                    className="text-xs text-slate-500"
                    onSave={async (v) => {
                      await api.patchSession(session.session_id, { subject: v });
                      onSubjectSaved(v);
                    }}
                  />
                  <span className="text-xs text-slate-300">·</span>
                  <InlineEdit
                    value={session.instructor_name ?? ""}
                    placeholder="Add instructor…"
                    className="text-xs text-slate-500"
                    onSave={async (v) => {
                      await api.patchSession(session.session_id, { instructor_name: v });
                      onInstructorSaved(v);
                    }}
                  />
                </div>
              </div>

              <button
                onClick={onDelete}
                className="flex items-center gap-1 rounded-lg border border-red-200 bg-red-50 px-2.5 py-1.5 text-[0.6875rem] font-semibold text-red-600 hover:bg-red-100 transition-colors shrink-0"
                title="Delete this session"
              >
                <Trash2 className="h-3 w-3" />
                <span className="hidden xs:inline">Delete</span>
              </button>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-3 mt-1">
              <InfoCell label="Grade" value={session.grade ?? "—"} />
              <InfoCell label="Board" value={session.board_type} />
              <InfoCell label="Frames" value={String(session.frame_count)} />
              <InfoCell
                label="Started"
                value={session.started_at ? timeAgo(session.started_at) : timeAgo(session.created_at)}
              />
            </div>

            {session.completed_at && (
              <p className="mt-2 text-xs text-slate-400">
                Completed {formatDateTime(session.completed_at)}
              </p>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function InfoCell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-slate-400 mb-0.5">{label}</p>
      <p className="text-sm font-medium text-slate-800 capitalize">{value}</p>
    </div>
  );
}

// ─── AI outputs grid ──────────────────────────────────────────────────────────

function OutputsGrid({ sessionId, outputs }: { sessionId: string; outputs: SessionOutputs }) {
  const entries = Object.entries(outputs.outputs);
  if (entries.length === 0) return null;

  const readyCount = entries.filter(([, v]) => v.status === "ready").length;
  const totalTokens = outputs.total_tokens;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Cpu className="h-4 w-4 text-purple-600" />
          <CardTitle>AI Outputs</CardTitle>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-500">{readyCount} / {entries.length} ready</span>
          {totalTokens > 0 && (
            <span className="flex items-center gap-1 text-xs font-medium text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded-full">
              <Coins className="h-3 w-3" />
              {totalTokens.toLocaleString()} tokens
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <ul className="divide-y divide-slate-100">
          {entries.map(([key, val]) => {
            const meta = OUTPUT_META[key];
            if (!meta) return null;
            return (
              <li key={key}>
                <Link href={`/sessions/${sessionId}/${meta.href}`}>
                  <div className="flex items-center justify-between px-4 sm:px-5 py-3 hover:bg-slate-50 transition-colors">
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="text-slate-400 shrink-0">{meta.icon}</span>
                      <span className="text-sm text-slate-700">{meta.label}</span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0 ml-2">
                      {val.tokens_used > 0 && (
                        <span className="flex items-center gap-0.5 text-[0.625rem] text-slate-400">
                          <Coins className="h-3 w-3" />
                          {val.tokens_used.toLocaleString()}
                        </span>
                      )}
                      <span className={cn("flex items-center gap-1 text-xs font-medium", STATUS_TEXT[val.status])}>
                        {STATUS_ICON_MAP[val.status]}
                        <span className="hidden sm:inline">{val.status}</span>
                      </span>
                      <ChevronRight className="h-3.5 w-3.5 text-slate-300" />
                    </div>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}

// ─── Quick actions ─────────────────────────────────────────────────────────────

function QuickActions({ sessionId, session }: { sessionId: string; session: Session }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Quick Actions</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <ActionButton href={`/sessions/${sessionId}/capture`} icon={<Camera className="h-4 w-4" />} label="Capture" colour="bg-green-600" />
        <ActionButton href={`/sessions/${sessionId}/notes`}   icon={<FileText className="h-4 w-4" />} label="View Notes" colour="bg-indigo-600" />
        <ActionButton href={`/sessions/${sessionId}/quiz`}    icon={<HelpCircle className="h-4 w-4" />} label="Quiz" colour="bg-blue-600" />
        <ActionButton href={`/sessions/${sessionId}/experiments`} icon={<FlaskConical className="h-4 w-4" />} label="Experiments" colour="bg-teal-600" />
        <ActionButton href={`/sessions/${sessionId}/missing-concepts`} icon={<AlertTriangle className="h-4 w-4" />} label="Opportunities" colour="bg-orange-500" />
        <ActionButton href={`/sessions/${sessionId}/tiqer`}   icon={<Zap className="h-4 w-4" />} label="TiQer Export" colour="bg-purple-600" />
        <ActionButton href={`/sessions/${sessionId}/lesson-plan`} icon={<BookOpen className="h-4 w-4" />} label="Lesson Plan" colour="bg-rose-600" />
        <ActionButton href={`/sessions/${sessionId}/class-analysis`} icon={<ScanLine className="h-4 w-4" />} label="Classroom Snapshot" colour="bg-cyan-600" />
      </CardContent>
    </Card>
  );
}

function ActionButton({
  href, icon, label, colour,
}: { href: string; icon: React.ReactNode; label: string; colour: string }) {
  return (
    <Link href={href}>
      <div className={cn(
        "flex flex-col items-center gap-2 rounded-xl p-3 text-white text-center text-xs font-medium",
        "hover:opacity-90 active:scale-95 transition-all cursor-pointer",
        colour,
      )}>
        {icon}
        {label}
      </div>
    </Link>
  );
}

// ─── Summary excerpt ──────────────────────────────────────────────────────────

function SummaryCard({ outputs }: { outputs: SessionOutputs }) {
  const summary = outputs.outputs?.summary;
  if (!summary || summary.status !== "ready") return null;
  const text = summary.data?.text as string | undefined;
  if (!text) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Class Summary</CardTitle>
        <CheckCircle2 className="h-4 w-4 text-green-500" />
      </CardHeader>
      <CardContent>
        <p className="text-sm text-slate-700 leading-relaxed">{text}</p>
      </CardContent>
    </Card>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function SessionOverviewPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = use(params);
  const router = useRouter();
  const [generating, setGenerating] = useState(false);
  const [genMsg, setGenMsg] = useState("");
  const [reprocessing, setReprocessing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [subjectOverride, setSubjectOverride] = useState<string | null>(null);
  const [titleOverride, setTitleOverride] = useState<string | null>(null);
  const [instructorOverride, setInstructorOverride] = useState<string | null>(null);

  const { data: session, error: sessErr, isLoading: sessLoading } =
    useSWR(["session", sessionId], () => api.getSession(sessionId), { refreshInterval: 15000 });

  const { data: outputs, mutate: mutateOutputs } = useSWR(
    session ? ["outputs", sessionId] : null,
    () => fetchOutputsCached(sessionId),
    {
      refreshInterval: (data) => {
        const hasProcessing = Object.values(data?.outputs ?? {}).some(
          o => o.status === "pending" || o.status === "processing",
        );
        return hasProcessing ? 5000 : 30000;
      },
    },
  );

  // Poll for AI completion events so outputs refresh without a manual reload
  useEventPoller({
    sessionId,
    onOutputReady: () => mutateOutputs(),
    onAudioTranscribed: () => mutateOutputs(),
    enabled: !!session,
  });

  // Additional data for the Command Center's "continue teaching" hero only —
  // the classic view below never reads this, so it can't be affected by it.
  const { data: textbooksData } = useSWR(
    session ? ["textbooks-hero", sessionId] : null,
    () => api.listTextbooks(sessionId),
    { revalidateOnFocus: false }
  );

  const { version, toggle: toggleDesign } = useDesignVersion("overview");

  async function handleGenerate() {
    setGenerating(true);
    setGenMsg("");
    try {
      await api.triggerGeneration(sessionId);
      setGenMsg("Generation started — outputs will appear in ~2 minutes.");
      mutateOutputs();
    } catch (err: unknown) {
      setGenMsg(err instanceof Error ? err.message : "Failed to trigger generation.");
    } finally {
      setGenerating(false);
    }
  }

  async function handleReprocessOCR() {
    setReprocessing(true);
    setGenMsg("");
    try {
      const res = await api.reprocessOCR(sessionId);
      setGenMsg(`Re-running OCR on ${res.queued} frame(s) with the improved engine — this takes ~30s per frame. Then click "Generate AI".`);
    } catch (err: unknown) {
      setGenMsg(err instanceof Error ? err.message : "Failed to reprocess OCR.");
    } finally {
      setReprocessing(false);
    }
  }

  async function handleDeleteConfirmed() {
    setDeleting(true);
    try {
      await api.deleteSession(sessionId);
      router.push("/sessions");
    } catch (err: unknown) {
      setDeleting(false);
      setConfirmDelete(false);
      setGenMsg(err instanceof Error ? err.message : "Failed to delete session.");
    }
  }

  if (sessLoading) return <LoadingScreen label="Loading session…" />;
  if (sessErr || !session) return (
    <div className="flex flex-col items-center gap-3 py-16 text-slate-400">
      <AlertTriangle className="h-8 w-8 text-red-400" />
      <p className="text-sm">Session not found.</p>
      <Link href="/sessions"><Button variant="secondary" size="sm">Back to Sessions</Button></Link>
    </div>
  );

  const hasOutputs = outputs && Object.keys(outputs.outputs).length > 0;
  const anyReady = hasOutputs && Object.values(outputs.outputs).some(o => o.status === "ready");

  return (
    <div className="space-y-5">
      {/* Delete confirmation dialog */}
      {confirmDelete && (
        <DeleteDialog
          session={session}
          onConfirm={handleDeleteConfirmed}
          onCancel={() => setConfirmDelete(false)}
          deleting={deleting}
        />
      )}

      {/* Classic/Command Center toggle — switching back is always one click, no reload lost */}
      <div className="flex justify-end">
        <button
          onClick={toggleDesign}
          className="flex items-center gap-1.5 text-xs font-medium text-indigo-600 hover:text-indigo-800 transition-colors"
        >
          {version === "premium"
            ? <><History className="h-3.5 w-3.5" /> Switch to classic view</>
            : <><Sparkles className="h-3.5 w-3.5" /> Try the new Command Center</>}
        </button>
      </div>

      {version === "premium" && (
        <CommandCenter sessionId={sessionId} textbooks={textbooksData?.textbooks} />
      )}

      {/* Session info */}
      <SessionInfoCard
        session={{
          ...session,
          ...(subjectOverride !== null ? { subject: subjectOverride } : {}),
          ...(titleOverride !== null ? { title: titleOverride } : {}),
          ...(instructorOverride !== null ? { instructor_name: instructorOverride } : {}),
        }}
        onDelete={() => setConfirmDelete(true)}
        onSubjectSaved={setSubjectOverride}
        onTitleSaved={setTitleOverride}
        onInstructorSaved={setInstructorOverride}
      />

      {/* Generate button / message */}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          loading={generating}
          onClick={handleGenerate}
          className={cn(!anyReady && "animate-pulse")}
        >
          <Cpu className="h-4 w-4" />
          {anyReady ? "Re-generate AI" : "Generate AI Notes & Quiz"}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          loading={reprocessing}
          onClick={handleReprocessOCR}
          title="Re-run OCR on all frames using the latest improved engine, then generate AI"
        >
          <ScanLine className="h-3.5 w-3.5" />
          Re-process OCR
        </Button>
        <Link href={`/sessions/${sessionId}/capture`}>
          <Button variant="secondary" size="sm">
            <Camera className="h-4 w-4" /> Capture More
          </Button>
        </Link>
        <Button variant="secondary" size="sm" onClick={() => mutateOutputs()}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      {genMsg && (
        <div className="rounded-lg bg-indigo-50 px-4 py-3 text-sm text-indigo-700">{genMsg}</div>
      )}

      {/* Layout: summary + outputs on left, actions on right */}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-4">
          {outputs && <SummaryCard outputs={outputs} />}
          {outputs && <OutputsGrid sessionId={sessionId} outputs={outputs} />}

          {!hasOutputs && (
            <Card>
              <CardContent className="py-14 flex flex-col items-center gap-3 text-slate-400">
                <Cpu className="h-10 w-10" />
                <p className="text-sm">No AI outputs yet.</p>
                <p className="text-xs text-slate-400 text-center max-w-xs">
                  Capture board photos first, then click "Generate AI Notes &amp; Quiz" above.
                </p>
              </CardContent>
            </Card>
          )}
        </div>

        <div className="space-y-4">
          {/* Command Center's Activity Grid above already covers every one
              of these links (and more) — avoid showing the same tiles twice. */}
          {version === "classic" && <QuickActions sessionId={sessionId} session={session} />}

          {/* Session stats */}
          <Card>
            <CardHeader><CardTitle className="text-sm">Session Info</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm">
              <InfoRow label="Session ID" value={sessionId.slice(0, 8) + "…"} />
              <InfoRow label="Capture Mode" value={session.capture_mode.replace("_", " ")} />
              <InfoRow label="Interval" value={`${session.capture_interval_sec}s`} />
              <InfoRow label="Sync Status" value={session.sync_status} />
              <InfoRow label="Created" value={formatDateTime(session.created_at)} />
              {outputs && outputs.total_tokens > 0 && (
                <>
                  <div className="border-t border-slate-100 pt-2 mt-2">
                    <div className="flex justify-between items-center text-xs">
                      <span className="text-slate-500">AI Tokens Used</span>
                      <span className="font-semibold text-indigo-700">{outputs.total_tokens.toLocaleString()}</span>
                    </div>
                    <div className="mt-1.5 space-y-0.5">
                      {Object.entries(outputs.outputs)
                        .filter(([, v]) => v.tokens_used > 0)
                        .sort(([, a], [, b]) => b.tokens_used - a.tokens_used)
                        .map(([key, val]) => (
                          <div key={key} className="flex justify-between items-center text-[0.6875rem]">
                            <span className="text-slate-400 capitalize">{key.replace(/_/g, " ")}</span>
                            <span className="text-slate-500">{val.tokens_used.toLocaleString()}</span>
                          </div>
                        ))
                      }
                    </div>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between items-center text-xs">
      <span className="text-slate-500">{label}</span>
      <span className="text-slate-700 font-medium capitalize">{value}</span>
    </div>
  );
}
