"use client";

import { use } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { useLanguage } from "@/contexts/LanguageContext";

export default function SessionLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = use(params);
  const pathname = usePathname();
  const { t } = useLanguage();

  const TABS = [
    { href: "",                 label: t.overview },
    { href: "capture",          label: t.capture },
    { href: "ocr",              label: t.ocr },
    { href: "notes",            label: t.notes },
    { href: "quiz",             label: t.quiz },
    { href: "experiments",      label: t.experiments },
    { href: "missing-concepts", label: t.gaps },
    { href: "homework",         label: t.homework },
    { href: "guided-practice",  label: t.guidedPractice },
    { href: "class-analysis",   label: t.classAnalysis },
    { href: "lesson-plan",      label: t.lessonPlan },
    { href: "textbook",         label: t.textbook },
    { href: "session-report",   label: t.sessionReport },
    { href: "tiqer",            label: t.tiqer },
  ];

  return (
    <div className="space-y-4">
      {/* Tab bar */}
      <nav className="flex items-center gap-1 overflow-x-auto rounded-xl bg-white border border-slate-200 px-2 py-1.5 no-scrollbar">
        {TABS.map(({ href, label }) => {
          const full    = href ? `/sessions/${sessionId}/${href}` : `/sessions/${sessionId}`;
          const isActive = href
            ? (pathname === full || pathname.startsWith(`${full}/`) || pathname.startsWith(`${full}?`))
            : pathname === `/sessions/${sessionId}`;
          return (
            <Link
              key={href}
              href={full}
              className={cn(
                "shrink-0 rounded-lg px-3 py-1.5 text-[0.8125rem] font-medium transition-colors whitespace-nowrap",
                isActive
                  ? "bg-indigo-600 text-white shadow-sm"
                  : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
              )}
            >
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Page content */}
      {children}
    </div>
  );
}
