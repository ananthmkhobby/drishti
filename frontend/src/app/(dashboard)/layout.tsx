import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";
import { EdgeAutoScroll } from "@/components/layout/EdgeAutoScroll";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    // This layout mounts once per arrival from OUTSIDE the dashboard route
    // group (e.g. from /welcome) and stays mounted across navigation
    // between dashboard pages, so the fade-in below plays exactly once on
    // that entrance — not on every in-dashboard navigation — matching the
    // fade-out on /welcome's "Go to dashboard" (see its WC_EXIT_MS).
    <div className="dash-fade-in flex h-screen overflow-hidden bg-slate-50">
      <style>{`
        @keyframes dash-fade-in-kf { from { opacity: 0; } to { opacity: 1; } }
        .dash-fade-in { animation: dash-fade-in-kf 320ms ease both; }
        @media (prefers-reduced-motion: reduce) { .dash-fade-in { animation: none; } }
      `}</style>
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <TopBar />
        <main className="flex-1 overflow-y-auto p-4 md:p-6" data-edge-autoscroll-target>
          {children}
        </main>
      </div>
      <EdgeAutoScroll />
    </div>
  );
}
