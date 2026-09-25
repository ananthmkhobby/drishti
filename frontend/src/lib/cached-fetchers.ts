/**
 * Cached fetchers for offline-first SWR usage.
 *
 * Pattern: try the real API call first. On success, write to IDB cache and return.
 * On network failure (offline or error), fall back to IDB cache so the page
 * still renders. Cached data older than 7 days is not served (forces refresh).
 */

import { api, type Session, type SessionOutputs } from "@/lib/api";
import {
  cacheSessions,
  getCachedSessions,
  cacheOutputs,
  getCachedOutputs,
} from "@/lib/offline-store";

// ── Sessions list ──────────────────────────────────────────────────────────────

export async function fetchSessionsCached(
  teacherId: string
): Promise<{ sessions: Session[]; total: number; _fromCache?: boolean }> {
  try {
    const data = await api.getSessions(teacherId);
    // Write to cache on success (non-blocking)
    cacheSessions(teacherId, data as { sessions: Session[]; total: number }).catch(() => {});
    return data as { sessions: Session[]; total: number };
  } catch {
    const cached = await getCachedSessions(teacherId).catch(() => undefined);
    if (cached) {
      return {
        sessions: cached.sessions as Session[],
        total: cached.total,
        _fromCache: true,
      };
    }
    throw new Error("Offline and no cached sessions available");
  }
}

// ── Session outputs ────────────────────────────────────────────────────────────

export async function fetchOutputsCached(
  sessionId: string
): Promise<SessionOutputs & { _fromCache?: boolean }> {
  try {
    const data = await api.getOutputs(sessionId);
    // Write to cache on success (non-blocking)
    cacheOutputs(sessionId, data).catch(() => {});
    return data;
  } catch {
    const cached = await getCachedOutputs(sessionId).catch(() => undefined);
    if (cached) {
      return {
        session_id: cached.session_id,
        outputs: cached.outputs as SessionOutputs["outputs"],
        total_tokens: cached.total_tokens,
        _fromCache: true,
      };
    }
    throw new Error("Offline and no cached outputs available");
  }
}
