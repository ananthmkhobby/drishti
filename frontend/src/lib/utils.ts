import clsx, { type ClassValue } from "clsx";

export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

/**
 * Chrome (and other browsers) report `duration: Infinity` for a WebM blob
 * produced by MediaRecorder — the container's duration box isn't written
 * until the file is finalized in a way MediaRecorder's incremental muxing
 * doesn't do — and the native <audio> control then renders that as a blank
 * or "0:00" duration even though playback works fine. The standard
 * workaround: seek near the end, which forces the browser to actually scan
 * the file and correct its own reported duration, then seek back to 0.
 * Wire this to an <audio>'s onLoadedMetadata.
 */
export function fixInfiniteAudioDuration(audio: HTMLAudioElement) {
  if (audio.duration !== Infinity && !Number.isNaN(audio.duration)) return;
  audio.currentTime = Number.MAX_SAFE_INTEGER;
  const onTimeUpdate = () => {
    audio.currentTime = 0;
    audio.removeEventListener("timeupdate", onTimeUpdate);
  };
  audio.addEventListener("timeupdate", onTimeUpdate);
}

// Backend stores UTC but may omit the 'Z' suffix — append it so JS parses as
// UTC instead of local time (without this, IST users see times 5h30m off).
function utcIso(iso: string): string {
  return /[Z+\-]\d{2}/.test(iso) ? iso : iso + "Z";
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(utcIso(iso)).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(utcIso(iso)).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(utcIso(iso)).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export const BLOOM_COLOURS: Record<string, string> = {
  remember:  "bg-slate-100 text-slate-700",
  understand:"bg-blue-100 text-blue-700",
  apply:     "bg-green-100 text-green-700",
  analyze:   "bg-yellow-100 text-yellow-700",
  evaluate:  "bg-orange-100 text-orange-700",
  create:    "bg-purple-100 text-purple-700",
};

export const STATUS_COLOURS: Record<string, string> = {
  active:      "bg-green-100 text-green-700",
  completed:   "bg-blue-100 text-blue-700",
  ai_complete: "bg-purple-100 text-purple-700",
  processing:  "bg-yellow-100 text-yellow-700",
  failed:      "bg-red-100 text-red-700",
};

export const SYNC_COLOURS: Record<string, string> = {
  synced:  "text-green-600",
  syncing: "text-blue-500",
  pending: "text-slate-400",
  failed:  "text-orange-500",
};
