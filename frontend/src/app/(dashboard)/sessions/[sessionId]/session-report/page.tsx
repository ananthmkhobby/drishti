"use client";

import { use, useState } from "react";
import useSWR from "swr";
import {
  FileText, Sparkles, BookOpen, AlertTriangle,
  ArrowRight, Camera, Mic, Cpu, Loader2, RefreshCw,
} from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { LoadingScreen } from "@/components/ui/Spinner";
import { Button } from "@/components/ui/Button";

export default function SessionReportPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  const [generating, setGenerating] = useState(false);
  const [genMsg, setGenMsg] = useState("");

  const { data: report, isLoading, mutate } = useSWR(
    ["session-report", sessionId],
    () => api.getSessionReport(sessionId).catch(() => null),
    {
      refreshInterval: (data) => (!data || data.status === "processing" || data.status === "pending") ? 4000 : 0,
      shouldRetryOnError: false,
    }
  );

  async function handleGenerate() {
    setGenerating(true);
    setGenMsg("");
    try {
      await api.triggerGeneration(sessionId, ["session_report"]);
      setGenMsg("Generating session report…");
      mutate();
    } catch (err: unknown) {
      setGenMsg(err instanceof Error ? err.message : "Failed to generate.");
    } finally {
      setGenerating(false);
    }
  }

  if (isLoading) return <LoadingScreen label="Loading session report…" />;

  const isProcessing = report?.status === "processing" || report?.status === "pending";
  const isReady = report?.status === "ready";

  if (!isReady) {
    return (
      <div className="flex flex-col items-center justify-center gap-6 py-20 text-center">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-indigo-50">
          <FileText className="h-8 w-8 text-indigo-400" />
        </div>
        <div className="max-w-sm space-y-2">
          <h2 className="text-lg font-semibold text-slate-800">
            {isProcessing ? "Generating session report…" : "No session report yet"}
          </h2>
          <p className="text-sm text-slate-500">
            {isProcessing
              ? "This usually takes 30–60 seconds. The page will refresh automatically."
              : "Get a plain-English summary combining board content, audio, and engagement — what was covered, how it went, and what to do next."}
          </p>
        </div>
        {genMsg && (
          <p className="text-sm text-indigo-600 bg-indigo-50 rounded-lg px-4 py-2">{genMsg}</p>
        )}
        {isProcessing ? (
          <div className="flex items-center gap-2 text-indigo-600">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span className="text-sm font-medium">Processing…</span>
          </div>
        ) : (
          <Button size="sm" loading={generating} onClick={handleGenerate}>
            <Cpu className="h-4 w-4" /> Generate Session Report
          </Button>
        )}
      </div>
    );
  }

  const { headline, what_was_covered, how_it_went, highlights, gaps, next_class, sources } = report!;

  return (
    <div className="space-y-6 max-w-3xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Session Report</h1>
          <p className="text-sm text-slate-500 mt-0.5">Plain-English overview of this session</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={() => mutate()}>
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
          <Button size="sm" loading={generating} onClick={handleGenerate}>
            <Cpu className="h-4 w-4" /> Re-generate
          </Button>
        </div>
      </div>

      {genMsg && (
        <div className="rounded-lg bg-indigo-50 border border-indigo-100 px-4 py-3 text-sm text-indigo-700">{genMsg}</div>
      )}

      {/* Headline card */}
      <div className="rounded-2xl bg-indigo-600 px-6 py-5 text-white">
        <div className="flex items-start gap-3">
          <Sparkles className="h-5 w-5 shrink-0 mt-0.5 opacity-80" />
          <p className="text-lg font-semibold leading-snug">{headline}</p>
        </div>
        <div className="mt-4 flex items-center gap-4 text-xs text-indigo-200">
          <span className="flex items-center gap-1">
            <Camera className="h-3.5 w-3.5" />
            {sources?.board_frames ?? 0} board frame{(sources?.board_frames ?? 0) !== 1 ? "s" : ""}
          </span>
          <span className="flex items-center gap-1">
            <Mic className="h-3.5 w-3.5" />
            {sources?.audio ? "Audio analysed" : "No audio"}
          </span>
        </div>
      </div>

      {/* What was covered */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <BookOpen className="h-4 w-4 text-indigo-500" />
            What Was Covered
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-slate-700 leading-relaxed">{what_was_covered}</p>
        </CardContent>
      </Card>

      {/* How it went */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Sparkles className="h-4 w-4 text-amber-500" />
            How It Went
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-slate-700 leading-relaxed">{how_it_went}</p>

          {highlights && highlights.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Highlights</p>
              <ul className="space-y-1.5">
                {highlights.map((h: string, i: number) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-slate-700">
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-green-500" />
                    {h}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Gaps */}
      {gaps && gaps.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="h-4 w-4 text-amber-500" />
              Areas to Revisit
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1.5">
              {gaps.map((g: string, i: number) => (
                <li key={i} className="flex items-start gap-2 text-sm text-slate-700">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
                  {g}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {/* Next class */}
      {next_class && (
        <Card className="border-indigo-100 bg-indigo-50">
          <CardContent className="pt-5">
            <div className="flex items-start gap-3">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-indigo-100">
                <ArrowRight className="h-4 w-4 text-indigo-600" />
              </div>
              <div>
                <p className="text-xs font-semibold text-indigo-600 uppercase tracking-wide mb-1">Next Class</p>
                <p className="text-sm text-slate-700 leading-relaxed">{next_class}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
