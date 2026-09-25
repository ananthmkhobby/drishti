// Shared between the Guided Practice page's two view components
// (classic/premium — render only) so neither view needs to import from
// the other, and the state/priority semantics (which colors and which
// order mean what) are never duplicated or allowed to drift between them.
import type { ValidationStatus, StudentState } from "@/lib/api";

export const STATE_STYLES: Record<StudentState, { label: string; dot: string; text: string; bg: string }> = {
  solved:           { label: "Solved 🎉",       dot: "bg-emerald-600", text: "text-emerald-800", bg: "bg-emerald-100 border-emerald-300" },
  progressing:      { label: "Progressing",     dot: "bg-emerald-500", text: "text-emerald-700", bg: "bg-emerald-50 border-emerald-200" },
  uncertain:        { label: "Uncertain",       dot: "bg-amber-400",   text: "text-amber-700",   bg: "bg-amber-50 border-amber-200" },
  stuck:            { label: "Stuck",           dot: "bg-amber-500",   text: "text-amber-800",   bg: "bg-amber-50 border-amber-300" },
  misconception:    { label: "Misconception",   dot: "bg-orange-500",  text: "text-orange-800",  bg: "bg-orange-50 border-orange-300" },
  ambiguous:        { label: "Needs clearer photo", dot: "bg-slate-400", text: "text-slate-600", bg: "bg-slate-50 border-slate-200" },
  teacher_required:  { label: "Needs you",      dot: "bg-red-500",     text: "text-red-700",     bg: "bg-red-50 border-red-300" },
};

// Same semantics as STATE_STYLES above, re-skinned for the premium warm
// palette (deep-tone text on a soft tint) instead of the classic view's
// flatter Tailwind slate/amber/emerald tones.
export const PREMIUM_STATE_STYLES: Record<StudentState, { label: string; fg: string; bg: string; dot: string }> = {
  solved:           { label: "Solved",         fg: "#1E6B47", bg: "#E1F3E9", dot: "#1E9C5F" },
  progressing:      { label: "Progressing",    fg: "#1E6B47", bg: "#E7F1EA", dot: "#3E7A57" },
  uncertain:        { label: "Uncertain",      fg: "#8A5D1E", bg: "#F6EAD3", dot: "#C89540" },
  stuck:            { label: "Stuck",          fg: "#8A5D1E", bg: "#F6EAD3", dot: "#B97F2C" },
  misconception:    { label: "Misconception",  fg: "#B4432D", bg: "#FBEAE6", dot: "#D9603F" },
  ambiguous:        { label: "Needs clearer photo", fg: "#57534E", bg: "#F1EFEA", dot: "#9A968A" },
  teacher_required:  { label: "Needs you",     fg: "#B4432D", bg: "#FBEAE6", dot: "#DC2626" },
};

export const VALIDATION_LABELS: Record<ValidationStatus, string> = {
  solved: "Solved — final answer reached",
  valid_progress: "On the right track",
  alternative_valid_method: "Valid alternate approach",
  incomplete: "Incomplete so far",
  arithmetic_slip: "Arithmetic slip",
  conceptual_misconception: "Conceptual misconception",
  ambiguous: "Ambiguous — couldn't classify",
  unsupported: "Approach not recognized",
};

// "ambiguous" covers several distinct reasons a teacher needs to tell apart
// at a glance — a blurry photo vs. a perfectly legible photo of the wrong
// page are very different problems to act on.
export const AMBIGUOUS_REASON_LABELS: Record<string, string> = {
  off_topic_content: "Legible, but not this question — wrong page?",
  blank_page: "Page appears blank",
  capture_illegible: "Photo too blurry/dark to read",
  recognition_unavailable: "Couldn't process this photo",
};

export const DOMAIN_LABELS: Record<string, string> = {
  numeric: "Numeric", algebraic: "Algebraic", conceptual: "Conceptual", diagram: "Diagram", other: "Other",
};

export const STATE_PRIORITY: Record<StudentState, number> = {
  teacher_required: 0,
  misconception: 1,
  stuck: 2,
  uncertain: 3,
  ambiguous: 4,
  progressing: 5,
  solved: 6, // least urgent of all — they're done
};

export const COMMON_SUBJECTS = [
  "Mathematics", "Physics", "Chemistry", "Biology", "English",
  "History", "Geography", "Computer Science", "Economics",
];

export function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}
