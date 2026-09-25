"use client";

import { use, useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import {
  Zap,
  CheckCircle2,
  AlertCircle,
  Eye,
  EyeOff,
  Download,
  Copy,
  Check,
} from "lucide-react";
import { api, TiQerExportPayload, QuizQuestion } from "@/lib/api";
import { cn, BLOOM_COLOURS } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LoadingScreen } from "@/components/ui/Spinner";
import { Empty } from "@/components/ui/Empty";

// ── Constants ─────────────────────────────────────────────────────────────────

const BLOOM_ORDER = ["remember", "understand", "apply", "analyze", "evaluate", "create"] as const;

const DIFFICULTY_COLOURS = {
  easy:   "bg-green-100 text-green-700",
  medium: "bg-yellow-100 text-yellow-700",
  hard:   "bg-red-100 text-red-700",
};

const LETTER_COLOURS = ["bg-indigo-100 text-indigo-700", "bg-sky-100 text-sky-700", "bg-violet-100 text-violet-700", "bg-teal-100 text-teal-700"];

// ── Sub-components ────────────────────────────────────────────────────────────

function QuestionRow({ q, index }: { q: QuizQuestion; index: number }) {
  const letters = ["A", "B", "C", "D"];

  return (
    <li className="px-5 py-4 border-b border-slate-100 last:border-0">
      <div className="flex items-start gap-3">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-bold text-slate-600 mt-0.5">
          {index + 1}
        </span>
        <div className="min-w-0 flex-1 space-y-2">
          <p className="text-sm text-slate-800 leading-snug font-medium">{q.text}</p>

          {/* MCQ options */}
          {q.type === "mcq" && Array.isArray(q.options) && q.options.length > 0 && (
            <ul className="space-y-1">
              {q.options.map((opt, oi) => {
                const isCorrect = q.correct === oi;
                return (
                  <li
                    key={oi}
                    className={cn(
                      "flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs",
                      isCorrect
                        ? "bg-green-50 border border-green-200 text-green-800"
                        : "bg-slate-50 border border-transparent text-slate-600"
                    )}
                  >
                    <span className={cn(
                      "flex h-4 w-4 shrink-0 items-center justify-center rounded text-[0.625rem] font-bold",
                      isCorrect ? "bg-green-500 text-white" : LETTER_COLOURS[oi % 4]
                    )}>
                      {letters[oi]}
                    </span>
                    <span>{opt}</span>
                    {isCorrect && (
                      <CheckCircle2 className="ml-auto h-3.5 w-3.5 text-green-500 shrink-0" />
                    )}
                  </li>
                );
              })}
            </ul>
          )}

          {/* T/F display */}
          {q.type === "true_false" && (
            <div className="flex gap-2">
              {[true, false].map((val) => {
                const label = val ? "True" : "False";
                const isCorrect = q.correct === val;
                return (
                  <span
                    key={label}
                    className={cn(
                      "rounded-md px-3 py-1 text-xs font-medium border",
                      isCorrect
                        ? "bg-green-50 border-green-200 text-green-700"
                        : "bg-slate-50 border-slate-200 text-slate-500"
                    )}
                  >
                    {isCorrect && <CheckCircle2 className="inline h-3 w-3 mr-1 mb-0.5" />}
                    {label}
                  </span>
                );
              })}
            </div>
          )}

          {/* Meta badges */}
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge className="text-[0.625rem] bg-slate-100 text-slate-500">
              {q.type === "mcq" ? "MCQ" : "T/F"}
            </Badge>
            {q.bloom_level && (
              <Badge className={cn("text-[0.625rem]", BLOOM_COLOURS[q.bloom_level])}>
                {q.bloom_level}
              </Badge>
            )}
            {q.topic && (
              <span className="text-[0.625rem] text-slate-400 truncate max-w-[7.5rem]" title={q.topic}>
                {q.topic}
              </span>
            )}
            {q.skill_tag && (
              <span className="font-mono text-[0.625rem] text-indigo-400 truncate max-w-[7.5rem]" title={q.skill_tag}>
                #{q.skill_tag}
              </span>
            )}
          </div>
        </div>
      </div>
    </li>
  );
}

function BloomBar({
  questions,
  exportedDist,
}: {
  questions: QuizQuestion[];
  exportedDist?: Record<string, number> | null;
}) {
  const dist = exportedDist ?? (() => {
    const d: Record<string, number> = {};
    for (const level of BLOOM_ORDER) d[level] = 0;
    for (const q of questions) if (q.bloom_level) d[q.bloom_level] = (d[q.bloom_level] ?? 0) + 1;
    return d;
  })();
  const total = Object.values(dist).reduce((a, b) => a + b, 0) || 1;

  return (
    <div className="space-y-2">
      {BLOOM_ORDER.map((level) => {
        const count = dist[level] ?? 0;
        const pct = Math.round((count / total) * 100);
        return (
          <div key={level} className="flex items-center gap-2">
            <span className="w-20 text-xs text-slate-500 capitalize">{level}</span>
            <div className="flex-1 h-2 rounded-full bg-slate-100 overflow-hidden">
              <div
                className={cn("h-full rounded-full transition-all", BLOOM_COLOURS[level]?.split(" ")[0]?.replace("text-", "bg-") ?? "bg-slate-300")}
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="w-6 text-right text-xs text-slate-500">{count}</span>
          </div>
        );
      })}
    </div>
  );
}

function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  async function handleCopy() {
    await navigator.clipboard.writeText(text).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }
  return (
    <button
      onClick={handleCopy}
      className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 transition-colors"
    >
      {copied ? <Check className="h-3 w-3 text-green-500" /> : <Copy className="h-3 w-3" />}
      {copied ? "Copied!" : label}
    </button>
  );
}

// ── Sample JSON ───────────────────────────────────────────────────────────────

const SAMPLE_JSON = JSON.stringify(
  {
    export_id: "a1b2c3d4-...",
    schema_version: "1.0",
    tiqer_class_id: "CLS-2026-G9-PHY",
    session_id: "uuid",
    exported_at: "2026-05-01T10:30:00Z",
    teacher_id: "uuid",
    subject: "Physics",
    grade: "Grade 9",
    question_count: 2,
    questions: [
      {
        question_id: "uuid",
        sequence: 1,
        type: "mcq",
        text: "What is Newton's Second Law?",
        options: [
          { key: "A", text: "F = ma" },
          { key: "B", text: "F = mv" },
          { key: "C", text: "F = mg" },
          { key: "D", text: "F = ma²" },
        ],
        correct_answer: "A",
        bloom_level: "understand",
        skill_tag: "newtons-second-law",
        topic: "Newton's Laws",
        grade: "Grade 9",
        subject: "Physics",
        difficulty: "easy",
      },
      {
        question_id: "uuid",
        sequence: 2,
        type: "true_false",
        text: "Acceleration is proportional to force.",
        options: null,
        correct_answer: "true",
        bloom_level: "remember",
        skill_tag: "forces",
        topic: "Forces",
        grade: "Grade 9",
        subject: "Physics",
        difficulty: "easy",
      },
    ],
    metadata: {
      generated_by: "Drishti",
      aci_version: "1.0.0",
      bloom_distribution: { remember: 1, understand: 1, apply: 0, analyze: 0, evaluate: 0, create: 0 },
      mcq_count: 1,
      true_false_count: 1,
    },
  },
  null,
  2
);

// ── Main page ─────────────────────────────────────────────────────────────────

export default function TiQerPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  const [classId, setClassId] = useState("");
  const [exporting, setExporting] = useState(false);
  const [result, setResult] = useState<{
    ok: boolean;
    message: string;
    payload?: TiQerExportPayload | null;
  } | null>(null);
  const [showSampleJson, setShowSampleJson] = useState(false);
  const [showResultJson, setShowResultJson] = useState(false);

  const { data: quizData, isLoading } = useSWR(
    ["quiz", sessionId],
    () => api.getQuiz(sessionId),
    { shouldRetryOnError: false }
  );

  const questions = quizData?.questions ?? [];
  const mcqCount = questions.filter((q) => q.type === "mcq").length;
  const tfCount  = questions.filter((q) => q.type === "true_false").length;

  async function handleExport(e: React.FormEvent) {
    e.preventDefault();
    if (!classId.trim()) return;
    setExporting(true);
    setResult(null);
    try {
      const res = await api.exportToTiQer(sessionId, classId.trim());
      setResult({
        ok: true,
        message: `Exported ${res.question_count} questions · TiQer ID: ${res.tiqer_session_id}`,
        payload: res.payload,
      });
    } catch (err: unknown) {
      setResult({
        ok: false,
        message: err instanceof Error ? err.message : "Export failed.",
      });
    } finally {
      setExporting(false);
    }
  }

  function handleDownload() {
    api.downloadTiQerJson(sessionId, classId.trim() || "PREVIEW");
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-600">
            <Zap className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-900">TiQer Export</h1>
            <p className="text-sm text-slate-500 mt-0.5">
              Send quiz questions to TiQer for live classroom engagement
            </p>
          </div>
        </div>
        {questions.length > 0 && (
          <Button variant="secondary" size="sm" onClick={handleDownload}>
            <Download className="h-4 w-4" />
            Download JSON
          </Button>
        )}
      </div>

      {isLoading && <LoadingScreen label="Loading questions…" />}

      {!isLoading && questions.length === 0 && (
        <Empty
          icon={<Zap className="h-12 w-12" />}
          title="No questions available"
          description="Generate a quiz first from the Notes page."
          action={
            <Link href={`/sessions/${sessionId}/notes`}>
              <Button size="sm" variant="secondary">Generate Quiz →</Button>
            </Link>
          }
        />
      )}

      {questions.length > 0 && (
        <div className="grid gap-6 lg:grid-cols-2">
          {/* ── Left column: export form + bloom distribution ── */}
          <div className="space-y-5">
            {/* Export form */}
            <Card>
              <CardHeader>
                <CardTitle>Export to TiQer</CardTitle>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleExport} className="space-y-4">
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-slate-700">
                      TiQer Class ID <span className="text-red-500">*</span>
                    </label>
                    <input
                      type="text"
                      value={classId}
                      onChange={(e) => setClassId(e.target.value)}
                      placeholder="e.g. CLS-2026-G9-PHY"
                      className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    />
                    <p className="mt-1.5 text-xs text-slate-400">
                      Find your class ID in the TiQer dashboard → Classes.
                    </p>
                  </div>

                  {/* What gets exported */}
                  <div className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600 space-y-1">
                    <p className="font-medium text-slate-700 mb-2">What gets exported:</p>
                    {[
                      mcqCount > 0       && `${mcqCount} MCQ question${mcqCount > 1 ? "s" : ""}`,
                      tfCount  > 0       && `${tfCount} True/False question${tfCount > 1 ? "s" : ""}`,
                      "Bloom levels and skill tags",
                      "Topic and difficulty mapping",
                      "TiQer schema v1.0 (grade + subject on each question)",
                    ]
                      .filter(Boolean)
                      .map((item) => (
                        <div key={item as string} className="flex items-center gap-1.5 text-xs text-slate-500">
                          <CheckCircle2 className="h-3 w-3 text-green-500 shrink-0" />
                          {item as string}
                        </div>
                      ))}
                  </div>

                  {/* Result banner */}
                  {result && (
                    <div className={cn(
                      "rounded-lg px-3 py-2.5 text-sm space-y-2",
                      result.ok ? "bg-green-50 border border-green-200" : "bg-red-50 border border-red-200"
                    )}>
                      <div className={cn(
                        "flex items-start gap-2",
                        result.ok ? "text-green-700" : "text-red-600"
                      )}>
                        {result.ok
                          ? <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5" />
                          : <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />}
                        <span>{result.message}</span>
                      </div>

                      {result.ok && result.payload && (
                        <div className="space-y-1">
                          <div className="flex items-center justify-between">
                            <button
                              type="button"
                              onClick={() => setShowResultJson((v) => !v)}
                              className="flex items-center gap-1 text-xs text-green-600 hover:text-green-800"
                            >
                              {showResultJson ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                              {showResultJson ? "Hide payload" : "Show payload"}
                            </button>
                            <CopyButton
                              text={JSON.stringify(result.payload, null, 2)}
                              label="Copy JSON"
                            />
                          </div>
                          {showResultJson && (
                            <pre className="rounded bg-white border border-green-200 p-2 text-[0.625rem] text-slate-600 overflow-auto max-h-48 whitespace-pre-wrap break-all">
                              {JSON.stringify(result.payload, null, 2).slice(0, 800)}
                              {JSON.stringify(result.payload, null, 2).length > 800 && "\n… (truncated)"}
                            </pre>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  <div className="flex gap-2">
                    <Button
                      type="submit"
                      loading={exporting}
                      className="flex-1"
                      disabled={!classId.trim()}
                    >
                      <Zap className="h-4 w-4" />
                      {exporting ? "Exporting…" : "Export to TiQer"}
                    </Button>
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={handleDownload}
                      title="Download TiQer JSON"
                    >
                      <Download className="h-4 w-4" />
                    </Button>
                  </div>
                </form>
              </CardContent>
            </Card>

            {/* Bloom distribution */}
            <Card>
              <CardHeader>
                <CardTitle>Bloom Distribution</CardTitle>
                <span className="text-sm text-slate-400">{questions.length} questions</span>
              </CardHeader>
              <CardContent>
                <BloomBar
                  questions={questions}
                  exportedDist={result?.ok ? result.payload?.metadata?.bloom_distribution : null}
                />
              </CardContent>
            </Card>

            {/* Sample JSON format */}
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between w-full">
                  <CardTitle>Sample JSON Format</CardTitle>
                  <div className="flex items-center gap-1">
                    <CopyButton text={SAMPLE_JSON} label="Copy sample" />
                    <button
                      onClick={() => setShowSampleJson((v) => !v)}
                      className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 transition-colors"
                    >
                      {showSampleJson ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                      {showSampleJson ? "Hide" : "Show"}
                    </button>
                  </div>
                </div>
              </CardHeader>
              {showSampleJson && (
                <CardContent>
                  <pre className="rounded-lg bg-slate-950 p-4 text-[0.6875rem] text-slate-200 overflow-auto max-h-72 leading-relaxed">
                    {SAMPLE_JSON}
                  </pre>
                  <p className="mt-2 text-xs text-slate-400">
                    Schema version 1.0 · MCQ <code className="bg-slate-100 rounded px-1">correct_answer</code> = letter A–D ·
                    T/F = <code className="bg-slate-100 rounded px-1">"true"</code>/<code className="bg-slate-100 rounded px-1">"false"</code>
                  </p>
                </CardContent>
              )}
            </Card>
          </div>

          {/* ── Right column: question preview ── */}
          <div>
            <Card className="h-fit">
              <CardHeader>
                <CardTitle>Question Preview</CardTitle>
                <div className="flex items-center gap-2">
                  {mcqCount > 0 && (
                    <Badge className="text-[0.625rem] bg-indigo-100 text-indigo-700">
                      {mcqCount} MCQ
                    </Badge>
                  )}
                  {tfCount > 0 && (
                    <Badge className="text-[0.625rem] bg-sky-100 text-sky-700">
                      {tfCount} T/F
                    </Badge>
                  )}
                </div>
              </CardHeader>
              <CardContent className="p-0 max-h-[40rem] overflow-y-auto">
                <ul>
                  {questions.map((q, i) => (
                    <QuestionRow key={q.id} q={q} index={i} />
                  ))}
                </ul>
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
