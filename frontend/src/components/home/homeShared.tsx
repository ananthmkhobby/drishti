// Shared between the Session History page and its two view components
// (classic/premium — render only) so neither view needs to import from
// the page module, and delete/date-grouping logic (safety- and
// correctness-sensitive) is never duplicated between them.
"use client";

import { useState } from "react";
import { AlertCircle, Loader2, Trash2 } from "lucide-react";
import { api, type Session } from "@/lib/api";

export type SessionFilter = "all" | "active" | "completed" | "ai_complete";

export interface SessionCounts {
  total: number;
  active: number;
  completed: number;
  offlineBacklog: number;
}

export interface DateGroup {
  label: string;
  items: Session[];
}

export function groupByDate(sessions: Session[]): DateGroup[] {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const thisWeekStart = new Date(today.getTime() - 6 * 86400000);

  const groups: Record<string, Session[]> = {
    "Today": [],
    "Yesterday": [],
    "This Week": [],
    "Older": [],
  };

  for (const s of sessions) {
    // Normalize to UTC — backend omits 'Z' suffix, causing local-time misparse
    const raw = s.created_at.endsWith("Z") ? s.created_at : s.created_at + "Z";
    const d = new Date(raw);
    const day = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    if (day >= today) {
      groups["Today"].push(s);
    } else if (day >= yesterday) {
      groups["Yesterday"].push(s);
    } else if (day >= thisWeekStart) {
      groups["This Week"].push(s);
    } else {
      groups["Older"].push(s);
    }
  }

  return Object.entries(groups)
    .filter(([, items]) => items.length > 0)
    .map(([label, items]) => ({ label, items }));
}

// Session.grade is free text set however a session was created (voice
// command, manual form) — real data has both "Grade 5" and bare "8" for
// the same grade, confirmed via a live DB check (2026-09-24). Comparing by
// the first run of digits found in each string, rather than string
// equality, is what makes "5" (from the Welcome flow's grade picker)
// correctly match a session stored as "Grade 5".
function firstNumber(s: string | null | undefined): string | null {
  return s?.match(/\d+/)?.[0] ?? null;
}

export function matchesGrade(session: Session, grade: string | null): boolean {
  if (!grade) return false;
  const target = firstNumber(grade);
  return target !== null && firstNumber(session.grade) === target;
}

export function computeCounts(sessions: Session[]): SessionCounts {
  return {
    total: sessions.length,
    active: sessions.filter(s => s.status === "active").length,
    completed: sessions.filter(s => ["completed", "ai_complete"].includes(s.status)).length,
    // Every session defaults to sync_status "pending" at creation and only
    // an offline device's bulk-sync flow ever moves it to "synced" — a
    // session created directly in the app (local_session_id is null) has
    // nothing queued, so it's excluded here. Only sessions that actually
    // came from an offline device count as a real backlog.
    offlineBacklog: sessions.filter(s => s.local_session_id && s.sync_status !== "synced").length,
  };
}

// ─── Delete confirmation dialog — shared verbatim, this is the one
// destructive action on the page and must behave identically in both
// views. ─────────────────────────────────────────────────────────────

export function DeleteConfirmDialog({
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
  const label = s.subject ?? "Untitled session";

  return (
    // Backdrop — click outside to cancel
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}
    >
      <div className="w-full max-w-sm rounded-2xl bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-start gap-3 border-b border-slate-100 px-5 py-4">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-red-100">
            <Trash2 className="h-4 w-4 text-red-600" />
          </div>
          <div className="min-w-0">
            <p className="font-semibold text-slate-900">Delete session?</p>
            <p className="mt-0.5 truncate text-sm text-slate-500">{label}</p>
          </div>
        </div>

        {/* Body */}
        <div className="space-y-3 px-5 py-4">
          {/* Active-session extra warning */}
          {isActive && (
            <div className="flex items-start gap-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2.5">
              <AlertCircle className="h-4 w-4 shrink-0 text-amber-500 mt-0.5" />
              <p className="text-xs text-amber-700 font-medium leading-relaxed">
                This session is still <strong>active</strong>. Any frames being captured or uploaded
                right now will be lost.
              </p>
            </div>
          )}
          <p className="text-sm text-slate-600">
            This will permanently remove:
          </p>
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

        {/* Footer */}
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
              : <><Trash2  className="h-3.5 w-3.5" /> Delete</>
            }
          </button>
        </div>
      </div>
    </div>
  );
}

/** Delete-with-confirmation state machine shared by both views' session rows. */
export function useDeleteSession(sessionId: string, onDeleted: (id: string) => void) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function handleDeleteConfirmed() {
    setDeleting(true);
    try {
      await api.deleteSession(sessionId);
      setConfirmOpen(false);
      onDeleted(sessionId);
    } catch (err: unknown) {
      setDeleting(false);
      const msg = err instanceof Error ? err.message : String(err);
      alert(`Failed to delete session: ${msg}`);
    }
  }

  return { confirmOpen, setConfirmOpen, deleting, handleDeleteConfirmed };
}
