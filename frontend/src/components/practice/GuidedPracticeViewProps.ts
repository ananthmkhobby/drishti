// Shared prop contract for the Guided Practice page's two view components
// (classic/premium — render only). The page component owns all
// data-fetching, state, and handlers; both views receive the exact same
// values, same as the Teaching and Session-History page redesigns.
import type { PracticeQuestion, PracticeStation } from "@/lib/api";

export interface GuidedPracticeViewProps {
  sessionId: string;
  t: (s: string) => string;
  generating: boolean;
  genError: string;
  handleGenerate: () => void;
  questions: PracticeQuestion[];
  pending: PracticeQuestion[];
  approved: PracticeQuestion[];
  decide: (questionId: string, status: "approved" | "rejected") => Promise<void>;
  mutate: () => void;
  stations: PracticeStation[];
  mutateStations: () => void;
  showManualCapture: boolean;
  setShowManualCapture: (updater: (v: boolean) => boolean) => void;
  designToggle: React.ReactNode;
}
