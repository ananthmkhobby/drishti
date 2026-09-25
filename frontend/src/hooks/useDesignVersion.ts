"use client";

import { useCallback, useEffect, useState } from "react";

export type DesignVersion = "classic" | "premium";

/**
 * Per-page opt-in for a redesigned view, remembered per-device via
 * localStorage — deliberately NOT a build-time flag. Each redesigned page
 * keeps its ORIGINAL, already-working render path completely untouched
 * ("classic") and adds the new one alongside it ("premium"); this hook only
 * decides which one renders. If a redesign has a problem in real classroom
 * use, switching back is one click for the teacher, right there on the
 * device — no redeploy, no waiting on us.
 *
 * `key` scopes the preference per redesigned surface (e.g. "overview",
 * "teaching") so a teacher can like one redesign and not another.
 */
export function useDesignVersion(key: string, defaultVersion: DesignVersion = "premium") {
  const storageKey = `aci_design_version_${key}`;
  const [version, setVersionState] = useState<DesignVersion>(defaultVersion);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(storageKey);
      if (stored === "classic" || stored === "premium") setVersionState(stored);
    } catch {
      // private mode / blocked storage — fall back to defaultVersion, fine
    } finally {
      setLoaded(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey]);

  const setVersion = useCallback((v: DesignVersion) => {
    setVersionState(v);
    try { window.localStorage.setItem(storageKey, v); } catch { /* fine, just won't persist */ }
  }, [storageKey]);

  const toggle = useCallback(() => {
    setVersion(version === "premium" ? "classic" : "premium");
  }, [version, setVersion]);

  // `loaded` lets a caller avoid a one-frame flash of the default version
  // before localStorage is read (SSR has no localStorage at all).
  return { version, setVersion, toggle, loaded };
}
