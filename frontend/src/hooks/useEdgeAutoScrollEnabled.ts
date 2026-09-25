"use client";

import { useSyncExternalStore } from "react";

// Shared on/off switch for the air-mouse edge-of-screen auto-scroll
// (useEdgeAutoScroll.ts) — a plain module-level store + useSyncExternalStore
// instead of a Context, since the toggle button (TopBar) and the hook
// itself (mounted once via EdgeAutoScroll in the dashboard layout) are
// siblings, not parent/child, and this avoids adding a new Provider to the
// tree for one boolean. Defaults ON (matches the existing, already-shipped
// behavior) — this is an opt-out for when it's getting in the way, e.g.
// reported 2026-09-22: "sometimes ... might become annoying", not an
// opt-in feature flag.
const STORAGE_KEY = "aci_edge_autoscroll_enabled";

let enabledState = true;
let hydrated = false;
const listeners = new Set<() => void>();

function hydrateOnce() {
  if (hydrated || typeof window === "undefined") return;
  hydrated = true;
  try {
    if (window.localStorage.getItem(STORAGE_KEY) === "0") enabledState = false;
  } catch {
    // private mode / blocked storage — fine, stays at the in-memory default
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): boolean {
  hydrateOnce();
  return enabledState;
}

// Server and pre-hydration client snapshots must agree (both "true", the
// default) so this never causes a hydration mismatch — the real persisted
// value (if different) applies from the first client read via hydrateOnce.
function getServerSnapshot(): boolean {
  return true;
}

export function setEdgeAutoScrollEnabled(next: boolean) {
  enabledState = next;
  try {
    window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
  } catch {
    // fine — just won't persist across reloads
  }
  listeners.forEach((l) => l());
}

export function useEdgeAutoScrollEnabled(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
