"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { BookOpen, Settings2, ChevronDown, CheckCircle2, Pencil } from "lucide-react";
import { api, DEV_TEACHER_ID } from "@/lib/api";
import { generateUUID } from "@/lib/uuid";
import { savePendingSession } from "@/lib/offline-store";
import {
  getClassroomSettings,
  saveClassroomSettings,
  classroomLabel,
  type ClassroomSettings,
} from "@/lib/classroom-settings";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";

const GRADES = [
  "Grade 1","Grade 2","Grade 3","Grade 4","Grade 5",
  "Grade 6","Grade 7","Grade 8","Grade 9","Grade 10",
  "Grade 11","Grade 12",
];

const BOARDS = [
  { value: "chalkboard", label: "Chalkboard",  emoji: "🖊️" },
  { value: "whiteboard", label: "Whiteboard",  emoji: "📋" },
  { value: "smartboard", label: "Smart Board", emoji: "💻" },
  { value: "notebook",   label: "Notebook",    emoji: "📓" },
];

function Select({
  value, onChange, children, placeholder,
}: {
  value: string; onChange: (v: string) => void; children: React.ReactNode; placeholder?: string;
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="w-full appearance-none rounded-lg border border-slate-200 bg-white px-3 py-2.5 pr-8 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 text-slate-900"
      >
        {placeholder && <option value="">{placeholder}</option>}
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
    </div>
  );
}

export default function NewSessionPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Classroom settings state (loaded from localStorage)
  const [classroom, setClassroom] = useState<ClassroomSettings | null>(null);
  const [editingClassroom, setEditingClassroom] = useState(false);
  const [tempGrade, setTempGrade] = useState("Grade 5");
  const [tempClassName, setTempClassName] = useState("");
  const [tempBoard, setTempBoard] = useState("chalkboard");

  // Per-session overrides
  const [boardType, setBoardType] = useState("chalkboard");
  const [captureMode, setCaptureMode] = useState("time_based");
  const [intervalSec, setIntervalSec] = useState("30");
  // Topic and instructor are per-session, not remembered in classroom
  // settings — this is a shared device used by multiple instructors
  // throughout the day, so defaulting to "whoever used it last" would be
  // actively wrong more often than it'd help.
  const [topic, setTopic] = useState("");
  const [instructorName, setInstructorName] = useState("");
  const [showDetails, setShowDetails] = useState(false);

  // Load classroom settings on mount
  useEffect(() => {
    const saved = getClassroomSettings();
    if (saved) {
      setClassroom(saved);
      setBoardType(saved.boardType || "chalkboard");
    } else {
      // First time — prompt setup
      setEditingClassroom(true);
    }
  }, []);

  function openEditClassroom() {
    if (classroom) {
      setTempGrade(classroom.grade || "Grade 5");
      setTempClassName(classroom.className || "");
      setTempBoard(classroom.boardType || "chalkboard");
    }
    setEditingClassroom(true);
  }

  function saveClassroom() {
    const s: ClassroomSettings = {
      grade: tempGrade,
      className: tempClassName,
      boardType: tempBoard,
    };
    saveClassroomSettings(s);
    setClassroom(s);
    setBoardType(tempBoard);
    setEditingClassroom(false);
  }

  async function handleStart(e?: React.FormEvent) {
    e?.preventDefault();
    setError("");
    const grade = classroom?.grade ?? "";
    setLoading(true);

    // Generate UUID client-side so we can navigate immediately even if offline.
    // The server will use this same UUID when the session syncs.
    const clientId = generateUUID();

    const payload = {
      teacher_id: DEV_TEACHER_ID,
      grade: grade || null,
      board_type: boardType,
      capture_mode: captureMode,
      capture_interval_sec: parseInt(intervalSec) || 30,
      classroom_id: null,
      subject: null,
      title: topic.trim() || null,
      instructor_name: instructorName.trim() || null,
    };

    try {
      // Try online path first — identical behaviour to before for WiFi users
      const res = await api.createSession({
        ...payload,
        client_session_id: clientId,
      });
      router.push(`/sessions/${res.session_id}/capture`);
    } catch {
      // Offline fallback — store in IDB and navigate using the client UUID
      try {
        await savePendingSession({
          id:           clientId,
          payload,
          status:       "pending",
          retryCount:   0,
          nextRetryAt:  Date.now(),
          createdAt:    Date.now(),
          errorMessage: null,
        });
        router.push(`/sessions/${clientId}/capture`);
      } catch (idbErr: unknown) {
        setError(idbErr instanceof Error ? idbErr.message : "Failed to create session offline.");
        setLoading(false);
      }
    }
  }

  // ─── Classroom setup form ────────────────────────────────────────────────
  if (editingClassroom) {
    return (
      <div className="mx-auto max-w-md space-y-6">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600">
            <Settings2 className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-900">Classroom Setup</h1>
            <p className="text-sm text-slate-500">
              Set once — used for every session on this device
            </p>
          </div>
        </div>

        <Card>
          <CardContent className="pt-6 space-y-5">
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-slate-700">Grade / Class</label>
              <Select value={tempGrade} onChange={setTempGrade} placeholder="Select grade…">
                {GRADES.map(g => <option key={g} value={g}>{g}</option>)}
              </Select>
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium text-slate-700">
                Class Name / Section
                <span className="ml-1 text-xs text-slate-400 font-normal">(optional)</span>
              </label>
              <input
                type="text"
                value={tempClassName}
                onChange={e => setTempClassName(e.target.value)}
                placeholder="e.g. Section A, Room 3, Morning Batch"
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium text-slate-700">Default Board Type</label>
              <div className="grid grid-cols-3 gap-2">
                {BOARDS.map(b => (
                  <button
                    key={b.value}
                    type="button"
                    onClick={() => setTempBoard(b.value)}
                    className={`rounded-lg border p-3 text-center text-xs font-medium transition-all ${
                      tempBoard === b.value
                        ? "border-indigo-500 bg-indigo-50 text-indigo-700"
                        : "border-slate-200 text-slate-600 hover:border-slate-300"
                    }`}
                  >
                    <div className="text-lg mb-1">{b.emoji}</div>
                    {b.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="rounded-lg bg-blue-50 px-4 py-3 text-sm text-blue-700">
              <strong>💡 AI auto-detects the subject</strong> from what's written on the board —
              you don't need to set it here.
            </div>

            <div className="flex gap-3 pt-1">
              {classroom && (
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setEditingClassroom(false)}
                  className="flex-1"
                >
                  Cancel
                </Button>
              )}
              <Button
                type="button"
                onClick={saveClassroom}
                disabled={!tempGrade}
                className="flex-1"
              >
                <CheckCircle2 className="h-4 w-4" />
                {classroom ? "Save Changes" : "Save & Continue"}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ─── Quick session start form ────────────────────────────────────────────
  return (
    <div className="mx-auto max-w-md space-y-6">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600">
          <BookOpen className="h-5 w-5 text-white" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-slate-900">New Session</h1>
          <p className="text-sm text-slate-500">Start capturing the board</p>
        </div>
      </div>

      {/* Classroom badge */}
      {classroom && (
        <div className="flex items-center justify-between rounded-xl bg-indigo-50 border border-indigo-100 px-4 py-3">
          <div>
            <p className="text-xs text-indigo-500 font-medium uppercase tracking-wide">Classroom</p>
            <p className="text-sm font-semibold text-indigo-900 mt-0.5">{classroomLabel(classroom)}</p>
          </div>
          <button
            onClick={openEditClassroom}
            className="flex items-center gap-1.5 text-xs text-indigo-600 hover:text-indigo-800 font-medium"
          >
            <Pencil className="h-3.5 w-3.5" /> Change
          </button>
        </div>
      )}

      {/* Primary path: no typing required at all. Subject and topic get
          filled in automatically from the board's own content once the
          first photo is OCR'd (see backend _detect_subject_and_topic) —
          everything below is only for a teacher who wants to set something
          BEFORE capturing (a different instructor, a non-default board). */}
      <Button onClick={() => handleStart()} disabled={loading} loading={loading} className="w-full" size="lg">
        <BookOpen className="h-4 w-4" /> Start Capturing Now
      </Button>
      {error && <p className="text-sm text-red-600">{error}</p>}

      <button
        type="button"
        onClick={() => setShowDetails((v) => !v)}
        className="w-full text-center text-xs font-medium text-slate-500 hover:text-slate-700"
      >
        {showDetails ? "Hide options" : "Set topic, instructor, or board type first (optional)"}
      </button>

      {showDetails && (
      <Card>
        <CardHeader>
          <CardTitle>Session Options</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleStart} className="space-y-5">
            {/* Topic + instructor — both optional but strongly recommended:
                this is the identifying info used for voice search/navigation
                and shown on the session dashboard, especially valuable since
                a shared device has no per-teacher login to fall back on. */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-slate-700">
                Topic <span className="ml-1 text-xs text-slate-400 font-normal">(optional)</span>
              </label>
              <input
                type="text"
                value={topic}
                onChange={e => setTopic(e.target.value)}
                placeholder="e.g. Newton's Laws of Motion"
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium text-slate-700">
                Instructor Name <span className="ml-1 text-xs text-slate-400 font-normal">(optional)</span>
              </label>
              <input
                type="text"
                value={instructorName}
                onChange={e => setInstructorName(e.target.value)}
                placeholder="e.g. Priya Sharma"
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>

            {/* Board type — might differ from classroom default (e.g. visiting a different room) */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-slate-700">Board Type</label>
              <div className="grid grid-cols-3 gap-2">
                {BOARDS.map(b => (
                  <button
                    key={b.value}
                    type="button"
                    onClick={() => setBoardType(b.value)}
                    className={`rounded-lg border p-3 text-center text-xs font-medium transition-all ${
                      boardType === b.value
                        ? "border-indigo-500 bg-indigo-50 text-indigo-700"
                        : "border-slate-200 text-slate-600 hover:border-slate-300"
                    }`}
                  >
                    <div className="text-lg mb-1">{b.emoji}</div>
                    {b.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Capture mode */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-slate-700">Capture Mode</label>
              <div className="grid grid-cols-2 gap-2">
                {[
                  { value: "time_based", label: "Auto (every N sec)" },
                  { value: "manual",     label: "Manual (tap to capture)" },
                ].map(m => (
                  <button
                    key={m.value}
                    type="button"
                    onClick={() => setCaptureMode(m.value)}
                    className={`rounded-lg border p-3 text-center text-xs font-medium transition-all ${
                      captureMode === m.value
                        ? "border-indigo-500 bg-indigo-50 text-indigo-700"
                        : "border-slate-200 text-slate-600 hover:border-slate-300"
                    }`}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
            </div>

            {captureMode === "time_based" && (
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-slate-700">
                  Capture Interval
                  <span className="ml-2 text-indigo-600 font-semibold">{intervalSec}s</span>
                </label>
                <input
                  type="range"
                  min={10} max={300} step={10}
                  value={intervalSec}
                  onChange={e => setIntervalSec(e.target.value)}
                  className="w-full accent-indigo-600"
                />
                <div className="flex justify-between text-xs text-slate-400">
                  <span>10s (fast)</span>
                  <span>5 min (slow)</span>
                </div>
              </div>
            )}

            {error && (
              <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>
            )}

            <div className="flex gap-3 pt-2">
              <Button type="button" variant="secondary" onClick={() => router.back()} className="flex-1">
                Cancel
              </Button>
              <Button type="submit" loading={loading} className="flex-1">
                Start Session →
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
      )}
    </div>
  );
}
