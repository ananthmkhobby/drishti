"use client";

/**
 * Registers the Drishti service worker on first mount.
 * Rendered once in the root layout — no visual output.
 */

import { useEffect } from "react";

export function ServiceWorkerRegistrar() {
  useEffect(() => {
    if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;

    navigator.serviceWorker
      .register("/sw.js", { scope: "/" })
      .then((reg) => {
        if (process.env.NODE_ENV === "development") {
          console.info("[Drishti SW] registered:", reg.scope);
        }

        // Prompt for updates in production
        reg.addEventListener("updatefound", () => {
          const next = reg.installing;
          if (!next) return;
          next.addEventListener("statechange", () => {
            if (next.state === "installed" && navigator.serviceWorker.controller) {
              // New SW waiting — could show a toast here in the future
            }
          });
        });
      })
      .catch((err) => {
        if (process.env.NODE_ENV === "development") {
          console.warn("[Drishti SW] registration failed:", err);
        }
      });
  }, []);

  return null;
}
