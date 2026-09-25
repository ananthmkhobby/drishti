"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import {
  Wifi, WifiOff, AlertTriangle, CheckCircle2,
  Clock, Upload, RefreshCw, HelpCircle,
} from "lucide-react";
import { api, type SyncStatusResponse } from "@/lib/api";
import { generateUUID } from "@/lib/uuid";
import { cn, formatDateTime, timeAgo } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { LoadingScreen } from "@/components/ui/Spinner";

// ── Health config ─────────────────────────────────────────────────────────────

const HEALTH_CONFIG = {
  healthy: {
    icon:  <CheckCircle2 className="h-6 w-6 text-green-600" />,
    label: "Healthy",
    colour: "border-green-200 bg-green-50",
    text:   "text-green-700",
    badge:  "bg-green-100 text-green-700",
  },
  degraded: {
    icon:  <AlertTriangle className="h-6 w-6 text-amber-500" />,
    label: "Degraded",
    colour: "border-amber-200 bg-amber-50",
    text:   "text-amber-700",
    badge:  "bg-amber-100 text-amber-700",
  },
  failing: {
    icon:  <WifiOff className="h-6 w-6 text-red-500" />,
    label: "Failing",
    colour: "border-red-200 bg-red-50",
    text:   "text-red-700",
    badge:  "bg-red-100 text-red-700",
  },
  unknown: {
    icon:  <HelpCircle className="h-6 w-6 text-slate-400" />,
    label: "Unknown",
    colour: "border-slate-200 bg-slate-50",
    text:   "text-slate-500",
    badge:  "bg-slate-100 text-slate-500",
  },
};

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  colour,
  icon,
}: {
  label: string;
  value: number;
  colour: string;
  icon: React.ReactNode;
}) {
  return (
    <div className={cn("rounded-xl border p-4", colour)}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">{label}</p>
          <p className="mt-1 text-3xl font-bold text-slate-900">{value}</p>
        </div>
        <div className="mt-0.5 opacity-70">{icon}</div>
      </div>
    </div>
  );
}

// ── Donut-style progress ring ──────────────────────────────────────────────────

function ProgressRing({ done, total }: { done: number; total: number }) {
  const pct  = total > 0 ? Math.round((done / total) * 100) : 0;
  const r    = 52;
  const circ = 2 * Math.PI * r;
  const dash = (pct / 100) * circ;

  return (
    <div className="relative flex items-center justify-center">
      <svg width="128" height="128" className="-rotate-90">
        <circle cx="64" cy="64" r={r} fill="none" stroke="#e2e8f0" strokeWidth="10" />
        <circle
          cx="64" cy="64" r={r}
          fill="none"
          stroke="#6366f1"
          strokeWidth="10"
          strokeDasharray={`${dash} ${circ}`}
          strokeLinecap="round"
          className="transition-all duration-700"
        />
      </svg>
      <div className="absolute flex flex-col items-center">
        <span className="text-2xl font-bold text-slate-900">{pct}%</span>
        <span className="text-xs text-slate-400">synced</span>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

function getOrCreateFingerprint(): string {
  if (typeof window === "undefined") return "ssr";
  let fp = localStorage.getItem("aci_device_fp");
  if (!fp) {
    // Simple fingerprint: random UUID stored locally
    fp = generateUUID();
    localStorage.setItem("aci_device_fp", fp);
  }
  return fp;
}

export default function SyncStatusPage() {
  const [fingerprint, setFingerprint] = useState<string>("");

  // Initialise fingerprint client-side only (avoids SSR mismatch)
  useEffect(() => {
    setFingerprint(getOrCreateFingerprint());
  }, []);

  const {
    data: sync,
    isLoading,
    error,
    mutate,
  } = useSWR<SyncStatusResponse>(
    fingerprint ? ["sync-status", fingerprint] : null,
    () => api.getSyncStatus(fingerprint),
    { refreshInterval: 15000, shouldRetryOnError: false }
  );

  const health = sync?.health ?? "unknown";
  const cfg    = HEALTH_CONFIG[health];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Sync Status</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Device upload health and frame sync progress
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => mutate()}>
          <RefreshCw className="h-3.5 w-3.5" /> Refresh
        </Button>
      </div>

      {isLoading && !sync && <LoadingScreen label="Checking sync status…" />}

      {!isLoading && error && (
        <Card>
          <CardContent className="py-14 text-center space-y-2">
            <WifiOff className="mx-auto h-10 w-10 text-slate-300" />
            <p className="text-sm font-medium text-slate-600">Could not reach sync service</p>
            <p className="text-xs text-slate-400">
              Make sure the backend is running and this device has been registered.
            </p>
            <Button size="sm" variant="secondary" onClick={() => mutate()} className="mt-3">
              Retry
            </Button>
          </CardContent>
        </Card>
      )}

      {sync && (
        <>
          {/* Health banner */}
          <div className={cn("flex items-center gap-4 rounded-xl border p-5", cfg.colour)}>
            <div className="shrink-0">{cfg.icon}</div>
            <div className="flex-1">
              <p className={cn("text-base font-semibold", cfg.text)}>
                Sync is {cfg.label}
              </p>
              <p className="text-xs text-slate-500 mt-0.5">
                {sync.total > 0
                  ? `${sync.done} of ${sync.total} frames synced`
                  : "No frames recorded for this device yet"}
                {sync.last_sync_at && (
                  <> · Last activity {timeAgo(sync.last_sync_at)}</>
                )}
              </p>
            </div>
            <span className={cn("rounded-full px-3 py-1 text-xs font-semibold shrink-0", cfg.badge)}>
              {cfg.label}
            </span>
          </div>

          {/* Stats grid + ring */}
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="Pending"
              value={sync.pending}
              colour="border-slate-200 bg-slate-50"
              icon={<Clock className="h-5 w-5 text-slate-400" />}
            />
            <StatCard
              label="Uploading"
              value={sync.uploading}
              colour="border-blue-200 bg-blue-50"
              icon={<Upload className="h-5 w-5 text-blue-500" />}
            />
            <StatCard
              label="Done"
              value={sync.done}
              colour="border-green-200 bg-green-50"
              icon={<CheckCircle2 className="h-5 w-5 text-green-500" />}
            />
            <StatCard
              label="Failed"
              value={sync.failed}
              colour={sync.failed > 0 ? "border-red-200 bg-red-50" : "border-slate-200 bg-slate-50"}
              icon={<WifiOff className={cn("h-5 w-5", sync.failed > 0 ? "text-red-500" : "text-slate-300")} />}
            />
          </div>

          {/* Details + ring */}
          <div className="grid gap-5 lg:grid-cols-2">

            {/* Device info */}
            <Card>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <Wifi className="h-4 w-4 text-indigo-600" />
                  <CardTitle>Device Details</CardTitle>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <Row label="Device fingerprint" value={
                  <code className="rounded bg-slate-100 px-2 py-0.5 text-xs font-mono text-slate-700 break-all">
                    {sync.device_fingerprint}
                  </code>
                } />
                {sync.device_id && (
                  <Row label="Device ID" value={
                    <code className="rounded bg-slate-100 px-2 py-0.5 text-xs font-mono text-slate-700">
                      {sync.device_id}
                    </code>
                  } />
                )}
                <Row label="Last sync" value={
                  <span className="text-sm text-slate-700">{formatDateTime(sync.last_sync_at)}</span>
                } />
                <Row label="Skipped frames" value={
                  <span className="text-sm text-slate-700">{sync.skipped}</span>
                } />
                <Row label="Total frames" value={
                  <span className="text-sm font-semibold text-slate-900">{sync.total}</span>
                } />
              </CardContent>
            </Card>

            {/* Progress ring */}
            <Card>
              <CardHeader>
                <CardTitle>Upload Progress</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col items-center justify-center gap-4 py-4">
                <ProgressRing done={sync.done} total={sync.total} />

                <div className="flex gap-6 text-center text-xs text-slate-500">
                  <div>
                    <p className="text-lg font-bold text-indigo-600">{sync.done}</p>
                    <p>Uploaded</p>
                  </div>
                  <div className="w-px bg-slate-200" />
                  <div>
                    <p className="text-lg font-bold text-slate-400">{sync.total - sync.done}</p>
                    <p>Remaining</p>
                  </div>
                </div>
              </CardContent>
            </Card>

          </div>

          {/* Failed warning */}
          {sync.failed > 0 && (
            <div className="flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-4">
              <AlertTriangle className="h-5 w-5 text-red-500 shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-semibold text-red-700">
                  {sync.failed} frame{sync.failed > 1 ? "s" : ""} failed to sync
                </p>
                <p className="text-xs text-red-600 mt-0.5">
                  Check network connectivity and ensure the capture device is online.
                  Failed frames will be retried automatically.
                </p>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-sm text-slate-500 shrink-0">{label}</span>
      <span className="text-right">{value}</span>
    </div>
  );
}
