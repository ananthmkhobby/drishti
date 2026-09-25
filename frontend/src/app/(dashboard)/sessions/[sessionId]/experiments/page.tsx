"use client";

import { use } from "react";
import useSWR from "swr";
import Link from "next/link";
import { FlaskConical, CheckCircle, Package } from "lucide-react";
import { api } from "@/lib/api";
import { fetchOutputsCached } from "@/lib/cached-fetchers";
import { cn } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { LoadingScreen } from "@/components/ui/Spinner";
import { Empty } from "@/components/ui/Empty";
import { Button } from "@/components/ui/Button";

const DIFFICULTY_COLOUR: Record<string, string> = {
  easy:   "bg-green-100 text-green-700",
  medium: "bg-yellow-100 text-yellow-700",
  hard:   "bg-red-100 text-red-700",
};

interface Experiment {
  title: string;
  topic?: string;
  difficulty?: string;
  description: string;
  materials?: string[];
  steps?: string[];
  expected_outcome?: string;
  safety_note?: string;
  xperimentor_kit?: string | null;
}

export default function ExperimentsPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);

  const { data: outputs, isLoading } = useSWR(
    ["outputs", sessionId],
    () => fetchOutputsCached(sessionId)
  );

  const expOutput = outputs?.outputs?.experiments;
  const expData   = expOutput?.data;

  // Handle both wrapped ({experiments:[...]}) and raw ([...]) formats
  const experiments: Experiment[] = Array.isArray(expData)
    ? expData
    : Array.isArray(expData?.experiments)
    ? (expData.experiments as Experiment[])
    : [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-slate-900">Hands-On Experiments</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          AI-suggested classroom activities based on today's lesson
        </p>
      </div>

      {isLoading && <LoadingScreen label="Loading experiments…" />}

      {!isLoading && experiments.length === 0 && (
        <Empty
          icon={<FlaskConical className="h-12 w-12" />}
          title="No experiment suggestions yet"
          description="Generate AI outputs from the Notes page to get experiment ideas."
          action={
            <Link href={`/sessions/${sessionId}/notes`}>
              <Button size="sm" variant="secondary">Generate AI Outputs →</Button>
            </Link>
          }
        />
      )}

      {experiments.length > 0 && (
        <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {experiments.map((exp, i) => (
            <Card key={i} className="flex flex-col">
              <CardHeader>
                <div className="space-y-1">
                  <div className="flex items-start justify-between gap-2">
                    <CardTitle className="text-base">{exp.title}</CardTitle>
                    {exp.difficulty && (
                      <Badge className={cn("shrink-0 text-[0.625rem]", DIFFICULTY_COLOUR[exp.difficulty] ?? "bg-slate-100 text-slate-500")}>
                        {exp.difficulty}
                      </Badge>
                    )}
                  </div>
                  {exp.topic && (
                    <p className="text-xs text-slate-500">{exp.topic}</p>
                  )}
                </div>
              </CardHeader>

              <CardContent className="flex-1 space-y-4">
                {/* Description */}
                <p className="text-sm text-slate-700">{exp.description}</p>

                {/* Materials */}
                {exp.materials && exp.materials.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1.5">Materials</p>
                    <div className="flex flex-wrap gap-1.5">
                      {exp.materials.map((m, j) => (
                        <span key={j} className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-600">
                          {m}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Steps */}
                {exp.steps && exp.steps.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1.5">Steps</p>
                    <ol className="space-y-1">
                      {exp.steps.map((step, j) => (
                        <li key={j} className="flex items-start gap-2 text-xs text-slate-600">
                          <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-[0.625rem] font-bold text-indigo-600 mt-0.5">
                            {j + 1}
                          </span>
                          {step}
                        </li>
                      ))}
                    </ol>
                  </div>
                )}

                {/* Expected outcome */}
                {exp.expected_outcome && (
                  <div className="flex items-start gap-2 rounded-lg bg-green-50 p-3 text-xs text-green-700">
                    <CheckCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                    <span><strong>Outcome: </strong>{exp.expected_outcome}</span>
                  </div>
                )}

                {/* Safety */}
                {exp.safety_note && (
                  <div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-700">
                    <strong>⚠ Safety: </strong>{exp.safety_note}
                  </div>
                )}

                {/* Xperimentor kit */}
                {exp.xperimentor_kit && (
                  <div className="flex items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2">
                    <Package className="h-4 w-4 text-indigo-600 shrink-0" />
                    <span className="text-xs font-medium text-indigo-700">
                      Xperimentor Kit: {exp.xperimentor_kit}
                    </span>
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
