"use client";

import { use, useRef, useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import {
  BookOpen, Upload, Loader2, AlertTriangle, PlayCircle, RotateCcw, CheckCircle2, Compass, Trash2,
} from "lucide-react";
import { api, type Textbook, type TextbookContentType } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { LoadingScreen } from "@/components/ui/Spinner";

function ContentTypeToggle({ value, onChange }: { value: TextbookContentType; onChange: (v: TextbookContentType) => void }) {
  const options: { value: TextbookContentType; label: string; hint: string }[] = [
    { value: "textbook", label: "Textbook", hint: "A formal book with multiple chapters" },
    { value: "concept_notes", label: "Concept Notes / Activity Sheet", hint: "A short single-topic worksheet — taught guess → investigate → observe → infer" },
  ];
  return (
    <div className="flex flex-col sm:flex-row gap-2 rounded-xl border border-slate-200 bg-slate-50 p-1.5">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={`flex-1 rounded-lg px-3 py-2 text-left transition-colors ${
            value === opt.value ? "bg-white shadow-sm border border-indigo-200" : "hover:bg-white/60"
          }`}
        >
          <p className={`text-sm font-semibold ${value === opt.value ? "text-indigo-700" : "text-slate-600"}`}>{opt.label}</p>
          <p className="text-[0.6875rem] text-slate-400 mt-0.5">{opt.hint}</p>
        </button>
      ))}
    </div>
  );
}

function UploadZone({ onFile, loading, contentType }: { onFile: (f: File) => void; loading: boolean; contentType: TextbookContentType }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDrag(false);
    const f = e.dataTransfer.files?.[0];
    if (f) onFile(f);
  }

  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={handleDrop}
      className={`
        flex flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed
        cursor-pointer transition-colors p-12 text-center
        ${drag ? "border-indigo-400 bg-indigo-50" : "border-slate-300 bg-slate-50 hover:bg-slate-100"}
      `}
    >
      {loading ? (
        <Loader2 className="h-12 w-12 text-indigo-500 animate-spin" />
      ) : (
        <Upload className="h-12 w-12 text-slate-400" />
      )}
      <div>
        <p className="font-semibold text-slate-700">
          {loading ? "Uploading and reading pages…" : contentType === "concept_notes" ? "Upload Concept Notes / Activity Sheet" : "Upload Textbook"}
        </p>
        <p className="text-xs text-slate-500 mt-1">PDF only · max 60 MB</p>
      </div>
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        accept=".pdf,application/pdf"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
    </div>
  );
}

function TextbookCard({
  sessionId, textbook, onRefresh, onDelete,
}: {
  sessionId: string; textbook: Textbook; onRefresh: () => void; onDelete: (textbookId: string) => void;
}) {
  const isProcessing = textbook.status === "pending" || textbook.status === "processing";
  const [deleting, setDeleting] = useState(false);

  useSWR(
    isProcessing ? ["textbook-poll", textbook.textbook_id] : null,
    () => api.getTextbook(textbook.textbook_id),
    { refreshInterval: 3000, onSuccess: (updated) => { if (updated.status !== "processing" && updated.status !== "pending") onRefresh(); } }
  );

  async function handleDelete() {
    if (!confirm(`Delete "${textbook.title || "this textbook"}"? This removes it and all its teaching progress permanently.`)) return;
    setDeleting(true);
    try {
      await api.deleteTextbook(textbook.textbook_id);
      onDelete(textbook.textbook_id);
    } catch {
      setDeleting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <BookOpen className="h-4 w-4 text-indigo-600" />
          <CardTitle>{textbook.title || "Untitled textbook"}</CardTitle>
          {textbook.language_name && textbook.language_name !== "English" && (
            <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[0.6875rem] font-medium text-indigo-600">
              {textbook.language_name}
            </span>
          )}
          {textbook.page_count != null && (
            <span className="ml-auto text-xs text-slate-400">{textbook.page_count} pages</span>
          )}
          <button
            onClick={handleDelete}
            disabled={deleting}
            title="Delete textbook"
            className="text-slate-300 hover:text-red-500 disabled:opacity-50 transition-colors"
          >
            {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
          </button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {isProcessing && (
          <div className="flex items-center gap-2 text-sm text-slate-600">
            <Loader2 className="h-4 w-4 animate-spin text-indigo-500" />
            Finding chapters in this textbook…
          </div>
        )}
        {textbook.status === "failed" && (
          <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
            <span>{textbook.error_message || "Chapter detection failed."}</span>
          </div>
        )}
        {textbook.status === "ready" && (
          <ul className="divide-y divide-slate-100">
            {(textbook.chapters ?? []).map((ch) => (
              <li key={ch.chapter_id} className="flex items-center justify-between gap-3 py-2.5">
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <p className="text-sm font-medium text-slate-800 truncate">{ch.title}</p>
                    {ch.pedagogy === "quest" && (
                      <span className="flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[0.625rem] font-semibold text-amber-700 shrink-0">
                        <Compass className="h-3 w-3" /> Quest
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-400">
                    Pages {ch.start_page}–{ch.end_page}
                    {ch.started && ch.last_taught_at && (
                      <> · last taught {new Date(ch.last_taught_at).toLocaleDateString()}</>
                    )}
                  </p>
                </div>
                <Link href={`/sessions/${sessionId}/textbook/${textbook.textbook_id}/${ch.chapter_id}`}>
                  <Button size="sm" variant={ch.started ? "secondary" : "primary"}>
                    {ch.started ? (
                      <><RotateCcw className="h-3.5 w-3.5 mr-1.5" /> Continue</>
                    ) : (
                      <><PlayCircle className="h-3.5 w-3.5 mr-1.5" /> Start teaching</>
                    )}
                  </Button>
                </Link>
              </li>
            ))}
            {(textbook.chapters ?? []).length === 0 && (
              <p className="text-xs text-slate-400 italic py-2">No chapters detected.</p>
            )}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export default function TextbookPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [contentType, setContentType] = useState<TextbookContentType>("textbook");

  const { data, isLoading, mutate } = useSWR(
    ["textbooks", sessionId],
    () => api.listTextbooks(sessionId),
    { revalidateOnFocus: false }
  );

  async function handleUpload(file: File) {
    setError(null);
    setUploading(true);
    try {
      const created = await api.uploadTextbook(sessionId, file, undefined, contentType);
      // Dedupe by id — a retried upload of the same PDF can come back as
      // the existing textbook (server-side idempotency) rather than a new
      // one, so replace any existing entry instead of blindly prepending
      // a second card for it.
      await mutate((prev) => {
        const rest = (prev?.textbooks ?? []).filter((t) => t.textbook_id !== created.textbook_id);
        return { textbooks: [created, ...rest] };
      }, false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Upload failed");
      // The request can fail on the client (a dropped connection, a slow
      // classroom wifi network) while the upload actually completes
      // server-side a moment later — re-sync with the server so that case
      // shows up here on its own instead of requiring a manual refresh.
      mutate();
    } finally {
      setUploading(false);
    }
  }

  const textbooks = data?.textbooks ?? [];

  return (
    <div className="space-y-5">
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white">
          <BookOpen className="h-5 w-5" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-slate-900">Textbook</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Upload a textbook and the AI will teach it chapter by chapter — say "let's start the [chapter] chapter" once it's ready
          </p>
        </div>
      </div>

      {isLoading && <LoadingScreen label="Loading textbooks…" />}

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {!isLoading && (
        <div className="space-y-4">
          {textbooks.map((tb) => (
            <TextbookCard
              key={tb.textbook_id}
              sessionId={sessionId}
              textbook={tb}
              onRefresh={() => mutate()}
              onDelete={(id) => mutate((prev) => ({ textbooks: (prev?.textbooks ?? []).filter((t) => t.textbook_id !== id) }), false)}
            />
          ))}

          <ContentTypeToggle value={contentType} onChange={setContentType} />
          <UploadZone onFile={handleUpload} loading={uploading} contentType={contentType} />

          {textbooks.length > 0 && (
            <p className="flex items-center gap-1.5 text-xs text-slate-400">
              <CheckCircle2 className="h-3.5 w-3.5" /> Uploading another PDF adds it alongside your existing textbooks.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
