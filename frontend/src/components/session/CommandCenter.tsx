"use client";

/**
 * The "reach anything in one or two clicks" redesign of the session
 * Overview page — additive only. Rendered ABOVE the existing Overview
 * content (SessionInfoCard, outputs grid, generate/reprocess buttons,
 * session stats all stay exactly as they are; only the old QuickActions
 * tile grid is hidden in favor of this one, since this one is a strict
 * superset of it — same routes, same tab bar in the layout above still
 * works regardless). See useDesignVersion for the classic/premium toggle
 * this is gated behind.
 */

import Link from "next/link";
import {
  ArrowRight, BookOpen, Book, Camera, ScanText, FileText, HelpCircle,
  FlaskConical, Lightbulb, ClipboardList, Target, ScanLine, BarChart3, Zap,
  Sparkles, Compass, Mic, Video,
} from "lucide-react";
import type { Textbook, TextbookChapterSummary } from "@/lib/api";

export interface HeroChapter {
  textbookId: string;
  chapter: TextbookChapterSummary;
  textbookTitle: string | null;
}

/** Picks the most recently-taught chapter across every textbook in this session, if any. */
export function findHeroChapter(textbooks: Textbook[] | undefined): HeroChapter | null {
  if (!textbooks) return null;
  let best: HeroChapter | null = null;
  for (const tb of textbooks) {
    for (const ch of tb.chapters ?? []) {
      if (!ch.started || !ch.last_taught_at) continue;
      if (!best || new Date(ch.last_taught_at) > new Date(best.chapter.last_taught_at!)) {
        best = { textbookId: tb.textbook_id, chapter: ch, textbookTitle: tb.title };
      }
    }
  }
  return best;
}

function ContinueTeachingHero({ sessionId, hero }: { sessionId: string; hero: HeroChapter }) {
  const { chapter, textbookId, textbookTitle } = hero;
  return (
    <div>
      <div className="cc-rise text-xs font-bold tracking-wide text-amber-700 mb-3">PICK UP WHERE YOU LEFT OFF</div>
      <div className="cc-rise relative overflow-hidden bg-white rounded-3xl p-8 sm:p-10 flex flex-col sm:flex-row gap-8 items-center shadow-[0_18px_48px_rgba(36,31,73,0.08)]" style={{ animationDelay: "60ms" }}>
        <div className="flex-1 min-w-0 flex flex-col gap-3">
          <span className="text-xs font-bold text-indigo-700 bg-indigo-50 px-3 py-1 rounded-full w-fit">
            {chapter.pedagogy === "quest" ? "QUEST · CONCEPT NOTES" : "TEXTBOOK"}{textbookTitle ? ` · ${textbookTitle.toUpperCase()}` : ""}
          </span>
          <h1 className="font-serif text-3xl sm:text-4xl font-semibold leading-tight tracking-tight text-slate-900" style={{ fontFamily: "var(--font-fraunces), Georgia, serif" }}>
            {chapter.title}
          </h1>
          <p className="text-sm text-slate-500">
            Pages {chapter.start_page}–{chapter.end_page}
            {chapter.segment_count > 0 && <> &middot; {chapter.segment_count} part{chapter.segment_count !== 1 ? "s" : ""} taught so far</>}
          </p>
          <div className="flex flex-wrap gap-3 mt-2">
            <Link
              href={`/sessions/${sessionId}/textbook/${textbookId}/${chapter.chapter_id}`}
              className="inline-flex items-center gap-2 bg-[#241F49] hover:bg-[#332B6B] hover:scale-[1.03] transition-all text-white px-6 py-3.5 rounded-2xl text-sm font-bold"
            >
              Continue teaching <ArrowRight className="h-4 w-4" />
            </Link>
            <Link
              href={`/sessions/${sessionId}/textbook`}
              className="inline-flex items-center gap-2 border border-slate-200 text-slate-600 px-5 py-3.5 rounded-2xl text-sm font-semibold hover:bg-slate-50 transition-colors"
            >
              See all chapters
            </Link>
          </div>
        </div>
        <div className="relative shrink-0">
          <div className="cc-drift pointer-events-none absolute inset-0 rounded-full opacity-60 blur-2xl" style={{ background: "radial-gradient(circle, #F6EAD3, transparent 70%)" }} />
          <div className="relative w-40 h-40 rounded-full flex items-center justify-center" style={{ background: "radial-gradient(circle at 34% 30%, #F6EAD3, #EDEAF9 72%)" }}>
            {chapter.pedagogy === "quest" ? <Compass className="h-14 w-14 text-indigo-700" /> : <BookOpen className="h-14 w-14 text-indigo-700" />}
          </div>
        </div>
      </div>
    </div>
  );
}

function StartFirstLessonHero({ sessionId }: { sessionId: string }) {
  return (
    <div className="cc-rise bg-white rounded-3xl p-8 sm:p-10 flex flex-col sm:flex-row gap-8 items-center shadow-[0_18px_48px_rgba(36,31,73,0.08)]">
      <div className="flex-1 min-w-0 flex flex-col gap-3">
        <span className="text-xs font-bold text-amber-700 bg-amber-50 px-3 py-1 rounded-full w-fit">GET STARTED</span>
        <h1 className="font-serif text-3xl font-semibold text-slate-900" style={{ fontFamily: "var(--font-fraunces), Georgia, serif" }}>
          Ready to teach your first chapter?
        </h1>
        <p className="text-sm text-slate-500 max-w-md">
          Upload a textbook or a concept-notes worksheet, and Drishti will teach it out loud, chapter by chapter.
        </p>
        <Link
          href={`/sessions/${sessionId}/textbook`}
          className="inline-flex items-center gap-2 bg-[#241F49] hover:bg-[#332B6B] transition-colors text-white px-6 py-3.5 rounded-2xl text-sm font-bold w-fit mt-2"
        >
          <Sparkles className="h-4 w-4" /> Start teaching
        </Link>
      </div>
    </div>
  );
}

interface Tile {
  href: string;
  label: string;
  icon: React.ReactNode;
  bg: string;
  iconColor: string;
}

function tileList(sessionId: string): Tile[] {
  const base = `/sessions/${sessionId}`;
  return [
    { href: `${base}/textbook`, label: "Textbook", icon: <Book className="h-[1.1875rem] w-[1.1875rem]" />, bg: "#EDEAF9", iconColor: "#453B87" },
    { href: `${base}/capture?autostart=camera`, label: "Capture board", icon: <Camera className="h-[1.1875rem] w-[1.1875rem]" />, bg: "#F6EAD3", iconColor: "#8A5D1E" },
    { href: `${base}/ocr`, label: "Board text (OCR)", icon: <ScanText className="h-[1.1875rem] w-[1.1875rem]" />, bg: "#EDEAF9", iconColor: "#453B87" },
    { href: `${base}/guided-practice`, label: "Guided practice", icon: <Target className="h-[1.1875rem] w-[1.1875rem]" />, bg: "#E7F1EA", iconColor: "#3E7A57" },
    { href: `${base}/notes`, label: "Notes", icon: <FileText className="h-[1.1875rem] w-[1.1875rem]" />, bg: "#EDEAF9", iconColor: "#453B87" },
    { href: `${base}/quiz`, label: "Quiz", icon: <HelpCircle className="h-[1.1875rem] w-[1.1875rem]" />, bg: "#F6EAD3", iconColor: "#8A5D1E" },
    { href: `${base}/experiments`, label: "Experiments", icon: <FlaskConical className="h-[1.1875rem] w-[1.1875rem]" />, bg: "#E7F1EA", iconColor: "#3E7A57" },
    { href: `${base}/homework`, label: "Homework", icon: <ClipboardList className="h-[1.1875rem] w-[1.1875rem]" />, bg: "#EDEAF9", iconColor: "#453B87" },
    { href: `${base}/missing-concepts`, label: "Opportunities", icon: <Lightbulb className="h-[1.1875rem] w-[1.1875rem]" />, bg: "#F6EAD3", iconColor: "#8A5D1E" },
    { href: `${base}/class-analysis`, label: "Classroom snapshot", icon: <ScanLine className="h-[1.1875rem] w-[1.1875rem]" />, bg: "#E7F1EA", iconColor: "#3E7A57" },
    { href: `${base}/lesson-plan`, label: "Lesson plan", icon: <BookOpen className="h-[1.1875rem] w-[1.1875rem]" />, bg: "#EDEAF9", iconColor: "#453B87" },
    { href: `${base}/session-report`, label: "Session report", icon: <BarChart3 className="h-[1.1875rem] w-[1.1875rem]" />, bg: "#F6EAD3", iconColor: "#8A5D1E" },
    { href: `${base}/tiqer`, label: "TiQer export", icon: <Zap className="h-[1.1875rem] w-[1.1875rem]" />, bg: "#E7F1EA", iconColor: "#3E7A57" },
  ];
}

function ActivityGrid({ sessionId }: { sessionId: string }) {
  return (
    <div>
      <div className="cc-rise text-xs font-bold text-slate-500 mb-3.5">JUMP TO AN ACTIVITY</div>
      <div className="grid grid-cols-2 xs:grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-3.5">
        {tileList(sessionId).map((t, idx) => (
          <Link
            key={t.href}
            href={t.href}
            className="cc-rise group bg-white rounded-2xl p-4 flex flex-col gap-3.5 shadow-[0_4px_14px_rgba(23,22,27,0.05)] hover:-translate-y-0.5 hover:shadow-[0_14px_32px_rgba(23,22,27,0.10)] transition-all"
            style={{ animationDelay: `${Math.min(idx, 10) * 35}ms` }}
          >
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center transition-transform group-hover:scale-110"
              style={{ background: t.bg, color: t.iconColor }}
            >
              {t.icon}
            </div>
            <span className="text-sm font-bold text-slate-900">{t.label}</span>
          </Link>
        ))}
      </div>
    </div>
  );
}

// Audio/video recording live inside the Capture page rather than as their
// own top-level routes, so without a direct link a teacher has no way to
// know they're there at all. These land pre-armed via ?autostart=… (see
// capture/page.tsx) — the camera/mic is already starting by the time the
// page appears, cutting the old "open Capture, then start it" tap.
function QuickCaptureRow({ sessionId }: { sessionId: string }) {
  const base = `/sessions/${sessionId}`;
  const items = [
    { href: `${base}/capture?autostart=audio`, label: "Record audio", icon: <Mic className="h-3.5 w-3.5" /> },
    { href: `${base}/capture?tab=video&autostart=video`, label: "Record video", icon: <Video className="h-3.5 w-3.5" /> },
  ];
  return (
    <div className="cc-rise flex flex-wrap items-center gap-2.5" style={{ animationDelay: "420ms" }}>
      <span className="text-xs font-bold text-slate-400">QUICK CAPTURE</span>
      {items.map((it) => (
        <Link
          key={it.href}
          href={it.href}
          className="inline-flex items-center gap-1.5 rounded-full bg-white border border-slate-200 px-3.5 py-2 text-xs font-semibold text-slate-600 shadow-[0_2px_8px_rgba(23,22,27,0.04)] hover:border-slate-300 hover:-translate-y-0.5 transition-all"
        >
          {it.icon} {it.label}
        </Link>
      ))}
    </div>
  );
}

export function CommandCenter({ sessionId, textbooks }: { sessionId: string; textbooks: Textbook[] | undefined }) {
  const hero = findHeroChapter(textbooks);
  return (
    <div className="space-y-9 mb-2">
      <style>{`
        @keyframes cc-rise-kf { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes cc-drift-kf { 0%,100% { transform: scale(1); } 50% { transform: scale(1.15); } }
        .cc-rise { animation: cc-rise-kf 560ms cubic-bezier(0.16,1,0.3,1) both; }
        .cc-drift { animation: cc-drift-kf 8s ease-in-out infinite; }
        @media (prefers-reduced-motion: reduce) {
          .cc-rise, .cc-drift { animation: none !important; }
        }
      `}</style>
      {hero
        ? <ContinueTeachingHero sessionId={sessionId} hero={hero} />
        : <StartFirstLessonHero sessionId={sessionId} />}
      <ActivityGrid sessionId={sessionId} />
      <QuickCaptureRow sessionId={sessionId} />
    </div>
  );
}
