"use client";

// The original Session History page, extracted verbatim (same classNames,
// same structure, zero logic changes) into a props-driven component — the
// guaranteed-safe fallback behind the classic/premium toggle. All state,
// data-fetching and handlers live in the parent page component; this file
// only renders.

import { useState } from "react";
import Link from "next/link";
import {
  BookOpen, Upload, Cpu, FileText, Plus, PlayCircle,
  Clock, CheckCircle2, Loader2, AlertCircle,
  ChevronRight, Settings2, Pencil, Trash2, WifiOff, GitCompare,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { api, type Session } from "@/lib/api";
import { removePendingSession, type PendingSession } from "@/lib/offline-store";
import { timeAgo, STATUS_COLOURS, SYNC_COLOURS, cn } from "@/lib/utils";
import { classroomLabel } from "@/lib/classroom-settings";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Empty } from "@/components/ui/Empty";
import { DeleteConfirmDialog, useDeleteSession } from "@/components/home/homeShared";
import { findHeroChapter } from "@/components/session/CommandCenter";
import type { HomeViewProps } from "@/components/home/HomeViewProps";

const STATUS_ICON: Record<string, React.ReactNode> = {
  active:      <Loader2 className="h-3.5 w-3.5 animate-spin" />,
  completed:   <CheckCircle2 className="h-3.5 w-3.5" />,
  ai_complete: <Cpu className="h-3.5 w-3.5" />,
  processing:  <Loader2 className="h-3.5 w-3.5 animate-spin" />,
  failed:      <AlertCircle className="h-3.5 w-3.5" />,
};

const SYNC_ICON: Record<string, React.ReactNode> = {
  synced:  <span className="h-2 w-2 rounded-full bg-green-500" />,
  syncing: <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" />,
  pending: <span className="h-2 w-2 rounded-full bg-slate-300" />,
  failed:  <span className="h-2 w-2 rounded-full bg-orange-400" />,
};

function Stat({ label, value, colour }: { label: string; value: number; colour: string }) {
  return (
    <Card className="p-4">
      <p className="text-xs text-slate-500">{label}</p>
      <p className={cn("mt-1 text-2xl font-bold", colour)}>{value}</p>
    </Card>
  );
}

function ClassroomBanner({ settings }: { settings: HomeViewProps["classroom"] }) {
  const router = useRouter();

  if (!settings) {
    return (
      <button
        onClick={() => router.push("/sessions/new")}
        className="flex w-full items-center gap-3 rounded-xl border border-dashed border-indigo-200 bg-indigo-50 px-4 py-3 text-sm text-indigo-700 hover:border-indigo-400 transition-colors text-left"
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
    <div className="flex items-center justify-between rounded-xl bg-slate-50 border border-slate-200 px-4 py-2.5">
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
        className="flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-800 font-medium"
      >
        <Pencil className="h-3 w-3" /> Edit
      </button>
    </div>
  );
}

function SessionRow({ session: s, onDeleted }: { session: Session; onDeleted: (id: string) => void }) {
  const router = useRouter();
  const { confirmOpen, setConfirmOpen, deleting, handleDeleteConfirmed } = useDeleteSession(s.session_id, onDeleted);
  const isActive = s.status === "active" || s.status === "processing";
  const hasAI = s.status === "ai_complete";
  const [resolvingTeach, setResolvingTeach] = useState(false);

  // Same shortcut as the premium view — see its matching comment for why
  // (resume-or-start-fresh, same logic the voice assistant's bare
  // "continue"/"start teaching" already uses).
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
      {/* Confirmation dialog (rendered at root so it overlays everything) */}
      {confirmOpen && (
        <DeleteConfirmDialog
          session={s}
          onConfirm={handleDeleteConfirmed}
          onCancel={() => setConfirmOpen(false)}
          deleting={deleting}
        />
      )}

      <Link href={`/sessions/${s.session_id}`} className="block">
        <Card className={cn(
          "hover:border-indigo-200 hover:shadow-sm transition-all cursor-pointer",
          isActive && "border-green-200 bg-green-50/30",
        )}>
          <div className="flex items-start gap-3 p-3 sm:p-4">
            {/* Icon */}
            <div className={cn(
              "flex h-9 w-9 sm:h-10 sm:w-10 shrink-0 items-center justify-center rounded-lg text-white mt-0.5",
              hasAI ? "bg-purple-600" : isActive ? "bg-green-600" : "bg-indigo-600",
            )}>
              {hasAI ? <Cpu className="h-4 w-4 sm:h-5 sm:w-5" /> : <BookOpen className="h-4 w-4 sm:h-5 sm:w-5" />}
            </div>

            {/* Main info — takes all remaining space */}
            <div className="min-w-0 flex-1">
              {/* Topic name, when set, is the most specific identifier a
                  teacher has for a session — lead with it and push subject/
                  grade down to a supporting line instead of burying it. */}
              {s.title && (
                <div className="text-sm font-semibold text-slate-900 break-words">{s.title}</div>
              )}
              {/* Subject + badges row — wraps on mobile */}
              <div className="flex flex-wrap items-center gap-1.5">
                <span className={cn("break-words", s.title ? "text-xs text-slate-500" : "text-sm font-medium text-slate-900")}>
                  {s.subject ?? (
                    <span className="text-slate-400 italic font-normal">No subject set</span>
                  )}
                  {s.grade ? <span className={s.title ? "" : "text-slate-500 font-normal"}> · {s.grade}</span> : ""}
                  {s.instructor_name ? <span className={s.title ? "" : "text-slate-500 font-normal"}> · {s.instructor_name}</span> : ""}
                </span>
                <Badge className={cn("gap-1 text-[0.625rem] px-1.5 py-0.5", STATUS_COLOURS[s.status] ?? "bg-slate-100 text-slate-600")}>
                  {STATUS_ICON[s.status]}
                  {s.status.replace("_", " ")}
                </Badge>
                {hasAI && (
                  <Badge className="bg-purple-100 text-purple-700 text-[0.625rem] px-1.5 py-0.5">
                    AI Ready
                  </Badge>
                )}
              </div>

              {/* Meta row */}
              <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span className="flex items-center gap-1">
                  <Clock className="h-3 w-3" /> {timeAgo(s.created_at)}
                </span>
                <span>{s.frame_count} frame{s.frame_count !== 1 ? "s" : ""}</span>
                <span className={cn("flex items-center gap-1 font-medium", SYNC_COLOURS[s.sync_status])}>
                  {SYNC_ICON[s.sync_status]}
                  {s.sync_status}
                </span>
              </div>

              {/* Action row — below text on mobile, stays tight */}
              <div className="mt-2 flex items-center gap-1">
                {/* Quick shortcuts — hidden on very small, shown on sm+ */}
                <button
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); router.push(`/sessions/${s.session_id}/capture`); }}
                  className="hidden sm:flex rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors"
                  title="Capture frames"
                ><Upload className="h-3.5 w-3.5" /></button>
                <button
                  onClick={startTeaching}
                  disabled={resolvingTeach}
                  className="hidden sm:flex rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors disabled:opacity-50"
                  title="Start teaching"
                >{resolvingTeach ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <PlayCircle className="h-3.5 w-3.5" />}</button>
                <button
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); router.push(`/sessions/${s.session_id}/notes`); }}
                  className="hidden sm:flex rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors"
                  title="AI notes"
                ><FileText className="h-3.5 w-3.5" /></button>

                {/* Delete — always visible, icon-only on mobile */}
                <button
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); setConfirmOpen(true); }}
                  disabled={deleting}
                  title="Delete session"
                  className="flex items-center gap-1 rounded-md border border-red-200 bg-red-50 px-2 py-1 text-[0.6875rem] font-semibold text-red-500 hover:bg-red-100 transition-colors disabled:opacity-40"
                >
                  {deleting
                    ? <Loader2 className="h-3 w-3 animate-spin" />
                    : <Trash2 className="h-3 w-3" />
                  }
                  <span className="hidden sm:inline">Delete</span>
                </button>
              </div>
            </div>

            <ChevronRight className="h-4 w-4 text-slate-300 shrink-0 mt-1" />
          </div>
        </Card>
      </Link>
    </>
  );
}

function OfflineSessionRow({ session: s, onDiscarded }: { session: PendingSession; onDiscarded: (id: string) => void }) {
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
    <Link href={`/sessions/${s.id}/capture`} className="block">
      <Card className="border-amber-200 bg-amber-50/30 hover:border-amber-300 hover:shadow-sm transition-all cursor-pointer">
        <div className="flex items-start gap-3 p-3 sm:p-4">
          {/* Icon */}
          <div className="flex h-9 w-9 sm:h-10 sm:w-10 shrink-0 items-center justify-center rounded-lg bg-amber-500 text-white mt-0.5">
            {isSyncing
              ? <Loader2 className="h-4 w-4 animate-spin" />
              : <WifiOff className="h-4 w-4" />
            }
          </div>

          {/* Main info */}
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-sm font-medium text-slate-900">{label}</span>
              <span style={{ display: "inline-flex", alignItems: "center", gap: "0.25rem", fontSize: "0.625rem", fontWeight: 600, background: isFailed ? "#fee2e2" : "#fef3c7", color: isFailed ? "#dc2626" : "#b45309", borderRadius: "0.25rem", padding: "0.125rem 0.375rem" }}>
                {isFailed ? <AlertCircle style={{ width: "0.625rem", height: "0.625rem" }} /> : <WifiOff style={{ width: "0.625rem", height: "0.625rem" }} />}
                {isFailed ? "Sync failed" : isSyncing ? "Syncing…" : "Offline"}
              </span>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <span className="flex items-center gap-1">
                <Clock className="h-3 w-3" /> {timeAgo(new Date(s.createdAt).toISOString())}
              </span>
              <span className="capitalize">{s.payload.board_type?.replace("_", " ")}</span>
              {isFailed && s.errorMessage && (
                <span className="text-red-500 truncate max-w-[12.5rem]">{s.errorMessage}</span>
              )}
            </div>
            <div className="mt-2 flex items-center gap-1">
              <button
                onClick={handleDiscard}
                disabled={discarding}
                title="Discard offline session"
                className="flex items-center gap-1 rounded-md border border-red-200 bg-red-50 px-2 py-1 text-[0.6875rem] font-semibold text-red-500 hover:bg-red-100 transition-colors disabled:opacity-40"
              >
                {discarding ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
                <span className="hidden sm:inline">Discard</span>
              </button>
            </div>
          </div>

          <ChevronRight className="h-4 w-4 text-slate-300 shrink-0 mt-1" />
        </div>
      </Card>
    </Link>
  );
}

export function HomeClassicView(p: HomeViewProps) {
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
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Session History</h1>
          <p className="text-sm text-slate-500 mt-0.5">All classroom capture sessions</p>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/sessions/compare">
            <Button size="sm" variant="secondary">
              <GitCompare className="h-4 w-4" /> Compare
            </Button>
          </Link>
          <Link href="/sessions/new">
            <Button size="sm">
              <Plus className="h-4 w-4" /> New Session
            </Button>
          </Link>
        </div>
      </div>

      {/* Today's class, from attendance — see the matching comment in
          HomePremiumView.tsx. Additive, not a filter: also appears in its
          normal date group below. */}
      {matchGrade && (
        <div className="rounded-lg border border-indigo-100 bg-white p-4">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-indigo-700">
            Grade {matchGrade}{matchSection ? ` · Section ${matchSection}` : ""}
          </h2>
          {matchingSessions.length > 0 ? (
            <div className="space-y-2">
              {matchingSessions.map(s => (
                <SessionRow key={s.session_id} session={s} onDeleted={onSessionDeleted} />
              ))}
            </div>
          ) : (
            <p className="text-sm text-slate-500">
              No sessions yet for Grade {matchGrade} —{" "}
              <Link href="/sessions/new" className="font-medium text-indigo-600 hover:underline">start one</Link>.
            </p>
          )}
        </div>
      )}

      {/* Classic/premium toggle */}
      <div className="flex justify-end">{designToggle}</div>

      {/* Offline cache banner */}
      {fromCache && (
        <div style={{ background: "#fef3c7", border: "1px solid #fbbf24", borderRadius: "0.5rem", padding: "0.625rem 0.875rem", display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <AlertCircle style={{ width: "1rem", height: "1rem", color: "#d97706", flexShrink: 0 }} />
          <span style={{ fontSize: "0.8125rem", color: "#92400e" }}>
            You&apos;re viewing cached sessions from your last sync. Some sessions may be missing until you reconnect.
          </span>
        </div>
      )}

      {/* Classroom settings banner */}
      <ClassroomBanner settings={classroom} />

      {/* Stats */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Total Sessions" value={counts.total}     colour="text-slate-900" />
        <Stat label="Active Now"     value={counts.active}    colour="text-green-600" />
        <Stat label="AI Complete"    value={counts.completed} colour="text-indigo-600" />
        <Stat label="Offline Sync Backlog" value={counts.offlineBacklog} colour="text-orange-500" />
      </div>

      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        {(["all","active","completed","ai_complete"] as const).map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={cn(
              "rounded-full px-3 py-1 text-xs font-medium transition-colors",
              filter === f
                ? "bg-indigo-600 text-white"
                : "bg-white border border-slate-200 text-slate-600 hover:border-indigo-300"
            )}
          >
            {f === "all" ? "All" : f === "ai_complete" ? "AI Complete" : f.charAt(0).toUpperCase() + f.slice(1)}
            {f !== "all" && (
              <span className="ml-1.5 rounded-full bg-white/20 px-1.5 py-0.5 text-[0.625rem]">
                {sessions.filter(s => s.status === f).length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Offline (not yet synced) sessions */}
      {offlineSessions.length > 0 && (
        <div>
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-amber-500">
            Pending upload <span className="text-amber-300 normal-case font-normal">({offlineSessions.length})</span>
          </h2>
          <div className="space-y-2">
            {offlineSessions.map(s => (
              <OfflineSessionRow
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
        <Empty
          icon={<BookOpen className="h-12 w-12" />}
          title="No sessions yet"
          description="Create a session, then capture board photos to get AI-generated notes and quizzes."
          action={
            <Link href="/sessions/new">
              <Button size="sm"><Plus className="h-4 w-4" /> New Session</Button>
            </Link>
          }
        />
      ) : filtered.length > 0 ? (
        <div className="space-y-6">
          {groups.map(({ label, items }) => (
            <div key={label}>
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
                {label} <span className="text-slate-300 normal-case font-normal">({items.length})</span>
              </h2>
              <div className="space-y-2">
                {items.map(s => (
                  <SessionRow key={s.session_id} session={s} onDeleted={onSessionDeleted} />
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
