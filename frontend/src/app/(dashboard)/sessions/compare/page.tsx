"use client";

import { useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { GitCompare, Loader2, AlertCircle, ArrowLeft, Lightbulb, Link2, Sparkles } from "lucide-react";
import { api, type Session, type CrossSessionLinkResponse, DEV_TEACHER_ID } from "@/lib/api";
import { fetchSessionsCached } from "@/lib/cached-fetchers";
import { Card, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { LoadingScreen } from "@/components/ui/Spinner";
import { cn } from "@/lib/utils";

function sessionLabel(s: Session): string {
  const parts = [s.title, s.subject, s.grade].filter(Boolean);
  return parts.length ? parts.join(" · ") : "Untitled session";
}

export default function CompareSessionsPage() {
  const { data, isLoading, error } = useSWR(["sessions"], () => fetchSessionsCached(DEV_TEACHER_ID));
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<CrossSessionLinkResponse | null>(null);
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState("");

  const sessions: Session[] = data?.sessions ?? [];

  function toggle(id: string) {
    setResult(null);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else if (next.size < 6) next.add(id); // matches backend's max_length=6
      return next;
    });
  }

  async function handleCompare() {
    if (selected.size < 2) return;
    setGenerating(true);
    setGenError("");
    setResult(null);
    try {
      const res = await api.crossSessionLinks(Array.from(selected));
      setResult(res);
    } catch (err: unknown) {
      setGenError(err instanceof Error ? err.message : "Couldn't generate this comparison — try again.");
    } finally {
      setGenerating(false);
    }
  }

  if (isLoading) return <LoadingScreen label="Loading sessions…" />;
  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-20 text-slate-400">
        <AlertCircle className="h-8 w-8 text-red-400" />
        <p className="text-sm">Could not reach backend — check if it is running.</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <Link href="/sessions" className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50">
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <div>
          <h1 className="flex items-center gap-2 text-xl font-bold text-slate-900">
            <GitCompare className="h-5 w-5 text-indigo-600" /> Compare Sessions
          </h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Pick 2–6 sessions — same or different subjects, grades, or instructors — and see how the concepts connect.
          </p>
        </div>
      </div>

      <Card>
        <CardContent className="pt-5 space-y-1">
          {sessions.length === 0 && (
            <p className="py-8 text-center text-sm text-slate-400">No sessions yet.</p>
          )}
          {sessions.map((s) => {
            const checked = selected.has(s.session_id);
            return (
              <button
                key={s.session_id}
                type="button"
                onClick={() => toggle(s.session_id)}
                disabled={!checked && selected.size >= 6}
                className={cn(
                  "flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors",
                  checked ? "border-indigo-400 bg-indigo-50" : "border-slate-200 hover:bg-slate-50",
                  !checked && selected.size >= 6 && "opacity-40 cursor-not-allowed",
                )}
              >
                <div className={cn(
                  "flex h-5 w-5 shrink-0 items-center justify-center rounded border-2",
                  checked ? "border-indigo-600 bg-indigo-600" : "border-slate-300",
                )}>
                  {checked && <div className="h-2 w-2 rounded-sm bg-white" />}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-slate-900">{sessionLabel(s)}</div>
                  {s.instructor_name && (
                    <div className="text-xs text-slate-500">by {s.instructor_name}</div>
                  )}
                </div>
              </button>
            );
          })}
        </CardContent>
      </Card>

      <div className="flex items-center gap-3">
        <Button onClick={handleCompare} disabled={selected.size < 2 || generating} loading={generating}>
          <GitCompare className="h-4 w-4" />
          {generating ? "Comparing…" : `Compare ${selected.size} Session${selected.size === 1 ? "" : "s"}`}
        </Button>
        {selected.size === 1 && (
          <span className="text-xs text-slate-400">Pick at least one more session.</span>
        )}
      </div>

      {genError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {genError}
        </div>
      )}

      {result && (
        <Card>
          <CardContent className="pt-5 space-y-5">
            {result.sessions.some((s) => !s.has_notes) && (
              <div className="rounded-lg bg-amber-50 border border-amber-100 px-3 py-2 text-xs text-amber-700">
                One or more selected sessions has no generated notes yet — the comparison for those is based on less content than usual.
              </div>
            )}

            {result.unifying_theme && (
              <div className="rounded-lg bg-indigo-50 border border-indigo-100 p-3">
                <h2 className="flex items-center gap-1.5 text-xs font-semibold text-indigo-700 uppercase tracking-wide mb-1">
                  <Sparkles className="h-3.5 w-3.5" /> The Big Idea
                </h2>
                <p className="text-sm text-indigo-900 leading-relaxed">{result.unifying_theme}</p>
              </div>
            )}

            <div>
              <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wide mb-2">Summary</h2>
              <p className="text-sm text-slate-800 leading-relaxed">{result.overall_summary}</p>
            </div>

            {result.connections.length > 0 && (
              <div>
                <h2 className="flex items-center gap-1.5 text-sm font-semibold text-slate-500 uppercase tracking-wide mb-2">
                  <Link2 className="h-3.5 w-3.5" /> Shared Principles
                </h2>
                <div className="space-y-3">
                  {result.connections.map((c, i) => (
                    <div key={i} className="rounded-lg border border-slate-200 p-3">
                      <div className="flex flex-wrap items-center gap-2 text-xs font-medium text-slate-500">
                        <span className="rounded bg-indigo-100 px-2 py-0.5 text-indigo-700">{c.concept_a}</span>
                        <span className="text-slate-400">+</span>
                        <span className="rounded bg-violet-100 px-2 py-0.5 text-violet-700">{c.concept_b}</span>
                      </div>
                      <p className="mt-2 text-sm text-slate-800 leading-relaxed">{c.shared_principle}</p>
                      {c.how_to_teach_it && (
                        <div className="mt-2 rounded-md bg-slate-50 px-2.5 py-2 text-xs text-slate-600">
                          <span className="font-semibold text-slate-500 uppercase tracking-wide">How to teach it — </span>
                          {c.how_to_teach_it}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {result.integrated_activity && (
              <div className="rounded-lg bg-green-50 border border-green-100 p-3">
                <h2 className="flex items-center gap-1.5 text-xs font-semibold text-green-700 uppercase tracking-wide mb-1">
                  <Lightbulb className="h-3.5 w-3.5" /> Integrated Activity
                </h2>
                <p className="text-sm text-green-900">{result.integrated_activity}</p>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
