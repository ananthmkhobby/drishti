"use client";

import { useState, useCallback, useRef } from "react";
import type { Language } from "@/components/ui/LanguageSelector";

const BASE =
  process.env.NEXT_PUBLIC_API_URL ??
  (process.env.NEXT_PUBLIC_USE_PROXY === "true" ? "/api/backend" : "http://localhost:8000/v1");

// Module-level cache shared across all hook instances — avoids re-translating
// the same strings when navigating between tabs.
const cache = new Map<string, string>();
function cKey(text: string, lang: Language) { return `${lang}\x00${text}`; }

export function useTranslation() {
  const [language, setLanguageState] = useState<Language>("english");
  const [translating, setTranslating] = useState(false);
  // Map from original → translated for current language
  const [tmap, setTmap] = useState<Map<string, string>>(new Map());
  const langRef = useRef<Language>("english");

  const translate = useCallback(async (texts: string[]) => {
    const lang = langRef.current;
    const unique = [...new Set(texts.filter((s) => s && s.trim()))];

    if (lang === "english" || unique.length === 0) {
      setTmap(new Map());
      return;
    }

    const uncached = unique.filter((t) => !cache.has(cKey(t, lang)));

    setTranslating(true);
    try {
      if (uncached.length > 0) {
        const res = await fetch(`${BASE}/translate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ texts: uncached, target_language: lang }),
        });
        if (res.ok) {
          const data: { translations: string[] } = await res.json();
          uncached.forEach((orig, i) => {
            if (data.translations[i]) cache.set(cKey(orig, lang), data.translations[i]);
          });
        }
      }

      const next = new Map<string, string>();
      unique.forEach((t) => {
        const v = cache.get(cKey(t, lang));
        if (v) next.set(t, v);
      });
      // Only update state if language hasn't changed mid-flight
      if (langRef.current === lang) setTmap(next);
    } catch (err) {
      console.error("Translation error:", err);
    } finally {
      setTranslating(false);
    }
  }, []);

  const setLanguage = useCallback((lang: Language) => {
    langRef.current = lang;
    setLanguageState(lang);
    if (lang === "english") setTmap(new Map());
  }, []);

  /** Translate a string — returns the original while loading */
  const t = useCallback(
    (text: string | null | undefined): string => {
      if (!text) return text ?? "";
      if (langRef.current === "english") return text;
      return tmap.get(text) ?? text;
    },
    [tmap],
  );

  return { language, setLanguage, translating, translate, t };
}
