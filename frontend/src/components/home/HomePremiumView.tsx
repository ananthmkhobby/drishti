"use client";

// Premium redesign of the Session History page — the actual app homepage.
// Same data, same handlers, same DeleteConfirmDialog/delete flow as the
// classic view (via homeShared) — only the visual language changes. See
// useDesignVersion for the classic/premium toggle this is gated behind,
// and CommandCenter.tsx for the matching Overview-page redesign this
// follows (Fraunces display serif, warm paper ground, indigo/gold accents).

import { useState } from "react";
import Link from "next/link";
import {
  BookOpen, Upload, Cpu, FileText, Plus, ArrowRight,
  Clock, Loader2, AlertCircle, PlayCircle,
  ChevronRight, Settings2, Pencil, Trash2, WifiOff, GitCompare,
  Sparkles, Layers, CloudOff,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { api, type Session } from "@/lib/api";
import { removePendingSession, type PendingSession } from "@/lib/offline-store";
import { timeAgo, cn } from "@/lib/utils";
import { classroomLabel } from "@/lib/classroom-settings";
import { DeleteConfirmDialog, useDeleteSession } from "@/components/home/homeShared";
import { findHeroChapter } from "@/components/session/CommandCenter";
import type { HomeViewProps } from "@/components/home/HomeViewProps";

const SERIF = { fontFamily: "var(--font-fraunces), Georgia, serif" };

const STATUS_META: Record<string, { label: string; fg: string; bg: string }> = {
  active:      { label: "Active",      fg: "#3E7A57", bg: "#E7F1EA" },
  processing:  { label: "Processing",  fg: "#8A5D1E", bg: "#F6EAD3" },
  ai_complete: { label: "AI ready",    fg: "#453B87", bg: "#EDEAF9" },
  completed:   { label: "Completed",   fg: "#57534E", bg: "#F1EFEA" },
  failed:      { label: "Failed",      fg: "#B4432D", bg: "#FBEAE6" },
};

function PremiumStat({ label, value, accent }: { label: string; value: number; accent: string }) {
  return (
    <div className="bg-white rounded-2xl p-4 sm:p-5 shadow-[0_4px_14px_rgba(23,22,27,0.05)]">
      <p className="text-[0.6875rem] font-bold uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-1.5 text-3xl font-semibold tabular-nums" style={{ ...SERIF, color: accent }}>{value}</p>
    </div>
  );
}

function PremiumClassroomBanner({ settings }: { settings: HomeViewProps["classroom"] }) {
  const router = useRouter();

  if (!settings) {
    return (
      <button
        onClick={() => router.push("/sessions/new")}
        className="flex w-full items-center gap-3 rounded-2xl border border-dashed px-4 py-3.5 text-sm text-left transition-colors hover:bg-[#EDEAF9]/60"
        style={{ borderColor: "#C9C1E8", background: "#F7F5FC", color: "#332B6B" }}
      >
        <Settings2 className="h-4 w-4 shrink-0" />
        <span>
          <strong>Set up your classroom once</strong> — grade and board type will auto-fill for every session.
        </span>
        <ChevronRight className="h-4 w-4 ml-auto shrink-0" />
      </button>
    );
  }

  return (
    <div className="flex items-center justify-between rounded-2xl bg-white px-4 py-3 shadow-[0_4px_14px_rgba(23,22,27,0.05)]">
      <div className="flex items-center gap-2.5">
        <Settings2 className="h-4 w-4 text-slate-400" />
        <div>
          <span className="text-xs text-slate-500 mr-2">Classroom:</span>
          <span className="text-sm font-medium text-slate-800">{classroomLabel(settings)}</span>
          <span className="mx-1.5 text-slate-300">·</span>
          <span className="text-xs text-slate-500 capitalize">{settings.boardType}</span>
        </div>
      </div>
      <button
        onClick={() => router.push("/sessions/new")}
        className="flex items-center gap-1 text-xs font-medium hover:opacity-70"
        style={{ color: "#241F49" }}
      >
        <Pencil className="h-3 w-3" /> Edit
      </button>
    </div>
  );
}

function PremiumSessionCard({ session: s, onDeleted, index = 0 }: { session: Session; onDeleted: (id: string) => void; index?: number }) {
  const router = useRouter();
  const { confirmOpen, setConfirmOpen, deleting, handleDeleteConfirmed } = useDeleteSession(s.session_id, onDeleted);
  const isActive = s.status === "active" || s.status === "processing";
  const hasAI = s.status === "ai_complete";
  const meta = STATUS_META[s.status] ?? { label: s.status.replace("_", " "), fg: "#57534E", bg: "#F1EFEA" };
  const [resolvingTeach, setResolvingTeach] = useState(false);

  // Same resume-or-start-fresh logic as the voice assistant's bare
  // "continue"/"start teaching" (see start_teaching in ClassroomBrain.tsx,
  // and CommandCenter.tsx's own "Continue teaching" hero) — jumps straight
  // to the most recently-taught chapter, or the first chapter of the
  // first ready textbook if nothing's been started yet, instead of making
  // a teacher go Session -> Textbook tab -> find the chapter -> Start
  // every single time. Falls back to the Textbook tab itself if there's
  // nothing to resolve yet (no textbook uploaded) — the click always does
  // something useful rather than silently no-op-ing.
  async function startTeaching(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setResolvingTeach(true);
    try {
      const { textbooks } = await api.listTextbooks(s.session_id);
      const hero = findHeroChapter(textbooks);
      const target = hero
        ? { textbookId: hero.textbookId, chapterId: hero.chapter.chapter_id }
        : (() => {
            const first = textbooks
              .filter((tb) => tb.status === "ready")
              .flatMap((tb) => (tb.chapters ?? []).map((ch) => ({ tb, ch })))
              .sort((a, b) => a.ch.order_index - b.ch.order_index)[0];
            return first ? { textbookId: first.tb.textbook_id, chapterId: first.ch.chapter_id } : null;
          })();
      router.push(target ? `/sessions/${s.session_id}/textbook/${target.textbookId}/${target.chapterId}` : `/sessions/${s.session_id}/textbook`);
    } catch {
      router.push(`/sessions/${s.session_id}/textbook`);
    } finally {
      setResolvingTeach(false);
    }
  }

  return (
    <>
      {confirmOpen && (
        <DeleteConfirmDialog
          session={s}
          onConfirm={handleDeleteConfirmed}
          onCancel={() => setConfirmOpen(false)}
          deleting={deleting}
        />
      )}

      <Link href={`/sessions/${s.session_id}`} className="hp-rise block group" style={{ animationDelay: `${Math.min(index, 8) * 45}ms` }}>
        <div className={cn(
          "bg-white rounded-2xl p-4 sm:p-5 flex items-start gap-4 shadow-[0_4px_14px_rgba(23,22,27,0.05)] transition-all",
          "group-hover:-translate-y-0.5 group-hover:shadow-[0_14px_32px_rgba(23,22,27,0.10)]",
        )}>
          <div
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl"
            style={{ background: hasAI ? "#EDEAF9" : isActive ? "#E7F1EA" : "#F6EAD3", color: hasAI ? "#453B87" : isActive ? "#3E7A57" : "#8A5D1E" }}
          >
            {hasAI ? <Cpu className="h-5 w-5" /> : <BookOpen className="h-5 w-5" />}
          </div>

          <div className="min-w-0 flex-1">
            {s.title && (
              <div className="text-sm font-bold text-slate-900 break-words" style={SERIF}>{s.title}</div>
            )}
            <div className="flex flex-wrap items-center gap-1.5 mt-0.5">
              <span className={cn("break-words", s.title ? "text-xs text-slate-500" : "text-sm font-semibold text-slate-900")}>
                {s.subject ?? <span className="text-slate-400 italic font-normal">No subject set</span>}
                {s.grade ? <span className={s.title ? "" : "text-slate-500 font-normal"}> · {s.grade}</span> : ""}
                {s.instructor_name ? <span className={s.title ? "" : "text-slate-500 font-normal"}> · {s.instructor_name}</span> : ""}
              </span>
              <span
                className="text-[0.625rem] font-bold px-2 py-0.5 rounded-full"
                style={{ background: meta.bg, color: meta.fg }}
              >
                {meta.label}
              </span>
              {hasAI && (
                <span className="text-[0.625rem] font-bold px-2 py-0.5 rounded-full flex items-center gap-1" style={{ background: "#F6EAD3", color: "#8A5D1E" }}>
                  <Sparkles className="h-2.5 w-2.5" /> AI Ready
                </span>
              )}
            </div>

            <div className="mt-1.5 flex flex-wrap items-center gap-3 text-xs text-slate-500">
              <span className="flex items-center gap-1"><Clock className="h-3 w-3" /> {timeAgo(s.created_at)}</span>
              <span>{s.frame_count} frame{s.frame_count !== 1 ? "s" : ""}</span>
              <span className="capitalize">{s.sync_status}</span>
            </div>

            <div className="mt-2.5 flex items-center gap-1.5">
              <button
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); router.push(`/sessions/${s.session_id}/capture`); }}
                className="hidden sm:flex rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors"
                title="Capture frames"
              ><Upload className="h-3.5 w-3.5" /></button>
              <button
                onClick={startTeaching}
                disabled={resolvingTeach}
                className="hidden sm:flex rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors disabled:opacity-50"
                title="Start teaching"
              >{resolvingTeach ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <PlayCircle className="h-3.5 w-3.5" />}</button>
              <button
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); router.push(`/sessions/${s.session_id}/notes`); }}
                className="hidden sm:flex rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors"
                title="AI notes"
              ><FileText className="h-3.5 w-3.5" /></button>
              <button
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); setConfirmOpen(true); }}
                disabled={deleting}
                title="Delete session"
                className="flex items-center gap-1 rounded-lg border border-red-200 bg-red-50 px-2 py-1 text-[0.6875rem] font-semibold text-red-500 hover:bg-red-100 transition-colors disabled:opacity-40"
              >
                {deleting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
                <span className="hidden sm:inline">Delete</span>
              </button>
            </div>
          </div>

          <ArrowRight className="h-4 w-4 text-slate-300 shrink-0 mt-1.5 group-hover:text-slate-500 transition-colors" />
        </div>
      </Link>
    </>
  );
}

function PremiumOfflineCard({ session: s, onDiscarded }: { session: PendingSession; onDiscarded: (id: string) => void }) {
  const [discarding, setDiscarding] = useState(false);

  async function handleDiscard(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setDiscarding(true);
    try {
      await removePendingSession(s.id);
      onDiscarded(s.id);
    } catch {
      setDiscarding(false);
    }
  }

  const isSyncing = s.status === "syncing";
  const isFailed  = s.status === "failed";
  const label     = s.payload.grade ?? "Session";

  return (
    <Link href={`/sessions/${s.id}/capture`} className="block group">
      <div
        className="rounded-2xl p-4 sm:p-5 flex items-start gap-4 shadow-[0_4px_14px_rgba(23,22,27,0.05)] transition-all group-hover:-translate-y-0.5"
        style={{ background: "#FBF6EC", border: "1px solid #F0DFB5" }}
      >
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl" style={{ background: "#F6EAD3", color: "#8A5D1E" }}>
          {isSyncing ? <Loader2 className="h-5 w-5 animate-spin" /> : <CloudOff className="h-5 w-5" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-sm font-semibold text-slate-900">{label}</span>
            <span
              className="text-[0.625rem] font-bold px-2 py-0.5 rounded-full flex items-center gap-1"
              style={{ background: isFailed ? "#FBEAE6" : "#F6EAD3", color: isFailed ? "#B4432D" : "#8A5D1E" }}
            >
              {isFailed ? <AlertCircle className="h-2.5 w-2.5" /> : <WifiOff className="h-2.5 w-2.5" />}
              {isFailed ? "Sync failed" : isSyncing ? "Syncing…" : "Offline"}
            </span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span className="flex items-center gap-1"><Clock className="h-3 w-3" /> {timeAgo(new Date(s.createdAt).toISOString())}</span>
            <span className="capitalize">{s.payload.board_type?.replace("_", " ")}</span>
            {isFailed && s.errorMessage && <span className="text-red-500 truncate max-w-[12.5rem]">{s.errorMessage}</span>}
          </div>
          <div className="mt-2.5">
            <button
              onClick={handleDiscard}
              disabled={discarding}
              title="Discard offline session"
              className="flex items-center gap-1 rounded-lg border border-red-200 bg-red-50 px-2 py-1 text-[0.6875rem] font-semibold text-red-500 hover:bg-red-100 transition-colors disabled:opacity-40"
            >
              {discarding ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
              <span className="hidden sm:inline">Discard</span>
            </button>
          </div>
        </div>
        <ChevronRight className="h-4 w-4 text-slate-300 shrink-0 mt-1.5" />
      </div>
    </Link>
  );
}

export function HomePremiumView(p: HomeViewProps) {
  const {
    filter, setFilter, classroom, offlineSessions, setOfflineSessions,
    fromCache, sessions, filtered, counts, groups, mutate, designToggle,
    matchGrade, matchSection, matchingSessions,
  } = p;
  const onSessionDeleted = (id: string) => mutate(
    (prev) => prev
      ? { ...prev, sessions: prev.sessions.filter(x => x.session_id !== id) }
      : prev,
    false,
  );

  return (
    <div className="space-y-7 pb-4">
      <style>{`
        @keyframes hp-rise { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes hp-drift { 0%,100% { transform: translate(0,0) scale(1); } 50% { transform: translate(18px,-12px) scale(1.06); } }
        .hp-rise { animation: hp-rise 560ms cubic-bezier(0.16,1,0.3,1) both; }
        .hp-drift { animation: hp-drift 12s ease-in-out infinite; }
        @media (prefers-reduced-motion: reduce) {
          .hp-rise, .hp-drift { animation: none !important; }
        }
      `}</style>

      {/* Hero header */}
      <div
        className="relative overflow-hidden rounded-3xl px-6 py-8 sm:px-9 sm:py-10 flex flex-col sm:flex-row sm:items-end sm:justify-between gap-5"
        style={{ background: "linear-gradient(135deg, #241F49 0%, #332B6B 100%)" }}
      >
        {/* Ambient glow — quiet, continuous motion so the hero never feels static */}
        <div className="hp-drift pointer-events-none absolute -right-10 -top-16 h-64 w-64 rounded-full opacity-25 blur-[70px]" style={{ background: "#D7A24E" }} />
        <div className="hp-rise relative">
          <span className="text-[0.6875rem] font-bold tracking-wide text-white/60 uppercase">Drishti</span>
          <h1 className="mt-1.5 text-3xl sm:text-4xl font-semibold text-white tracking-tight" style={SERIF}>
            Your classroom sessions
          </h1>
          <p className="mt-2 text-sm text-white/70 max-w-md">
            Every lesson you&apos;ve captured or taught, in one place.
          </p>
        </div>
        <div className="hp-rise relative flex items-center gap-2.5 shrink-0" style={{ animationDelay: "80ms" }}>
          <Link
            href="/sessions/compare"
            className="inline-flex items-center gap-2 rounded-xl border border-white/25 text-white px-4 py-2.5 text-sm font-semibold hover:bg-white/10 transition-colors"
          >
            <GitCompare className="h-4 w-4" /> Compare
          </Link>
          <Link
            href="/sessions/new"
            className="inline-flex items-center gap-2 rounded-xl bg-white text-[#241F49] px-5 py-2.5 text-sm font-bold hover:bg-white/90 hover:scale-[1.03] transition-all"
          >
            <Plus className="h-4 w-4" /> New Session
          </Link>
        </div>
      </div>

      {/* Today's class, from attendance — only present when arriving from
          Welcome (see (dashboard)/sessions/page.tsx), so a teacher with
          several sessions today doesn't have to scroll the full list
          below to find this one. Additive, not a filter: today's session
          still appears again in its normal date group further down. */}
      {matchGrade && (
        <div className="hp-rise rounded-3xl bg-white p-5 shadow-[0_4px_14px_rgba(23,22,27,0.05)]" style={{ border: "1px solid #EDEAF9" }}>
          <h2 className="mb-3 text-xs font-bold uppercase tracking-wider" style={{ color: "#453B87" }}>
            Grade {matchGrade}{matchSection ? ` · Section ${matchSection}` : ""}
          </h2>
          {matchingSessions.length > 0 ? (
            <div className="space-y-2.5">
              {matchingSessions.map((s, idx) => (
                <PremiumSessionCard key={s.session_id} session={s} index={idx} onDeleted={onSessionDeleted} />
              ))}
            </div>
          ) : (
            <p className="text-sm text-slate-500">
              No sessions yet for Grade {matchGrade} —{" "}
              <Link href="/sessions/new" className="font-semibold hover:underline" style={{ color: "#453B87" }}>start one</Link>.
            </p>
          )}
        </div>
      )}

      {/* Classic/premium toggle */}
      <div className="flex justify-end -mt-3">{designToggle}</div>

      {/* Offline cache banner */}
      {fromCache && (
        <div className="flex items-center gap-2 rounded-2xl px-4 py-3" style={{ background: "#FBF6EC", border: "1px solid #F0DFB5" }}>
          <AlertCircle className="h-4 w-4 shrink-0" style={{ color: "#8A5D1E" }} />
          <span className="text-[0.8125rem]" style={{ color: "#6B4C16" }}>
            You&apos;re viewing cached sessions from your last sync. Some sessions may be missing until you reconnect.
          </span>
        </div>
      )}

      <PremiumClassroomBanner settings={classroom} />

      {/* Stats */}
      <div className="hp-rise grid grid-cols-2 gap-3 sm:grid-cols-4" style={{ animationDelay: "120ms" }}>
        <PremiumStat label="Total Sessions" value={counts.total} accent="#241F49" />
        <PremiumStat label="Active Now" value={counts.active} accent="#3E7A57" />
        <PremiumStat label="AI Complete" value={counts.completed} accent="#453B87" />
        <PremiumStat label="Sync Backlog" value={counts.offlineBacklog} accent="#8A5D1E" />
      </div>

      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        {(["all","active","completed","ai_complete"] as const).map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className="rounded-full px-3.5 py-1.5 text-xs font-semibold transition-colors"
            style={filter === f
              ? { background: "#241F49", color: "white" }
              : { background: "white", color: "#57534E", boxShadow: "0 1px 0 rgba(0,0,0,0.05)" }
            }
          >
            {f === "all" ? "All" : f === "ai_complete" ? "AI Complete" : f.charAt(0).toUpperCase() + f.slice(1)}
            {f !== "all" && (
              <span className="ml-1.5 rounded-full px-1.5 py-0.5 text-[0.625rem]" style={{ background: filter === f ? "rgba(255,255,255,0.2)" : "#F1EFEA" }}>
                {sessions.filter(s => s.status === f).length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Offline (not yet synced) sessions */}
      {offlineSessions.length > 0 && (
        <div>
          <h2 className="mb-2.5 text-xs font-bold uppercase tracking-wider" style={{ color: "#8A5D1E" }}>
            Pending upload <span className="font-normal normal-case opacity-60">({offlineSessions.length})</span>
          </h2>
          <div className="space-y-2.5">
            {offlineSessions.map(s => (
              <PremiumOfflineCard
                key={s.id}
                session={s}
                onDiscarded={(id) => setOfflineSessions(prev => prev.filter(x => x.id !== id))}
              />
            ))}
          </div>
        </div>
      )}

      {/* Session list — grouped by date */}
      {filtered.length === 0 && offlineSessions.length === 0 ? (
        <div className="bg-white rounded-3xl px-6 py-14 flex flex-col items-center text-center gap-4 shadow-[0_4px_14px_rgba(23,22,27,0.05)]">
          <div className="w-16 h-16 rounded-full flex items-center justify-center" style={{ background: "#EDEAF9" }}>
            <Layers className="h-7 w-7" style={{ color: "#453B87" }} />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-slate-900" style={SERIF}>No sessions yet</h3>
            <p className="mt-1 text-sm text-slate-500 max-w-sm">
              Create a session, then capture board photos to get AI-generated notes and quizzes.
            </p>
          </div>
          <Link
            href="/sessions/new"
            className="inline-flex items-center gap-2 rounded-xl text-white px-5 py-2.5 text-sm font-bold hover:opacity-90 transition-opacity"
            style={{ background: "#241F49" }}
          >
            <Plus className="h-4 w-4" /> New Session
          </Link>
        </div>
      ) : filtered.length > 0 ? (
        <div className="space-y-7">
          {groups.map(({ label, items }) => (
            <div key={label}>
              <h2 className="mb-2.5 text-xs font-bold uppercase tracking-wider text-slate-400">
                {label} <span className="text-slate-300 normal-case font-normal">({items.length})</span>
              </h2>
              <div className="space-y-2.5">
                {items.map((s, idx) => (
                  <PremiumSessionCard key={s.session_id} session={s} index={idx} onDeleted={onSessionDeleted} />
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
