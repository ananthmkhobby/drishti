"use client";

import { use, useState } from "react";
import useSWR from "swr";
import {
  Brain, Cpu, Loader2, RefreshCw, ChevronDown, ChevronRight,
  TrendingUp, TrendingDown, Minus, AlertTriangle, BookOpen, Lightbulb,
} from "lucide-react";
import {
  api,
  type AbsorptionFrame,
  type AbsorptionRevisionSection,
  type AbsorptionMapAI,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { LoadingScreen } from "@/components/ui/Spinner";
import { cn } from "@/lib/utils";

// ─── Helpers ──────────────────────────────────────────────────────────────────

const LEVEL_CONFIG = {
  high:    { label: "High",    color: "bg-emerald-500", textColor: "text-emerald-700", bgLight: "bg-emerald-50",  border: "border-emerald-200", barColor: "bg-emerald-400" },
  medium:  { label: "Medium",  color: "bg-amber-400",   textColor: "text-amber-700",   bgLight: "bg-amber-50",    border: "border-amber-200",   barColor: "bg-amber-400"   },
  low:     { label: "Low",     color: "bg-rose-500",    textColor: "text-rose-700",    bgLight: "bg-rose-50",     border: "border-rose-200",    barColor: "bg-rose-400"    },
  unknown: { label: "No data", color: "bg-slate-300",   textColor: "text-slate-500",   bgLight: "bg-slate-50",    border: "border-slate-200",   barColor: "bg-slate-300"   },
} as const;

type Level = keyof typeof LEVEL_CONFIG;

function LevelDot({ level }: { level: Level }) {
  const cfg = LEVEL_CONFIG[level] ?? LEVEL_CONFIG.unknown;
  return <span className={cn("inline-block h-2.5 w-2.5 rounded-full shrink-0", cfg.color)} />;
}

function AttentionBar({ pct }: { pct: number | null }) {
  if (pct === null) return <div className="h-1 rounded-full bg-slate-100 w-full" />;
  const w = Math.min(100, Math.max(0, pct));
  const cfg = LEVEL_CONFIG[pct >= 65 ? "high" : pct >= 35 ? "medium" : "low"];
  return (
    <div className="h-1 rounded-full bg-slate-100 w-full overflow-hidden">
      <div className={cn("h-full rounded-full transition-all", cfg.barColor)} style={{ width: `${w}%` }} />
    </div>
  );
}

// ─── Frame Card ───────────────────────────────────────────────────────────────

function FrameCard({ frame }: { frame: AbsorptionFrame }) {
  const [open, setOpen] = useState(false);
  const cfg = LEVEL_CONFIG[frame.absorption_level as Level] ?? LEVEL_CONFIG.unknown;
  const hasOcr = frame.ocr_preview && frame.ocr_preview.trim().length > 0;

  return (
    <div className={cn("rounded-xl border p-3 transition-colors", cfg.border, cfg.bgLight)}>
      <div className="flex items-start gap-2.5">
        <LevelDot level={frame.absorption_level as Level} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2 mb-1.5">
            <span className="text-xs font-semibold text-slate-600">
              Frame {frame.sequence_no}
              <span className="font-normal text-slate-400 ml-1">· min {frame.minute}</span>
            </span>
            <span className={cn("text-xs font-semibold", cfg.textColor)}>
              {frame.attention_pct !== null ? `${frame.attention_pct}%` : "—"}
            </span>
          </div>
          <AttentionBar pct={frame.attention_pct} />
          {hasOcr && (
            <button
              onClick={() => setOpen((v) => !v)}
              className="mt-2 flex items-center gap-1 text-[0.6875rem] text-slate-500 hover:text-slate-700"
            >
              {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              Board content
            </button>
          )}
          {open && hasOcr && (
            <p className="mt-1.5 text-[0.6875rem] text-slate-600 leading-relaxed whitespace-pre-wrap font-mono bg-white/70 rounded-lg p-2 border border-slate-100">
              {frame.ocr_preview}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Summary Bar ─────────────────────────────────────────────────────────────

function SummaryBar({
  total, high, medium, low, avg,
}: { total: number; high: number; medium: number; low: number; avg: number | null }) {
  const pct = (n: number) => total > 0 ? Math.round((n / total) * 100) : 0;

  return (
    <div className="rounded-2xl bg-white border border-slate-200 px-5 py-4 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold text-slate-700">{total} frames analysed</span>
        {avg !== null && (
          <span className="text-sm font-semibold text-slate-500">
            Avg attention <span className="text-slate-800">{avg}%</span>
          </span>
        )}
      </div>
      {/* Stacked progress bar */}
      <div className="flex h-3 rounded-full overflow-hidden gap-0.5">
        {high > 0 && (
          <div
            className="bg-emerald-400 rounded-l-full transition-all"
            style={{ width: `${pct(high)}%` }}
            title={`High: ${high} frames`}
          />
        )}
        {medium > 0 && (
          <div
            className="bg-amber-400 transition-all"
            style={{ width: `${pct(medium)}%` }}
            title={`Medium: ${medium} frames`}
          />
        )}
        {low > 0 && (
          <div
            className="bg-rose-400 rounded-r-full transition-all"
            style={{ width: `${pct(low)}%` }}
            title={`Low: ${low} frames`}
          />
        )}
        {high === 0 && medium === 0 && low === 0 && (
          <div className="bg-slate-200 rounded-full w-full" />
        )}
      </div>
      {/* Legend */}
      <div className="flex items-center gap-4 mt-2">
        {([
          ["high", high, "emerald"] as const,
          ["medium", medium, "amber"] as const,
          ["low", low, "rose"] as const,
        ]).map(([lvl, count, color]) => (
          <div key={lvl} className="flex items-center gap-1.5">
            <span className={cn("h-2 w-2 rounded-full", `bg-${color}-400`)} />
            <span className="text-xs text-slate-600 capitalize">
              {lvl} <span className="font-semibold text-slate-700">{count}</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Revision Section ─────────────────────────────────────────────────────────

function RevisionSection({ section }: { section: AbsorptionRevisionSection }) {
  const cfg = LEVEL_CONFIG[section.level as Level] ?? LEVEL_CONFIG.unknown;

  const LevelIcon = section.level === "high"
    ? TrendingUp
    : section.level === "medium"
    ? Minus
    : section.level === "low"
    ? TrendingDown
    : BookOpen;

  return (
    <div className={cn("rounded-2xl border p-5", cfg.border)}>
      <div className="flex items-center gap-2 mb-3">
        <div className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-lg", cfg.bgLight)}>
          <LevelIcon className={cn("h-4 w-4", cfg.textColor)} />
        </div>
        <h3 className="text-sm font-semibold text-slate-800">{section.heading}</h3>
        <span className={cn("ml-auto text-xs font-medium px-2 py-0.5 rounded-full", cfg.bgLight, cfg.textColor)}>
          {section.items.length} topic{section.items.length !== 1 ? "s" : ""}
        </span>
      </div>
      <ul className="space-y-3">
        {section.items.map((item, i) => (
          <li key={i} className="space-y-1">
            <p className="text-sm font-semibold text-slate-800">{item.topic}</p>
            <p className="text-sm text-slate-600 leading-relaxed">{item.summary}</p>
            {item.detail && (
              <p className="text-sm text-slate-500 leading-relaxed bg-white/70 rounded-lg px-3 py-2 border border-slate-100 mt-1">
                {item.detail}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function AbsorptionMapPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = use(params);
  const [generating, setGenerating] = useState(false);
  const [genMsg, setGenMsg] = useState("");

  // Raw frame data (no AI)
  const { data: mapData, isLoading: mapLoading } = useSWR(
    ["absorption-map", sessionId],
    () => api.getAbsorptionMap(sessionId).catch(() => null),
    { shouldRetryOnError: false }
  );

  // AI revision notes (from outputs)
  const { data: outputs, mutate: mutateOutputs } = useSWR(
    ["outputs", sessionId],
    () => api.getOutputs(sessionId).catch(() => null),
    {
      refreshInterval: (data) => {
        const s = data?.outputs?.absorption_map?.status;
        return s === "processing" || s === "pending" ? 4000 : 0;
      },
      shouldRetryOnError: false,
    }
  );

  const aiOutput = outputs?.outputs?.absorption_map;
  const aiData = aiOutput?.status === "ready" ? (aiOutput.data as unknown as AbsorptionMapAI) : null;
  const isAiProcessing = aiOutput?.status === "processing" || aiOutput?.status === "pending";

  async function handleGenerate() {
    setGenerating(true);
    setGenMsg("");
    try {
      await api.triggerGeneration(sessionId, ["absorption_map"]);
      setGenMsg("Generating revision notes…");
      mutateOutputs();
    } catch (err: unknown) {
      setGenMsg(err instanceof Error ? err.message : "Failed to generate.");
    } finally {
      setGenerating(false);
    }
  }

  if (mapLoading) return <LoadingScreen label="Loading absorption map…" />;

  const hasFrames = mapData && mapData.total_frames > 0;

  return (
    <div className="space-y-6 max-w-3xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Absorption Map</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Board content × student attention — what actually landed
          </p>
        </div>
        <div className="flex gap-2">
          {isAiProcessing ? (
            <div className="flex items-center gap-2 text-indigo-600 text-sm font-medium">
              <Loader2 className="h-4 w-4 animate-spin" />
              Generating…
            </div>
          ) : (
            <Button size="sm" loading={generating} onClick={handleGenerate}>
              <Cpu className="h-4 w-4" />
              {aiData ? "Re-generate" : "Generate Revision Notes"}
            </Button>
          )}
        </div>
      </div>

      {genMsg && (
        <div className="rounded-lg bg-indigo-50 border border-indigo-100 px-4 py-3 text-sm text-indigo-700">
          {genMsg}
        </div>
      )}

      {!hasFrames ? (
        <div className="flex flex-col items-center justify-center gap-6 py-20 text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-slate-100">
            <Brain className="h-8 w-8 text-slate-400" />
          </div>
          <div className="max-w-sm space-y-2">
            <h2 className="text-lg font-semibold text-slate-800">No frames yet</h2>
            <p className="text-sm text-slate-500">
              Capture board frames during a session to see the Absorption Map. The map
              joins board content with live student attention to show what was absorbed.
            </p>
          </div>
        </div>
      ) : (
        <>
          {/* Summary bar */}
          <SummaryBar
            total={mapData.total_frames}
            high={mapData.high_count}
            medium={mapData.medium_count}
            low={mapData.low_count}
            avg={mapData.avg_attention_pct}
          />

          {!mapData.has_audience_data && (
            <div className="flex items-start gap-3 rounded-xl bg-amber-50 border border-amber-200 px-4 py-3">
              <AlertTriangle className="h-4 w-4 text-amber-500 mt-0.5 shrink-0" />
              <p className="text-sm text-amber-700">
                No audience attention data for this session. Enable Audience Mode during
                capture to see attention levels per frame. Frames are shown without
                absorption classification.
              </p>
            </div>
          )}

          {/* Frame grid */}
          <div>
            <h2 className="text-sm font-semibold text-slate-700 mb-3">Frame Timeline</h2>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {mapData.frames.map((frame) => (
                <FrameCard key={frame.frame_id} frame={frame} />
              ))}
            </div>
          </div>

          {/* AI revision notes */}
          {aiData ? (
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <h2 className="text-base font-semibold text-slate-800">AI Revision Notes</h2>
                <Button
                  variant="secondary"
                  size="sm"
                  loading={generating}
                  onClick={handleGenerate}
                  className="ml-auto"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                </Button>
              </div>

              {aiData.revision_sections?.map((section, i) => (
                <RevisionSection key={i} section={section} />
              ))}

              {aiData.insight && (
                <Card className="border-indigo-100 bg-indigo-50">
                  <CardContent className="pt-5">
                    <div className="flex items-start gap-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-indigo-100">
                        <Brain className="h-4 w-4 text-indigo-600" />
                      </div>
                      <div>
                        <p className="text-xs font-semibold text-indigo-600 uppercase tracking-wide mb-1">
                          Pattern Insight
                        </p>
                        <p className="text-sm text-slate-700 leading-relaxed">{aiData.insight}</p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )}

              {aiData.replan_suggestion && (
                <Card className="border-amber-100 bg-amber-50">
                  <CardContent className="pt-5">
                    <div className="flex items-start gap-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-amber-100">
                        <Lightbulb className="h-4 w-4 text-amber-600" />
                      </div>
                      <div>
                        <p className="text-xs font-semibold text-amber-700 uppercase tracking-wide mb-1">
                          Next Class
                        </p>
                        <p className="text-sm text-slate-700 leading-relaxed">{aiData.replan_suggestion}</p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>
          ) : !isAiProcessing ? (
            <div className="flex flex-col items-center gap-4 rounded-2xl border border-dashed border-slate-200 py-10 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100">
                <Brain className="h-6 w-6 text-slate-400" />
              </div>
              <div className="space-y-1 max-w-xs">
                <p className="text-sm font-semibold text-slate-700">No revision notes yet</p>
                <p className="text-xs text-slate-500">
                  Click "Generate Revision Notes" to create targeted study materials
                  based on where attention dropped.
                </p>
              </div>
              <Button size="sm" loading={generating} onClick={handleGenerate}>
                <Cpu className="h-4 w-4" /> Generate Revision Notes
              </Button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
