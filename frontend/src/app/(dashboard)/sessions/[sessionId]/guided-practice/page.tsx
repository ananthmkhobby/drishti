"use client";

import { use, useState } from "react";
import useSWR from "swr";
import { History, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { LoadingScreen } from "@/components/ui/Spinner";
import { useTranslation } from "@/hooks/useTranslation";
import { useEventPoller } from "@/hooks/useEventPoller";
import { useDesignVersion } from "@/hooks/useDesignVersion";
import { GuidedPracticeClassicView } from "@/components/practice/GuidedPracticeClassicView";
import { GuidedPracticePremiumView } from "@/components/practice/GuidedPracticePremiumView";

export default function GuidedPracticePage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  const { t } = useTranslation();
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState("");
  const [showManualCapture, setShowManualCapture] = useState(false);
  const { version, toggle: toggleDesign } = useDesignVersion("guided-practice");

  const { data, isLoading, mutate } = useSWR(
    ["practice-questions", sessionId],
    () => api.getPracticeQuestions(sessionId),
  );

  const { data: stationsData, mutate: mutateStations } = useSWR(
    ["practice-stations", sessionId],
    () => api.getStations(sessionId),
    { refreshInterval: 5000 },
  );

  useEventPoller({
    sessionId,
    onPracticeAttemptDone: () => { mutate(); mutateStations(); },
  });

  async function handleGenerate() {
    setGenerating(true);
    setGenError("");
    try {
      await api.generatePracticeQuestions(sessionId, 3);
      mutate();
    } catch (err) {
      setGenError(err instanceof Error ? err.message : "Couldn't generate questions — capture and process a board photo first.");
    } finally {
      setGenerating(false);
    }
  }

  async function decide(questionId: string, status: "approved" | "rejected") {
    await api.updatePracticeQuestion(questionId, { status });
    mutate();
  }

  if (isLoading) return <LoadingScreen label="Loading guided practice…" />;

  const questions = data?.questions ?? [];
  const pending = questions.filter((q) => q.status === "pending_review");
  const approved = questions.filter((q) => q.status === "approved");
  const stations = stationsData?.stations ?? [];

  const viewProps = {
    sessionId, t, generating, genError, handleGenerate, questions, pending, approved,
    decide, mutate, stations, mutateStations, showManualCapture, setShowManualCapture,
    designToggle: (
      <button
        onClick={toggleDesign}
        className="flex items-center gap-1.5 text-xs font-medium text-indigo-600 hover:text-indigo-800"
      >
        {version === "premium"
          ? <><History className="h-3.5 w-3.5" /> Classic view</>
          : <><Sparkles className="h-3.5 w-3.5" /> Try the new design</>}
      </button>
    ),
  };

  return version === "premium"
    ? <GuidedPracticePremiumView {...viewProps} />
    : <GuidedPracticeClassicView {...viewProps} />;
}
