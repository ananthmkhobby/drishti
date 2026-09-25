"use client";

import { Suspense, useState, useEffect, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { AlertCircle, RefreshCw, Sparkles, History } from "lucide-react";
import { DEV_TEACHER_ID } from "@/lib/api";
import { fetchSessionsCached } from "@/lib/cached-fetchers";
import { getAllPendingSessions, type PendingSession } from "@/lib/offline-store";
import {
  getClassroomSettings,
  type ClassroomSettings,
} from "@/lib/classroom-settings";
import { Button } from "@/components/ui/Button";
import { LoadingScreen } from "@/components/ui/Spinner";
import { useDesignVersion } from "@/hooks/useDesignVersion";
import { groupByDate, computeCounts, matchesGrade, type SessionFilter } from "@/components/home/homeShared";
import { HomeClassicView } from "@/components/home/HomeClassicView";
import { HomePremiumView } from "@/components/home/HomePremiumView";

export default function SessionsPage() {
  // useSearchParams() (inside SessionsPageInner) requires a Suspense
  // boundary from an ancestor — Next.js's production build enforces this
  // strictly (`next build` on the Pi failed on it; local `next dev` didn't
  // surface it, which is why this was missed testing on the Mac,
  // confirmed 2026-09-24). LoadingScreen already covers the same "still
  // loading" moment the SWR isLoading check below handles once mounted.
  return (
    <Suspense fallback={<LoadingScreen label="Loading sessions…" />}>
      <SessionsPageInner />
    </Suspense>
  );
}

function SessionsPageInner() {
  const [filter, setFilter] = useState<SessionFilter>("all");
  const [classroom, setClassroom] = useState<ClassroomSettings | null>(null);
  const [offlineSessions, setOfflineSessions] = useState<PendingSession[]>([]);
  const { version, toggle: toggleDesign } = useDesignVersion("home");
  // Set only when arriving straight from Welcome's attendance flow (its
  // "Go to dashboard" appends these) — powers the "Continue Grade X" banner
  // below the hero so a teacher with several sessions today doesn't have to
  // scroll the full list to find today's class. Absent on a plain visit to
  // /sessions (direct nav, bookmark, sidebar link), which shows no banner.
  const searchParams = useSearchParams();
  const matchGrade = searchParams.get("grade");
  const matchSection = searchParams.get("section");

  // All hooks before any early returns
  const { data, error, isLoading, mutate } = useSWR(
    ["sessions", DEV_TEACHER_ID],
    () => fetchSessionsCached(DEV_TEACHER_ID),
    { refreshInterval: 15000 }
  );

  const refreshOffline = useCallback(async () => {
    try {
      const all = await getAllPendingSessions();
      setOfflineSessions(all.filter(s => s.status !== "done"));
    } catch {
      // IDB unavailable — ignore
    }
  }, []);

  useEffect(() => {
    setClassroom(getClassroomSettings());
    refreshOffline();
  }, [refreshOffline]);

  // Remove from offline list when sync engine notifies success
  useEffect(() => {
    const handler = (ev: Event) => {
      const { sessionId } = (ev as CustomEvent).detail ?? {};
      if (sessionId) {
        setOfflineSessions(prev => prev.filter(s => s.id !== sessionId));
        mutate();
      }
    };
    window.addEventListener("aci:session-synced", handler);
    return () => window.removeEventListener("aci:session-synced", handler);
  }, [mutate]);

  if (isLoading) return <LoadingScreen label="Loading sessions…" />;
  if (error) return (
    <div className="flex flex-col items-center justify-center gap-3 py-20 text-slate-400">
      <AlertCircle className="h-8 w-8 text-red-400" />
      <p className="text-sm">Could not reach backend — check if it is running.</p>
      <Button variant="secondary" size="sm" onClick={() => mutate()}>
        <RefreshCw className="h-3.5 w-3.5" /> Retry
      </Button>
    </div>
  );

  const fromCache = !!(data as { _fromCache?: boolean })?._fromCache;
  const sessions = data?.sessions ?? [];
  const matchingSessions = matchGrade ? sessions.filter(s => matchesGrade(s, matchGrade)) : [];
  // Excluded from the date-grouped list below once shown in the Grade X
  // banner — reported as reading like duplicates, not helpful redundancy
  // (2026-09-24), so this is now a genuine "pinned to top" move rather
  // than an additional copy.
  const matchingIds = new Set(matchingSessions.map(s => s.session_id));
  const filtered = (filter === "all" ? sessions : sessions.filter(s => s.status === filter))
    .filter(s => !matchingIds.has(s.session_id));
  const counts = computeCounts(sessions);
  const groups = groupByDate(filtered);

  const designToggle = (
    <button
      onClick={toggleDesign}
      className="flex items-center gap-1.5 text-xs font-medium text-indigo-600 hover:text-indigo-800 transition-colors"
    >
      {version === "premium"
        ? <><History className="h-3.5 w-3.5" /> Switch to classic view</>
        : <><Sparkles className="h-3.5 w-3.5" /> Try the new design</>}
    </button>
  );

  const viewProps = {
    filter, setFilter, classroom, offlineSessions, setOfflineSessions,
    fromCache, sessions, filtered, counts, groups, mutate, designToggle,
    matchGrade, matchSection, matchingSessions,
  };

  return version === "premium"
    ? <HomePremiumView {...viewProps} />
    : <HomeClassicView {...viewProps} />;
}
