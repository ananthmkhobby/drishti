"use client";

import { use, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import Link from "next/link";
import { Eye, ChevronRight, Zap, BarChart2 } from "lucide-react";
import { api, type OCRRegion } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { LoadingScreen } from "@/components/ui/Spinner";
import { Empty } from "@/components/ui/Empty";

const REGION_COLOURS: Record<string, string> = {
  heading:  "border-l-indigo-500 bg-indigo-50/40",
  formula:  "border-l-purple-500 bg-purple-50/40 font-mono",
  list:     "border-l-green-500 bg-green-50/40",
  diagram:  "border-l-orange-400 bg-orange-50/40",
  text:     "border-l-slate-300 bg-white",
};

const REGION_BADGE: Record<string, string> = {
  heading: "bg-indigo-100 text-indigo-700",
  formula: "bg-purple-100 text-purple-700",
  list:    "bg-green-100 text-green-700",
  diagram: "bg-orange-100 text-orange-700",
  text:    "bg-slate-100 text-slate-600",
};

function ConfBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const colour = pct >= 75 ? "bg-green-500" : pct >= 50 ? "bg-yellow-400" : "bg-red-400";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 rounded-full bg-slate-200">
        <div className={cn("h-full rounded-full", colour)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-500">{pct}%</span>
    </div>
  );
}

export default function OCRPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  const searchParams = useSearchParams();
  const frameId = searchParams.get("frame") ?? "";

  const { data: framesData } = useSWR(
    ["frames", sessionId],
    () => api.getFrames(sessionId),
    {
      // Poll every 3s while any frame is still being OCR'd, so a frame that
      // finishes processing shows up without the teacher having to reload —
      // previously this list never refreshed on its own, so "pending"/
      // "processing" looked permanently stuck even once the backend was
      // actually done.
      refreshInterval: (data) => {
        const frames = data?.frames ?? [];
        const hasInProgress = frames.some(
          (f) => f.ocr_status !== "done" && f.ocr_status !== "failed" && f.ocr_status !== "skipped",
        );
        return hasInProgress ? 3000 : 0;
      },
      revalidateOnFocus: true,
    },
  );

  const frames = framesData?.frames ?? [];
  const activeFrame = frames.find(f => f.frame_id === frameId) ?? frames[0];
  const stillProcessing = activeFrame?.ocr_status === "pending" || activeFrame?.ocr_status === "processing";

  const { data: ocr, error, isLoading, mutate: mutateOCR } = useSWR(
    activeFrame?.frame_id ? ["ocr", activeFrame.frame_id] : null,
    () => api.getOCR(activeFrame!.frame_id),
    { shouldRetryOnError: false, refreshInterval: stillProcessing ? 3000 : 0 }
  );

  const [isRetrying, setIsRetrying] = useState(false);

  async function handleRetry() {
    if (!activeFrame) return;
    setIsRetrying(true);
    try {
      await api.retryOCR(activeFrame.frame_id);
      // Give the background task a few seconds to run, then re-fetch
      await new Promise(r => setTimeout(r, 4000));
      await mutateOCR();
    } finally {
      setIsRetrying(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">OCR Result</h1>
          <p className="text-sm text-slate-500 mt-0.5">Text extracted from board image</p>
        </div>
        <Link href={`/sessions/${sessionId}/notes`}>
          <button className="flex items-center gap-1 text-sm text-indigo-600 hover:underline">
            View AI Notes <ChevronRight className="h-4 w-4" />
          </button>
        </Link>
      </div>

      {/* Frame selector */}
      {frames.length > 1 && (
        <div className="flex flex-wrap gap-2">
          {frames.map(f => (
            <Link
              key={f.frame_id}
              href={`/sessions/${sessionId}/ocr?frame=${f.frame_id}`}
              className={cn(
                "rounded-full px-3 py-1 text-xs font-medium border transition-colors",
                f.frame_id === activeFrame?.frame_id
                  ? "border-indigo-500 bg-indigo-50 text-indigo-700"
                  : "border-slate-200 text-slate-600 hover:border-slate-300"
              )}
            >
              Frame #{f.sequence_no}
            </Link>
          ))}
        </div>
      )}

      {!activeFrame && (
        <Empty
          icon={<Eye className="h-12 w-12" />}
          title="No frames uploaded"
          description="Upload board images first to see OCR results."
          action={
            <Link href={`/sessions/${sessionId}/capture`}>
              <button className="text-sm text-indigo-600 hover:underline">Upload a frame →</button>
            </Link>
          }
        />
      )}

      {activeFrame && isLoading && <LoadingScreen label="Processing OCR…" />}

      {activeFrame && error && (
        <Card>
          <CardContent className="py-12 text-center space-y-4">
            <p className="text-sm text-slate-500">
              {error?.message?.includes("OCR_NOT_READY") || error?.message?.includes("404")
                ? "OCR is still processing — this page updates automatically once it's done."
                : "OCR processing failed for this frame."}
            </p>
            {/* Retry is also offered while "pending" (not just "failed") as a manual
                escape hatch — a frame can be stuck queued if the server restarted
                mid-run and never picked it back up; not shown for "processing" since
                the backend rejects a retry while a run is already in flight. */}
            {(activeFrame.ocr_status === "failed" || activeFrame.ocr_status === "pending" || error?.message?.includes("OCR_FAILED")) && (
              <button
                onClick={handleRetry}
                disabled={isRetrying}
                className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60"
              >
                {isRetrying ? "Retrying…" : "Retry OCR"}
              </button>
            )}
          </CardContent>
        </Card>
      )}

      {ocr && (
        <div className="grid gap-6 lg:grid-cols-3">
          {/* Stats */}
          <div className="space-y-3 lg:col-span-1">
            <Card>
              <CardContent className="space-y-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-50">
                    <Zap className="h-5 w-5 text-indigo-600" />
                  </div>
                  <div>
                    <p className="text-xs text-slate-500">Engine</p>
                    <p className="text-sm font-semibold text-slate-900 capitalize">{ocr.engine_used}</p>
                  </div>
                </div>
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <p className="text-xs text-slate-500">Confidence</p>
                    <span className="text-xs font-medium text-slate-700">
                      {Math.round(ocr.confidence * 100)}%
                    </span>
                  </div>
                  <div className="h-2 w-full rounded-full bg-slate-200">
                    <div
                      className={cn(
                        "h-full rounded-full transition-all",
                        ocr.confidence >= 0.75 ? "bg-green-500" :
                        ocr.confidence >= 0.50 ? "bg-yellow-400" : "bg-red-400"
                      )}
                      style={{ width: `${Math.round(ocr.confidence * 100)}%` }}
                    />
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <BarChart2 className="h-4 w-4 text-slate-400" />
                  <span className="text-sm text-slate-600">{ocr.regions.length} regions detected</span>
                </div>
              </CardContent>
            </Card>

            {/* Region type breakdown */}
            <Card>
              <CardHeader><CardTitle className="text-sm">Region Types</CardTitle></CardHeader>
              <CardContent className="space-y-2">
                {Array.from(new Set(ocr.regions.map(r => r.type))).map(type => {
                  const count = ocr.regions.filter(r => r.type === type).length;
                  return (
                    <div key={type} className="flex items-center justify-between">
                      <Badge className={REGION_BADGE[type] ?? "bg-slate-100 text-slate-600"}>{type}</Badge>
                      <span className="text-sm font-medium text-slate-600">{count}</span>
                    </div>
                  );
                })}
              </CardContent>
            </Card>
          </div>

          {/* Regions + raw text */}
          <div className="space-y-4 lg:col-span-2">
            <Card>
              <CardHeader><CardTitle>Detected Regions</CardTitle></CardHeader>
              <CardContent className="space-y-2">
                {ocr.regions.length === 0 ? (
                  <p className="text-sm text-slate-400">No regions detected.</p>
                ) : ocr.regions.map((r: OCRRegion, i: number) => (
                  <div
                    key={i}
                    className={cn(
                      "rounded-r-lg border-l-4 p-3 text-sm",
                      REGION_COLOURS[r.type] ?? "border-l-slate-300"
                    )}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <Badge className={cn("text-[0.625rem]", REGION_BADGE[r.type])}>{r.type}</Badge>
                      {r.confidence !== null && r.confidence !== undefined && (
                        <ConfBar value={r.confidence} />
                      )}
                    </div>
                    <p className="whitespace-pre-wrap text-slate-800">{r.content ?? "(no text)"}</p>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle>Raw Extracted Text</CardTitle></CardHeader>
              <CardContent>
                <pre className="whitespace-pre-wrap rounded-lg bg-slate-50 p-4 text-sm text-slate-700 font-mono leading-relaxed overflow-auto max-h-64">
                  {ocr.ocr_text || "(empty)"}
                </pre>
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
