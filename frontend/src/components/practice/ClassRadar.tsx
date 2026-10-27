"use client";

/**
 * Class Misconception Radar card — shown on the TEACHER's Guided Practice
 * screen only. When several desks working the same question are stuck on the
 * same misconception, the backend raises one alert (see
 * backend/app/services/radar_service.py for the thresholds); this card
 * surfaces it so the teacher can address the room once instead of walking
 * desk to desk.
 *
 * Desk names are collapsed by default: this screen is sometimes mirrored to
 * a classroom display, and "these students are wrong" shouldn't be public.
 * "Not what's happening" is the precision signal — it suppresses that
 * misconception on that question and is counted server-side.
 */

import { useState } from "react";
import useSWR from "swr";
import { Radar, ChevronDown, ChevronUp, X } from "lucide-react";
import { api } from "@/lib/api";
import type { RadarAlert } from "@/lib/api";
import { cn } from "@/lib/utils";

const POLL_MS = 5000;

function AlertRow({ alert, onResolve }: { alert: RadarAlert; onResolve: (status: "dismissed" | "false_alarm") => void }) {
  const [showDesks, setShowDesks] = useState(false);
  const question = alert.question_text && alert.question_text.length > 90
    ? `${alert.question_text.slice(0, 90)}…`
    : alert.question_text;

  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-slate-800">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold">
            {alert.desk_count} of {alert.attempting_count} desks are making the same mistake
          </p>
          {question && <p className="mt-0.5 text-xs text-slate-600">On: {question}</p>}
        </div>
        <button
          type="button"
          onClick={() => onResolve("dismissed")}
          aria-label="Dismiss"
          className="shrink-0 rounded p-1 text-slate-500 hover:bg-amber-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-600"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <p className="mt-2 text-sm font-medium">{alert.title}</p>
      {alert.description && <p className="mt-0.5 text-xs text-slate-700">{alert.description}</p>}
      {alert.typical_work && (
        <p className="mt-1 text-xs text-slate-600">
          <span className="font-semibold">Typically looks like:</span> {alert.typical_work}
        </p>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setShowDesks((v) => !v)}
          className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-white px-2 py-1 text-xs font-medium text-slate-700 hover:bg-amber-100"
        >
          {showDesks ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          {showDesks ? "Hide desks" : "Show desks"}
        </button>
        <button
          type="button"
          onClick={() => onResolve("false_alarm")}
          className="rounded-md border border-amber-300 bg-white px-2 py-1 text-xs font-medium text-slate-700 hover:bg-amber-100"
        >
          Not what&apos;s happening
        </button>
      </div>

      {showDesks && (
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {alert.desks.map((d) => (
            <li key={d.station_id} className="rounded-full border border-amber-300 bg-white px-2 py-0.5 text-xs text-slate-700">
              {d.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ClassRadar({ sessionId, className }: { sessionId: string; className?: string }) {
  const { data, mutate } = useSWR(
    ["class-radar", sessionId],
    () => api.getSessionRadar(sessionId),
    { refreshInterval: POLL_MS },
  );
  const alerts = data?.alerts ?? [];
  if (alerts.length === 0) return null;

  const resolve = async (alert: RadarAlert, status: "dismissed" | "false_alarm") => {
    // Optimistic: drop it immediately; the next poll reconciles with the server.
    await mutate(
      async (current) => {
        await api.updateRadarAlert(alert.id, status);
        return current ? { ...current, alerts: current.alerts.filter((a) => a.id !== alert.id) } : current;
      },
      {
        optimisticData: (current) => (current ? { ...current, alerts: current.alerts.filter((a) => a.id !== alert.id) } : current!),
        rollbackOnError: true,
        revalidate: true,
      },
    );
  };

  return (
    <section aria-label="Class misconception radar" className={cn("space-y-2", className)}>
      <h2 className="flex items-center gap-1.5 text-sm font-semibold text-slate-600">
        <Radar className="h-3.5 w-3.5" /> Class radar — a pattern across desks
      </h2>
      {alerts.map((a) => (
        <AlertRow key={a.id} alert={a} onResolve={(status) => resolve(a, status)} />
      ))}
    </section>
  );
}
