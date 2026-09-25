/**
 * Classroom settings — persisted in localStorage so a teacher only has to
 * configure their grade / class name once per device.
 *
 * These values pre-fill the "New Session" form and supply the grade context
 * to AI generation when the teacher does not specify it per-session.
 */

export interface ClassroomSettings {
  /** e.g. "Grade 5", "Grade 8" */
  grade: string;
  /** Optional display label, e.g. "Section A", "Room 3" */
  className: string;
  /** "chalkboard" | "whiteboard" | "smartboard" */
  boardType: string;
}

const STORAGE_KEY = "aci_classroom_settings";

export function getClassroomSettings(): ClassroomSettings | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as ClassroomSettings;
  } catch {
    return null;
  }
}

export function saveClassroomSettings(s: ClassroomSettings): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
}

export function clearClassroomSettings(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(STORAGE_KEY);
}

export function classroomLabel(s: ClassroomSettings): string {
  const parts = [s.grade, s.className].filter(Boolean);
  return parts.join(" · ") || "My Classroom";
}
