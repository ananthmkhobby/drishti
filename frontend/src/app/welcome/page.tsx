"use client";

/**
 * The app's new entry screen — shown every time the app loads, before the
 * session dashboard: a welcome moment, then grade/class selection, then an
 * attendance pass, then a quick stats recap, then into the existing
 * dashboard unchanged. Grade/class here is deliberately NOT wired to any
 * session data yet — it's a UI step on the way to attendance, not a
 * session-creation flow (that's still the dashboard's own "New Session").
 * Attendance itself is RANDOM for now, standing in for a real TiQer
 * camera-based roll-call integration — every present/absent call here is
 * make-believe, never a real record of who showed up.
 */

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { GraduationCap, ArrowRight, Users, CheckCircle2, ScanLine } from "lucide-react";

const INDIGO = "#241F49";
const INDIGO_DEEP = "#332B6B";
const GOLD = "#D7A24E";
const GOLD_DEEP = "#8A5D1E";
const SERIF = { fontFamily: "var(--font-fraunces), Georgia, serif" };

const GRADES = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"];
const SECTIONS = ["A", "B", "C", "D"];

// A varied pool of plausible Indian student names — deliberately mixing
// short and long ones (a name with three parts, an unusually long single
// name) so the attendance grid's ellipsis-truncation actually gets
// exercised, not just short two-word names that always fit. Placeholder
// only, same as the attendance itself — replaced once a real roster
// exists (see the file's own top comment).
const NAME_POOL = [
  "Aarav Sharma", "Priya Patel", "Rohan Gupta", "Ananya Reddy", "Vikram Singh",
  "Diya Mehta", "Arjun Nair", "Kavya Iyer", "Aditya Rao", "Ishita Verma",
  "Karthik Krishnan", "Sanya Malhotra", "Rahul Desai", "Meera Pillai", "Siddharth Chatterjee",
  "Anjali Bhatt", "Varun Kapoor", "Riya Joshi", "Nikhil Agarwal", "Pooja Menon",
  "Aryan Choudhury", "Shreya Bose", "Manav Trivedi", "Tanvi Saxena", "Rohit Bansal",
  "Neha Kulkarni", "Aakash Ganguly", "Simran Chawla", "Devansh Mishra", "Ritika Bhattacharya",
  "Yash Thakur", "Aisha Khan", "Om Prakash Yadav", "Lakshmi Narayanan Swaminathan", "Krishna Venkataraman",
  "Divya Subramaniam", "Harsh Vardhan Rathore", "Zara Fatima Sheikh", "Advait Deshpande", "Ira Chandrasekaran",
];

type Student = { cardNo: number; name: string };
type Status = "pending" | "present" | "absent";

function buildRoster(): Student[] {
  const count = 30 + Math.floor(Math.random() * 11); // 30-40
  const shuffled = [...NAME_POOL].sort(() => Math.random() - 0.5);
  const names: string[] = [];
  for (let i = 0; i < count; i++) names.push(shuffled[i % shuffled.length]);
  return names.map((name, i) => ({ cardNo: i + 1, name }));
}

type Step = "welcome" | "grade" | "attendance" | "summary";

export default function WelcomePage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("welcome");
  const [grade, setGrade] = useState("5");
  const [section, setSection] = useState("A");
  const [roster] = useState<Student[]>(() => buildRoster());
  const [statuses, setStatuses] = useState<Record<number, Status>>({});
  const [scanning, setScanning] = useState(false);
  const [exiting, setExiting] = useState(false);

  // Welcome/attendance is dark and shown on every app load, then hands off
  // to the (light) dashboard — a hard cut between the two was reported as
  // jarring precisely because it repeats every class period, not just on a
  // one-time first run. Fades this page out before navigating; the
  // dashboard layout's own fade-in (see (dashboard)/layout.tsx) picks up
  // from there, matching WC_EXIT_MS below.
  const WC_EXIT_MS = 320;
  function goToDashboard() {
    setExiting(true);
    // Grade/section were just picked for attendance — passing them along
    // lets the sessions list surface the matching class at the top instead
    // of making the teacher scroll to find it (reported 2026-09-24).
    // Section isn't stored on sessions at all yet, so it's carried through
    // for display only; matching itself is grade-only (see matchesGrade).
    const params = new URLSearchParams({ grade, section });
    setTimeout(() => router.push(`/sessions?${params.toString()}`), WC_EXIT_MS);
  }

  const presentCount = useMemo(
    () => Object.values(statuses).filter((s) => s === "present").length,
    [statuses],
  );
  const decidedCount = useMemo(
    () => Object.values(statuses).filter((s) => s !== "pending").length,
    [statuses],
  );
  const allDecided = decidedCount === roster.length && roster.length > 0;

  function startScan() {
    setScanning(true);
    setStatuses({});
    // Reveals present/absent one card at a time, staggered — reads as a
    // real roll-call happening instead of every box flipping color at
    // once. ~88% present, close to a realistic classroom attendance rate
    // and to the "29/32" example this was speced against.
    const order = [...roster].sort(() => Math.random() - 0.5);
    order.forEach((student, i) => {
      setTimeout(() => {
        setStatuses((prev) => ({ ...prev, [student.cardNo]: Math.random() < 0.88 ? "present" : "absent" }));
        if (i === order.length - 1) setTimeout(() => setScanning(false), 300);
      }, i * 70);
    });
  }

  // Voice bridge from ClassroomBrain.tsx (mounted at the app root, not just
  // inside the dashboard, specifically so it's available here — see
  // app/layout.tsx). Each handler is a no-op unless the matching step is
  // actually current, same guard the on-screen buttons themselves have, so
  // e.g. saying "see summary" mid-scan doesn't skip ahead of the scan.
  useEffect(() => {
    function onBegin() {
      if (step === "welcome") setStep("grade");
    }
    function onTakeAttendance() {
      if (step === "grade") { setStep("attendance"); startScan(); }
    }
    function onSeeSummary() {
      if (step === "attendance" && allDecided) setStep("summary");
    }
    function onGoToDashboard() {
      if (step === "summary" && !exiting) goToDashboard();
    }
    window.addEventListener("classroom-brain:welcome_begin", onBegin);
    window.addEventListener("classroom-brain:welcome_take_attendance", onTakeAttendance);
    window.addEventListener("classroom-brain:welcome_see_summary", onSeeSummary);
    window.addEventListener("classroom-brain:welcome_go_to_dashboard", onGoToDashboard);
    return () => {
      window.removeEventListener("classroom-brain:welcome_begin", onBegin);
      window.removeEventListener("classroom-brain:welcome_take_attendance", onTakeAttendance);
      window.removeEventListener("classroom-brain:welcome_see_summary", onSeeSummary);
      window.removeEventListener("classroom-brain:welcome_go_to_dashboard", onGoToDashboard);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, allDecided, exiting]);

  return (
    <div
      className={`wc-page min-h-screen flex flex-col items-center justify-center px-4 py-10 ${exiting ? "wc-page-exiting" : ""}`}
      style={{ background: `radial-gradient(ellipse 1200px 700px at 50% 20%, ${INDIGO_DEEP}, #131022 68%)`, color: "#F5F1E7" }}
    >
      <style>{`
        @keyframes wc-rise { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes wc-pop { 0% { transform: scale(0.85); opacity: 0; } 60% { transform: scale(1.05); } 100% { transform: scale(1); opacity: 1; } }
        .wc-rise { animation: wc-rise 480ms cubic-bezier(0.16,1,0.3,1) both; }
        .wc-pop { animation: wc-pop 320ms cubic-bezier(0.16,1,0.3,1) both; }
        .wc-page { opacity: 1; transition: opacity ${WC_EXIT_MS}ms ease; }
        .wc-page-exiting { opacity: 0; }
        @media (prefers-reduced-motion: reduce) { .wc-rise, .wc-pop { animation: none !important; } .wc-page { transition: none; } }
      `}</style>

      {step === "welcome" && (
        <div className="wc-rise flex flex-col items-center gap-7 text-center max-w-xl">
          <div className="flex h-20 w-20 items-center justify-center rounded-3xl" style={{ background: "rgba(215,162,78,0.14)" }}>
            <GraduationCap className="h-10 w-10" style={{ color: GOLD }} />
          </div>
          <div className="space-y-3">
            <p className="text-xs font-bold uppercase tracking-[0.2em]" style={{ color: GOLD }}>Drishti</p>
            <h1 className="text-4xl sm:text-5xl font-semibold leading-tight" style={SERIF}>
              Learning, made easy.
            </h1>
            <p className="text-base text-[#C9C4D6] max-w-md mx-auto">
              Capture the board, teach with AI, and keep every student's progress in one place — let's get today's class started.
            </p>
          </div>
          <button
            onClick={() => setStep("grade")}
            className="flex items-center gap-2 rounded-full px-8 py-4 text-base font-bold transition-transform hover:scale-105"
            style={{ background: `linear-gradient(135deg, ${GOLD}, ${GOLD_DEEP})`, color: "#1C1200" }}
          >
            Let's begin <ArrowRight className="h-5 w-5" />
          </button>
        </div>
      )}

      {step === "grade" && (
        <div className="wc-rise flex flex-col items-center gap-7 text-center w-full max-w-md">
          <div className="space-y-2">
            <p className="text-xs font-bold uppercase tracking-[0.2em]" style={{ color: GOLD }}>Today's class</p>
            <h1 className="text-3xl font-semibold" style={SERIF}>Which grade and section?</h1>
          </div>
          <div className="grid grid-cols-2 gap-4 w-full">
            <label className="flex flex-col gap-2 text-left">
              <span className="text-xs font-semibold uppercase tracking-wide text-[#A79FC4]">Grade</span>
              <select
                value={grade}
                onChange={(e) => setGrade(e.target.value)}
                className="rounded-2xl border border-white/15 bg-white/8 px-4 py-3.5 text-lg font-semibold text-white focus:outline-none focus:ring-2"
                style={{ colorScheme: "dark" }}
              >
                {GRADES.map((g) => <option key={g} value={g}>Grade {g}</option>)}
              </select>
            </label>
            <label className="flex flex-col gap-2 text-left">
              <span className="text-xs font-semibold uppercase tracking-wide text-[#A79FC4]">Section</span>
              <select
                value={section}
                onChange={(e) => setSection(e.target.value)}
                className="rounded-2xl border border-white/15 bg-white/8 px-4 py-3.5 text-lg font-semibold text-white focus:outline-none focus:ring-2"
                style={{ colorScheme: "dark" }}
              >
                {SECTIONS.map((s) => <option key={s} value={s}>Section {s}</option>)}
              </select>
            </label>
          </div>
          <button
            onClick={() => setStep("attendance")}
            className="flex items-center gap-2 rounded-full px-8 py-4 text-base font-bold transition-transform hover:scale-105"
            style={{ background: `linear-gradient(135deg, ${GOLD}, ${GOLD_DEEP})`, color: "#1C1200" }}
          >
            <Users className="h-5 w-5" /> Take attendance
          </button>
        </div>
      )}

      {step === "attendance" && (
        <div className="wc-rise flex flex-col items-center gap-6 w-full max-w-5xl">
          <div className="text-center space-y-1">
            <p className="text-xs font-bold uppercase tracking-[0.2em]" style={{ color: GOLD }}>
              Grade {grade} · Section {section}
            </p>
            <h1 className="text-2xl sm:text-3xl font-semibold" style={SERIF}>
              {allDecided ? "Attendance complete" : scanning ? "Taking attendance…" : "Ready to take attendance"}
            </h1>
            <p className="text-sm text-[#A79FC4]">{roster.length} students on the roster</p>
          </div>

          <div className="grid grid-cols-4 sm:grid-cols-6 md:grid-cols-8 gap-2.5 sm:gap-3 w-full">
            {roster.map((s) => {
              const status = statuses[s.cardNo] ?? "pending";
              const bg = status === "present" ? "rgba(34,197,94,0.16)" : status === "absent" ? "rgba(249,115,22,0.16)" : "rgba(255,255,255,0.06)";
              const border = status === "present" ? "#22C55E" : status === "absent" ? "#F97316" : "rgba(255,255,255,0.14)";
              const dot = status === "present" ? "#22C55E" : status === "absent" ? "#F97316" : "#6B7280";
              return (
                <div
                  key={s.cardNo}
                  className={status !== "pending" ? "wc-pop" : ""}
                  style={{ background: bg, border: `1px solid ${border}`, borderRadius: "1rem" }}
                >
                  <div className="flex flex-col items-center gap-1.5 px-2 py-3">
                    <div className="flex h-2 w-2 rounded-full shrink-0" style={{ background: dot }} />
                    <span className="text-[0.6875rem] font-bold text-[#8983A3]">#{s.cardNo}</span>
                    <span className="w-full truncate text-center text-xs font-semibold text-white" title={s.name}>
                      {s.name}
                    </span>
                    <span
                      className="text-[0.625rem] font-bold uppercase tracking-wide"
                      style={{ color: status === "present" ? "#4ADE80" : status === "absent" ? "#FB923C" : "#6B7280" }}
                    >
                      {status === "pending" ? "—" : status}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>

          {!allDecided ? (
            <button
              onClick={startScan}
              disabled={scanning}
              className="flex items-center gap-2 rounded-full px-8 py-4 text-base font-bold transition-transform hover:scale-105 disabled:opacity-60 disabled:hover:scale-100"
              style={{ background: `linear-gradient(135deg, ${GOLD}, ${GOLD_DEEP})`, color: "#1C1200" }}
            >
              <ScanLine className="h-5 w-5" /> {scanning ? "Scanning…" : "Start"}
            </button>
          ) : (
            <button
              onClick={() => setStep("summary")}
              className="flex items-center gap-2 rounded-full px-8 py-4 text-base font-bold transition-transform hover:scale-105"
              style={{ background: `linear-gradient(135deg, ${GOLD}, ${GOLD_DEEP})`, color: "#1C1200" }}
            >
              See summary <ArrowRight className="h-5 w-5" />
            </button>
          )}
        </div>
      )}

      {step === "summary" && (
        <div className="wc-rise flex flex-col items-center gap-7 text-center max-w-md">
          <div className="flex h-20 w-20 items-center justify-center rounded-3xl" style={{ background: "rgba(34,197,94,0.14)" }}>
            <CheckCircle2 className="h-10 w-10" style={{ color: "#4ADE80" }} />
          </div>
          <div className="space-y-2">
            <p className="text-xs font-bold uppercase tracking-[0.2em]" style={{ color: GOLD }}>
              Grade {grade} · Section {section}
            </p>
            <h1 className="text-5xl font-semibold tabular-nums" style={SERIF}>
              {presentCount}/{roster.length}
            </h1>
            <p className="text-base text-[#C9C4D6]">students present today</p>
          </div>
          <button
            onClick={goToDashboard}
            disabled={exiting}
            className="flex items-center gap-2 rounded-full px-8 py-4 text-base font-bold transition-transform hover:scale-105"
            style={{ background: `linear-gradient(135deg, ${GOLD}, ${GOLD_DEEP})`, color: "#1C1200" }}
          >
            Go to dashboard <ArrowRight className="h-5 w-5" />
          </button>
        </div>
      )}
    </div>
  );
}
