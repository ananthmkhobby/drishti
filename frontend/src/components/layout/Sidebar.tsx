"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  BookOpen,
  RefreshCw,
  Brain,
  Zap,
  BarChart2,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/sessions",     label: "Sessions",    icon: LayoutDashboard },
  { href: "/sessions/new", label: "New Session", icon: BookOpen },
  { href: "/reports",      label: "Reports",     icon: BarChart2 },
  { href: "/sync",         label: "Sync Status", icon: RefreshCw },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden md:flex w-56 shrink-0 flex-col border-r border-slate-200 bg-white">
      {/* Logo */}
      <div className="flex h-14 items-center gap-2 border-b border-slate-100 px-4">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-600">
          <Brain className="h-4 w-4 text-white" />
        </div>
        <span className="text-sm font-bold text-slate-900">Drishti</span>
        <span className="text-xs text-slate-400 mt-0.5">Teacher</span>
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-0.5 p-3">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active =
            pathname === href ||
            (href !== "/sessions/new" && pathname.startsWith(href + "/"));
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-indigo-50 text-indigo-700 font-medium"
                  : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="border-t border-slate-100 p-3">
        <div className="flex items-center gap-2 px-3 py-2">
          <div className="h-7 w-7 rounded-full bg-indigo-100 flex items-center justify-center">
            <Zap className="h-3.5 w-3.5 text-indigo-600" />
          </div>
          <div>
            <p className="text-xs font-medium text-slate-900">Teacher</p>
            <p className="text-[0.625rem] text-slate-400">Dev mode</p>
          </div>
        </div>
      </div>
    </aside>
  );
}
