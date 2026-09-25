// Shared prop contract for the Session History page's two view components
// (classic/premium — render only). The page component owns all state,
// data-fetching and handlers; both views receive the exact same values.
import type { KeyedMutator } from "swr";
import type { Session } from "@/lib/api";
import type { PendingSession } from "@/lib/offline-store";
import type { ClassroomSettings } from "@/lib/classroom-settings";
import type { SessionFilter, SessionCounts, DateGroup } from "@/components/home/homeShared";

export type SessionsResponse = { sessions: Session[]; total: number; _fromCache?: boolean };

export interface HomeViewProps {
  filter: SessionFilter;
  setFilter: (f: SessionFilter) => void;
  classroom: ClassroomSettings | null;
  offlineSessions: PendingSession[];
  setOfflineSessions: React.Dispatch<React.SetStateAction<PendingSession[]>>;
  fromCache: boolean;
  sessions: Session[];
  filtered: Session[];
  counts: SessionCounts;
  groups: DateGroup[];
  mutate: KeyedMutator<SessionsResponse>;
  designToggle: React.ReactNode;
  // Set only when arriving from Welcome's attendance flow — see
  // (dashboard)/sessions/page.tsx. matchSection is display-only (sessions
  // aren't stored per-section); matching itself is grade-only.
  matchGrade: string | null;
  matchSection: string | null;
  matchingSessions: Session[];
}
