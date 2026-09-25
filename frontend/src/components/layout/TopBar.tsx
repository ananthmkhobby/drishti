"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight, Brain, Globe, ArrowUpDown } from "lucide-react";
import { useLanguage } from "@/contexts/LanguageContext";
import { LOCALE_LABELS, type Locale } from "@/lib/i18n";
import { useEdgeAutoScrollEnabled, setEdgeAutoScrollEnabled } from "@/hooks/useEdgeAutoScrollEnabled";

const CRUMB_MAP: Record<string, string> = {
  sessions:           "sessions",
  new:                "newSession",
  capture:            "capture",
  ocr:                "ocr",
  notes:              "notes",
  quiz:               "quiz",
  tiqer:              "tiqer",
  experiments:        "experiments",
  "missing-concepts": "gaps",
  "class-analysis":   "classAnalysis",
  "lesson-plan":      "lessonPlan",
  sync:               "sync",
};

export function TopBar() {
  const pathname = usePathname();
  const { locale, setLocale, t } = useLanguage();
  const [langOpen, setLangOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const edgeScrollEnabled = useEdgeAutoScrollEnabled();

  // Close dropdown on outside click
  useEffect(() => {
    function handle(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setLangOpen(false);
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, []);

  const parts = pathname.split("/").filter(Boolean);
  const crumbs: { label: string; href: string }[] = [];
  let running = "";
  for (const part of parts) {
    running += `/${part}`;
    const isUUID = /^[0-9a-f-]{36}$/.test(part);
    const key = CRUMB_MAP[part];
    const label = isUUID ? t.session : (key ? (t as Record<string, string>)[key] ?? part : part);
    crumbs.push({ label, href: running });
  }

  return (
    <header className="flex h-14 items-center gap-2 border-b border-slate-200 bg-white px-4">
      {/* Mobile logo */}
      <Link href="/sessions" className="flex md:hidden items-center gap-1.5 mr-2">
        <div className="flex h-6 w-6 items-center justify-center rounded-md bg-indigo-600">
          <Brain className="h-3.5 w-3.5 text-white" />
        </div>
        <span className="text-sm font-bold text-slate-900">Drishti</span>
      </Link>

      {/* Breadcrumbs */}
      <nav className="flex flex-1 items-center gap-1 text-sm text-slate-500 overflow-x-auto min-w-0">
        {crumbs.map((c, i) => (
          <span key={c.href} className="flex items-center gap-1 shrink-0">
            {i > 0 && <ChevronRight className="h-3.5 w-3.5 text-slate-300" />}
            {i === crumbs.length - 1 ? (
              <span className="font-medium text-slate-900">{c.label}</span>
            ) : (
              <Link href={c.href} className="hover:text-slate-900 transition-colors">
                {c.label}
              </Link>
            )}
          </span>
        ))}
      </nav>

      {/* Air-mouse edge-of-screen auto-scroll toggle — off by default it
          would be a behavior regression for the kiosk hardware this was
          built for, so this defaults ON and is purely an escape hatch for
          when hovering near an edge for another reason unintentionally
          scrolls the page (reported 2026-09-22). */}
      <button
        onClick={() => setEdgeAutoScrollEnabled(!edgeScrollEnabled)}
        className={`flex shrink-0 items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors ${
          edgeScrollEnabled
            ? "border-indigo-200 bg-indigo-50 text-indigo-700 hover:bg-indigo-100"
            : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
        }`}
        title={edgeScrollEnabled ? "Edge scroll is on — click to turn off" : "Edge scroll is off — click to turn on"}
        aria-pressed={edgeScrollEnabled}
      >
        <ArrowUpDown className={`h-3.5 w-3.5 ${edgeScrollEnabled ? "text-indigo-500" : "text-slate-400"}`} />
        <span className="hidden sm:inline">Edge scroll {edgeScrollEnabled ? "on" : "off"}</span>
      </button>

      {/* Language switcher */}
      <div className="relative shrink-0" ref={menuRef}>
        <button
          onClick={() => setLangOpen((o) => !o)}
          className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 transition-colors"
          title="Change language"
        >
          <Globe className="h-3.5 w-3.5 text-indigo-500" />
          <span className="hidden sm:inline">{LOCALE_LABELS[locale]}</span>
        </button>

        {langOpen && (
          <div className="absolute right-0 top-full mt-1 z-50 min-w-[8.75rem] rounded-xl border border-slate-200 bg-white shadow-lg py-1 overflow-hidden">
            {(Object.entries(LOCALE_LABELS) as [Locale, string][]).map(([code, label]) => (
              <button
                key={code}
                onClick={() => { setLocale(code); setLangOpen(false); }}
                className={`w-full text-left px-3 py-2 text-sm transition-colors ${
                  locale === code
                    ? "bg-indigo-50 text-indigo-700 font-semibold"
                    : "text-slate-700 hover:bg-slate-50"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        )}
      </div>
    </header>
  );
}
