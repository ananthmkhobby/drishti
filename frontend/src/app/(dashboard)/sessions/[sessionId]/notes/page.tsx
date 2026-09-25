"use client";

import { use, useState, useEffect } from "react";
import useSWR from "swr";
import Link from "next/link";
import {
  FileText, Cpu, RefreshCw, Lightbulb, CheckCircle2,
  Loader2, BookOpen, AlertTriangle, Target, TrendingUp,
  ChevronRight, Award, Brain, Layers, ArrowRight, Download,
  GitBranch,
} from "lucide-react";
import { api, getDiagramImageUrl } from "@/lib/api";
import { fetchOutputsCached } from "@/lib/cached-fetchers";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { LoadingScreen } from "@/components/ui/Spinner";
import { LanguageSelector } from "@/components/ui/LanguageSelector";
import { useTranslation } from "@/hooks/useTranslation";
import { cn } from "@/lib/utils";

// ─── Types ─────────────────────────────────────────────────────────────────────

interface CoveredConcept {
  concept: string;
  depth: "strong" | "medium" | "weak";
  bloom_level: string;
}

interface PartiallyCoveredConcept {
  concept: string;
  what_missing: string;
}

interface CurriculumCoverage {
  syllabus_coverage_pct?: number;
  missing_learning_objectives?: string[];
}

interface BloomDistribution {
  remember?: number;
  understand?: number;
  apply?: number;
  analyze?: number;
  evaluate?: number;
  create?: number;
}

interface Diagram {
  type: "flowchart" | "cycle" | "concept_map" | "comparison";
  title: string;
  // flowchart
  steps?: string[];
  // cycle
  nodes?: string[];
  // concept_map
  center?: string;
  branches?: string[];
  // comparison
  left_label?: string;
  right_label?: string;
  left_items?: string[];
  right_items?: string[];
}

interface BoardDiagramError {
  issue: string;
  correct_version: string;
}

interface BoardDiagramValidation {
  diagram_type?: string;
  is_correct: boolean | null;
  errors?: BoardDiagramError[];
  unvalidated?: boolean;
  reason?: string;
}

interface BoardDiagram {
  frame_id: string;
  index: number;
  description: string;
  validation: BoardDiagramValidation;
}

interface NotesData {
  markdown?: string;
  mind_map?: string;
  session_summary?: string;
  topic_detected?: string;
  diagrams?: Diagram[];
  board_diagrams?: BoardDiagram[];
  covered_concepts?: CoveredConcept[];
  partially_covered_concepts?: PartiallyCoveredConcept[];
  missing_concepts?: string[];
  missing_prerequisites?: string[];
  curriculum_coverage?: CurriculumCoverage;
  bloom_distribution?: BloomDistribution;
  teaching_completeness_score?: number | null;
  recommended_next_topics?: string[];
  suggested_exercises?: string[];
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

// Inline-only substitutions (bold/italic/code) — safe to apply within any
// single line since they never introduce block-level tags.
function renderInline(line: string): string {
  return line
    .replace(/\*\*\*(.+?)\*\*\*/g, '<strong class="font-bold text-indigo-700 italic">$1</strong>')
    .replace(/\*\*(.+?)\*\*/g, '<strong class="font-semibold text-slate-900 bg-yellow-50 px-0.5 rounded">$1</strong>')
    .replace(/\*(.+?)\*/g, '<em class="italic text-slate-700">$1</em>')
    .replace(/`([^`]+)`/g, '<code class="rounded bg-indigo-50 px-1.5 py-0.5 text-[0.8125rem] font-mono text-purple-700">$1</code>');
}

/**
 * Converts markdown to HTML, line by line, emitting only valid block
 * structure (h1-h3, blockquote-style callouts, ul/ol, hr, p). Every loose
 * line of prose gets its own explicit <p class="text-slate-700 ..."> —
 * previously a single regex pass turned headings/lists into block tags but
 * left the surrounding text wrapped in one big caller-supplied <p>, which is
 * invalid nesting (a <p> can't contain a <h2>/<ul>/<div>). Browsers silently
 * close the <p> at the first such tag, so any prose after it lost its
 * text-slate-700 color and rendered in the page's default (much lighter)
 * inherited color — meaning it looked correct in isolation but faded to
 * near-invisible against a white/light background.
 */
function renderMarkdown(md: string): string {
  const lines = md.split("\n");
  const out: string[] = [];
  let list: { type: "ul" | "ol"; items: string[] } | null = null;

  const flushList = () => {
    if (!list) return;
    if (list.type === "ol") {
      const items = list.items
        .map((item, i) =>
          `<li class="flex gap-2.5 text-slate-700 leading-relaxed py-0.5"><span class="counter-item shrink-0 mt-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-indigo-100 text-[0.6875rem] font-bold text-indigo-700">${i + 1}</span><span>${item}</span></li>`)
        .join("");
      out.push(`<ol class="space-y-1.5 my-3 pl-1">${items}</ol>`);
    } else {
      const items = list.items
        .map((item) =>
          `<li class="flex gap-2 text-slate-700 leading-relaxed py-0.5"><span class="mt-2 shrink-0 h-1.5 w-1.5 rounded-full bg-indigo-400 inline-block"></span><span>${item}</span></li>`)
        .join("");
      out.push(`<ul class="space-y-1 my-2 pl-1">${items}</ul>`);
    }
    list = null;
  };

  for (const line of lines) {
    let m: RegExpMatchArray | null;

    if ((m = line.match(/^### (.+)$/))) {
      flushList();
      out.push(`<h3 class="text-sm font-bold text-slate-800 mt-5 mb-1.5 flex items-center gap-1.5"><span class="w-1 h-4 bg-indigo-300 rounded-full inline-block"></span>${renderInline(m[1])}</h3>`);
    } else if ((m = line.match(/^## (.+)$/))) {
      flushList();
      out.push(`<h2 class="text-base font-bold text-indigo-800 mt-7 mb-2 pb-1.5 border-b-2 border-indigo-100">${renderInline(m[1])}</h2>`);
    } else if ((m = line.match(/^# (.+)$/))) {
      flushList();
      out.push(`<h1 class="text-xl font-bold text-indigo-700 mt-2 mb-4">${renderInline(m[1])}</h1>`);
    } else if ((m = line.match(/^> (.+)$/))) {
      flushList();
      out.push(`<div class="my-2 rounded-lg border-l-4 border-amber-400 bg-amber-50 px-4 py-2.5 text-sm text-amber-900 font-medium leading-relaxed">💡 ${renderInline(m[1])}</div>`);
    } else if (/^---+$/.test(line)) {
      flushList();
      out.push('<hr class="my-4 border-slate-200"/>');
    } else if ((m = line.match(/^\d+\. (.+)$/))) {
      if (list && list.type !== "ol") flushList();
      if (!list) list = { type: "ol", items: [] };
      list.items.push(renderInline(m[1]));
    } else if ((m = line.match(/^[-*] (.+)$/))) {
      if (list && list.type !== "ul") flushList();
      if (!list) list = { type: "ul", items: [] };
      list.items.push(renderInline(m[1]));
    } else if (line.trim() === "") {
      flushList();
    } else {
      flushList();
      out.push(`<p class="text-slate-700 leading-relaxed my-2">${renderInline(line)}</p>`);
    }
  }
  flushList();

  return out.join("\n");
}

function OutputStatus({ status }: { status: string }) {
  const map: Record<string, { colour: string; icon: React.ReactNode; label: string }> = {
    ready:      { colour: "text-emerald-600", icon: <CheckCircle2 className="h-3.5 w-3.5" />, label: "Ready" },
    processing: { colour: "text-amber-600",   icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />, label: "Processing" },
    pending:    { colour: "text-slate-400",   icon: <Loader2 className="h-3.5 w-3.5" />, label: "Pending" },
    failed:     { colour: "text-red-500",     icon: <AlertTriangle className="h-3.5 w-3.5" />, label: "Failed" },
    partial:    { colour: "text-orange-500",  icon: <AlertTriangle className="h-3.5 w-3.5" />, label: "Partial" },
  };
  const s = map[status] ?? map.pending;
  return (
    <span className={cn("flex items-center gap-1 text-xs font-medium", s.colour)}>
      {s.icon}{s.label}
    </span>
  );
}

// ─── Score ring ───────────────────────────────────────────────────────────────

function ScoreRing({ score, label, size = 80 }: { score: number | null | undefined; label: string; size?: number }) {
  const val = score ?? 0;
  const pct = Math.min(100, Math.max(0, val * 10));
  const r = (size - 12) / 2;
  const circ = 2 * Math.PI * r;
  const dash = (pct / 100) * circ;
  const colour = pct >= 70 ? "#10b981" : pct >= 40 ? "#f59e0b" : "#ef4444";

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="#e2e8f0" strokeWidth={6} />
        <circle
          cx={size/2} cy={size/2} r={r} fill="none"
          stroke={colour} strokeWidth={6}
          strokeDasharray={`${dash} ${circ}`}
          strokeLinecap="round"
          style={{ transition: "stroke-dasharray 0.8s ease" }}
        />
      </svg>
      <div className="text-center -mt-1">
        <p className="text-xl font-bold text-slate-800" style={{ color: colour }}>{val.toFixed(1)}</p>
        <p className="text-[0.6875rem] text-slate-500">{label}</p>
      </div>
    </div>
  );
}

// ─── Bloom bar ────────────────────────────────────────────────────────────────

const BLOOM_COLOURS: Record<string, string> = {
  remember:  "bg-slate-400",
  understand:"bg-blue-400",
  apply:     "bg-teal-500",
  analyze:   "bg-indigo-500",
  evaluate:  "bg-purple-500",
  create:    "bg-pink-500",
};

function BloomBars({ dist }: { dist: BloomDistribution }) {
  const keys = ["remember", "understand", "apply", "analyze", "evaluate", "create"] as const;
  const total = keys.reduce((s, k) => s + (dist[k] ?? 0), 0) || 1;
  return (
    <div className="space-y-1.5">
      {keys.map((k) => {
        const val = dist[k] ?? 0;
        const pct = Math.round((val / total) * 100);
        return (
          <div key={k} className="flex items-center gap-2 text-xs">
            <span className="w-20 text-slate-500 capitalize text-right shrink-0">{k}</span>
            <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
              <div
                className={cn("h-full rounded-full transition-all duration-700", BLOOM_COLOURS[k])}
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="w-6 text-slate-500 text-right">{val}</span>
          </div>
        );
      })}
    </div>
  );
}

// ─── Coverage progress ────────────────────────────────────────────────────────

function CoveragePill({ pct }: { pct: number | undefined }) {
  const val = pct ?? 0;
  const colour = val >= 70 ? "bg-emerald-500" : val >= 40 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs text-slate-500">
        <span>Syllabus Coverage</span>
        <span className="font-bold text-slate-700">{val}%</span>
      </div>
      <div className="h-2.5 bg-slate-100 rounded-full overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all duration-700", colour)}
          style={{ width: `${val}%` }}
        />
      </div>
    </div>
  );
}

// ─── Depth badge ─────────────────────────────────────────────────────────────

function DepthBadge({ depth }: { depth: string }) {
  const styles: Record<string, string> = {
    strong: "bg-emerald-100 text-emerald-700 border-emerald-200",
    medium: "bg-amber-100 text-amber-700 border-amber-200",
    weak:   "bg-red-100 text-red-600 border-red-200",
  };
  return (
    <span className={cn("text-[0.625rem] font-semibold px-1.5 py-0.5 rounded border uppercase tracking-wide", styles[depth] ?? "bg-slate-100 text-slate-500 border-slate-200")}>
      {depth}
    </span>
  );
}

// ─── Mind map renderer ────────────────────────────────────────────────────────

function MindMap({ text }: { text: string }) {
  if (!text) return null;
  return (
    <div className="rounded-xl bg-slate-950 border border-slate-800 p-4 overflow-x-auto">
      <pre className="text-sm leading-relaxed font-mono whitespace-pre text-slate-100 select-text">
        {text}
      </pre>
    </div>
  );
}

// ─── Diagram renderers ────────────────────────────────────────────────────────

const DIAGRAM_COLOURS = [
  "#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#a855f7",
];

function FlowchartDiagram({ steps, title }: { steps: string[]; title: string }) {
  if (!steps?.length) return null;
  const cols = Math.min(steps.length, 4);
  const w = 680;
  const boxW = 110;
  const boxH = 52;
  const gapX = cols > 1 ? (w - cols * boxW) / (cols + 1) : (w - boxW) / 2;
  const rows = Math.ceil(steps.length / cols);
  const rowH = 90;
  const svgH = rows * rowH + 20;

  return (
    <div className="rounded-xl bg-gradient-to-br from-indigo-50 to-blue-50 border border-indigo-100 p-4 overflow-x-auto">
      <p className="text-xs font-semibold text-indigo-700 uppercase tracking-wide mb-3">{title}</p>
      <svg viewBox={`0 0 ${w} ${svgH}`} className="w-full" style={{ minWidth: "18.75rem" }}>
        <defs>
          <marker id="arrowBlue" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
            <path d="M0,0 L0,6 L8,3 z" fill="#6366f1" />
          </marker>
        </defs>
        {steps.map((step, i) => {
          const row = Math.floor(i / cols);
          const col = i % cols;
          const cx = gapX + col * (boxW + gapX) + boxW / 2;
          const cy = row * rowH + boxH / 2 + 10;
          const colour = DIAGRAM_COLOURS[i % DIAGRAM_COLOURS.length];
          const isLast = i === steps.length - 1;
          const nextRow = Math.floor((i + 1) / cols);
          const nextCol = (i + 1) % cols;
          const ncx = gapX + nextCol * (boxW + gapX) + boxW / 2;
          const ncy = nextRow * rowH + boxH / 2 + 10;

          return (
            <g key={i}>
              {/* Arrow to next */}
              {!isLast && (
                col < cols - 1 ? (
                  // Horizontal arrow
                  <line
                    x1={cx + boxW / 2} y1={cy}
                    x2={cx + gapX - 4} y2={cy}
                    stroke="#6366f1" strokeWidth="1.5"
                    markerEnd="url(#arrowBlue)"
                    style={{ animation: `fadeIn 0.4s ease ${i * 0.15}s both` }}
                  />
                ) : (
                  // Down + across arrow when wrapping rows
                  <polyline
                    points={`${cx},${cy + boxH / 2} ${cx},${cy + rowH - boxH / 2} ${ncx},${ncy - boxH / 2}`}
                    fill="none" stroke="#6366f1" strokeWidth="1.5"
                    markerEnd="url(#arrowBlue)"
                    style={{ animation: `fadeIn 0.4s ease ${i * 0.15}s both` }}
                  />
                )
              )}
              {/* Box — solid fill with white text, not a translucent tint with
                  same-hue text (that pairing is near-invisible at small font
                  sizes regardless of the accent colour). */}
              <rect
                x={cx - boxW / 2} y={cy - boxH / 2}
                width={boxW} height={boxH}
                rx={8} fill={colour}
                style={{ animation: `fadeIn 0.35s ease ${i * 0.12}s both` }}
              />
              {/* Number badge — white circle now that the box itself is solid-coloured,
                  otherwise a same-colour badge would blend invisibly into it. */}
              <circle cx={cx - boxW / 2 + 12} cy={cy - boxH / 2 + 12} r={9} fill="white"
                style={{ animation: `fadeIn 0.35s ease ${i * 0.12}s both` }} />
              <text x={cx - boxW / 2 + 12} y={cy - boxH / 2 + 16} textAnchor="middle"
                fill={colour} fontSize={9} fontWeight="700">{i + 1}</text>
              {/* Label (wrap at ~16 chars) */}
              {(() => {
                const words = step.split(" ");
                const lines: string[] = [];
                let line = "";
                for (const word of words) {
                  if ((line + " " + word).trim().length > 14) { lines.push(line.trim()); line = word; }
                  else line = (line + " " + word).trim();
                }
                if (line) lines.push(line);
                const startY = cy - (lines.length - 1) * 7;
                return lines.map((ln, li) => (
                  <text key={li} x={cx + 4} y={startY + li * 14} textAnchor="middle"
                    fill="white" fontSize={10} fontWeight="600"
                    style={{ animation: `fadeIn 0.35s ease ${i * 0.12 + 0.1}s both` }}>
                    {ln}
                  </text>
                ));
              })()}
            </g>
          );
        })}
      </svg>
      <style>{`@keyframes fadeIn { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:translateY(0); } }`}</style>
    </div>
  );
}

function CycleDiagram({ nodes, title }: { nodes: string[]; title: string }) {
  if (!nodes?.length) return null;
  const n = nodes.length;
  const cx = 200, cy = 160, r = 110, br = 48, bh = 32;
  const svgW = 400, svgH = 320;

  return (
    <div className="rounded-xl bg-gradient-to-br from-teal-50 to-emerald-50 border border-teal-100 p-4 overflow-x-auto">
      <p className="text-xs font-semibold text-teal-700 uppercase tracking-wide mb-3">{title}</p>
      <svg viewBox={`0 0 ${svgW} ${svgH}`} className="w-full" style={{ minWidth: "16.25rem" }}>
        <defs>
          <marker id="arrowCycle" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto">
            <path d="M0,0 L0,6 L7,3 z" fill="#10b981" />
          </marker>
        </defs>
        {/* Circular arrows */}
        {nodes.map((_, i) => {
          const a1 = (2 * Math.PI * i / n) - Math.PI / 2;
          const a2 = (2 * Math.PI * (i + 0.8) / n) - Math.PI / 2;
          const x1 = cx + r * Math.cos(a1);
          const y1 = cy + r * Math.sin(a1);
          const x2 = cx + r * Math.cos(a2);
          const y2 = cy + r * Math.sin(a2);
          const largeArc = 0.8 / n > 0.5 ? 1 : 0;
          return (
            <path key={i}
              d={`M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2}`}
              fill="none" stroke="#10b981" strokeWidth="2" markerEnd="url(#arrowCycle)"
              style={{ animation: `fadeIn 0.5s ease ${i * 0.18}s both` }}
            />
          );
        })}
        {/* Node boxes */}
        {nodes.map((node, i) => {
          const angle = (2 * Math.PI * i / n) - Math.PI / 2;
          const nx = cx + r * Math.cos(angle);
          const ny = cy + r * Math.sin(angle);
          const colour = DIAGRAM_COLOURS[i % DIAGRAM_COLOURS.length];
          const words = node.split(" ");
          const lines: string[] = [];
          let line = "";
          for (const w of words) {
            if ((line + " " + w).trim().length > 12) { lines.push(line.trim()); line = w; }
            else line = (line + " " + w).trim();
          }
          if (line) lines.push(line);
          return (
            <g key={i} style={{ animation: `fadeIn 0.4s ease ${i * 0.15}s both` }}>
              {/* Solid fill + white text — a translucent tint with same-hue text
                  is near-invisible at this font size regardless of the accent colour. */}
              <rect x={nx - br} y={ny - bh} width={br * 2} height={bh * 2} rx={8} fill={colour} />
              {lines.map((ln, li) => (
                <text key={li} x={nx} y={ny - (lines.length - 1) * 7 + li * 13 + 4}
                  textAnchor="middle" fill="white" fontSize={10} fontWeight="600">{ln}</text>
              ))}
            </g>
          );
        })}
        {/* Center label */}
        <circle cx={cx} cy={cy} r={28} fill="white" stroke="#e2e8f0" strokeWidth={1.5} />
        <text x={cx} y={cy + 5} textAnchor="middle" fill="#64748b" fontSize={10} fontWeight="700">CYCLE</text>
      </svg>
      <style>{`@keyframes fadeIn { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:translateY(0); } }`}</style>
    </div>
  );
}

function ConceptMapDiagram({ center, branches, title }: { center: string; branches: string[]; title: string }) {
  if (!branches?.length) return null;
  const n = branches.length;
  const cxC = 240, cyC = 160, R = 120, nodeW = 90, nodeH = 34;
  const svgW = 480, svgH = 320;

  return (
    <div className="rounded-xl bg-gradient-to-br from-purple-50 to-indigo-50 border border-purple-100 p-4 overflow-x-auto">
      <p className="text-xs font-semibold text-purple-700 uppercase tracking-wide mb-3">{title}</p>
      <svg viewBox={`0 0 ${svgW} ${svgH}`} className="w-full" style={{ minWidth: "17.5rem" }}>
        {branches.map((branch, i) => {
          const angle = (2 * Math.PI * i / n) - Math.PI / 2;
          const nx = cxC + R * Math.cos(angle);
          const ny = cyC + R * Math.sin(angle);
          const colour = DIAGRAM_COLOURS[i % DIAGRAM_COLOURS.length];
          const words = branch.split(" ");
          const lines: string[] = [];
          let line = "";
          for (const w of words) {
            if ((line + " " + w).trim().length > 13) { lines.push(line.trim()); line = w; }
            else line = (line + " " + w).trim();
          }
          if (line) lines.push(line);
          return (
            <g key={i}>
              <line x1={cxC} y1={cyC} x2={nx} y2={ny}
                stroke={colour} strokeWidth={1.5} strokeDasharray="4 3" opacity={0.6}
                style={{ animation: `fadeIn 0.4s ease ${i * 0.12}s both` }} />
              {/* Solid fill + white text — a translucent tint with same-hue text
                  is near-invisible at this font size regardless of the accent colour. */}
              <rect x={nx - nodeW / 2} y={ny - nodeH} width={nodeW} height={nodeH * 2}
                rx={8} fill={colour}
                style={{ animation: `fadeIn 0.35s ease ${i * 0.12 + 0.05}s both` }} />
              {lines.map((ln, li) => (
                <text key={li} x={nx} y={ny - (lines.length - 1) * 6 + li * 12 + 4}
                  textAnchor="middle" fill="white" fontSize={9.5} fontWeight="600"
                  style={{ animation: `fadeIn 0.35s ease ${i * 0.12 + 0.1}s both` }}>{ln}</text>
              ))}
            </g>
          );
        })}
        {/* Central node */}
        <ellipse cx={cxC} cy={cyC} rx={52} ry={28}
          fill="#6366f1" fillOpacity={0.15} stroke="#6366f1" strokeWidth={2} />
        <text x={cxC} y={cyC - 5} textAnchor="middle" fill="#4338ca" fontSize={11} fontWeight="700">{center?.split(" ")[0]}</text>
        {center?.split(" ").slice(1).length > 0 && (
          <text x={cxC} y={cyC + 9} textAnchor="middle" fill="#4338ca" fontSize={10} fontWeight="700">
            {center.split(" ").slice(1).join(" ")}
          </text>
        )}
      </svg>
      <style>{`@keyframes fadeIn { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:translateY(0); } }`}</style>
    </div>
  );
}

function ComparisonDiagram({ left_label, right_label, left_items, right_items, title }: {
  left_label?: string; right_label?: string;
  left_items?: string[]; right_items?: string[]; title: string;
}) {
  const li = left_items ?? [];
  const ri = right_items ?? [];
  const rows = Math.max(li.length, ri.length);
  return (
    <div className="rounded-xl bg-gradient-to-br from-amber-50 to-orange-50 border border-amber-100 p-4">
      <p className="text-xs font-semibold text-amber-700 uppercase tracking-wide mb-3">{title}</p>
      <div className="grid grid-cols-2 gap-3">
        {[{ label: left_label ?? "A", items: li, colour: "bg-blue-100 text-blue-800 border-blue-200" },
          { label: right_label ?? "B", items: ri, colour: "bg-amber-100 text-amber-800 border-amber-200" }].map((side, si) => (
          <div key={si}>
            <div className={cn("rounded-lg border px-3 py-1.5 text-xs font-bold text-center mb-2", side.colour)}>
              {side.label}
            </div>
            <ul className="space-y-1.5">
              {side.items.map((item, ii) => (
                <li key={ii} className={cn("rounded-lg border px-3 py-1.5 text-xs", side.colour)}
                  style={{ animation: `fadeIn 0.3s ease ${ii * 0.1}s both` }}>
                  {item}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <style>{`@keyframes fadeIn { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:translateY(0); } }`}</style>
    </div>
  );
}

function DiagramRenderer({ diagram }: { diagram: Diagram }) {
  if (diagram.type === "flowchart" && diagram.steps?.length)
    return <FlowchartDiagram steps={diagram.steps} title={diagram.title} />;
  if (diagram.type === "cycle" && diagram.nodes?.length)
    return <CycleDiagram nodes={diagram.nodes} title={diagram.title} />;
  if (diagram.type === "concept_map" && diagram.branches?.length)
    return <ConceptMapDiagram center={diagram.center ?? diagram.title} branches={diagram.branches} title={diagram.title} />;
  if (diagram.type === "comparison")
    return <ComparisonDiagram {...diagram} />;
  return null;
}

function BoardDiagramCard({ diagram, sessionId }: { diagram: BoardDiagram; sessionId: string }) {
  const v = diagram.validation;
  const status: "correct" | "wrong" | "unvalidated" =
    v?.unvalidated || v?.is_correct === null || v?.is_correct === undefined
      ? "unvalidated"
      : v.is_correct
      ? "correct"
      : "wrong";

  const unvalidatedLabel = v?.reason === "crop_unclear" ? "Couldn't verify diagram" : "Not validated";
  const badge = {
    correct:     { label: "Looks correct",        cls: "bg-green-100 text-green-700" },
    wrong:       { label: "Possible error found",  cls: "bg-red-100 text-red-700" },
    unvalidated: { label: unvalidatedLabel,        cls: "bg-slate-100 text-slate-500" },
  }[status];

  return (
    <div className="rounded-xl border border-slate-200 overflow-hidden bg-white">
      <img
        src={getDiagramImageUrl(sessionId, diagram.frame_id, diagram.index)}
        alt={diagram.description || "Board diagram"}
        className="w-full max-h-72 object-contain bg-slate-50 border-b border-slate-100"
      />
      <div className="p-3 space-y-2">
        <div className="flex items-start justify-between gap-2">
          <p className="text-sm font-semibold text-slate-800">
            {v?.diagram_type || "Diagram"}
          </p>
          <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-[0.6875rem] font-semibold", badge.cls)}>
            {badge.label}
          </span>
        </div>
        {diagram.description && (
          <p className="text-xs text-slate-500 leading-relaxed">{diagram.description}</p>
        )}
        {v?.reason === "crop_unclear" && (
          <p className="text-xs text-slate-400 italic">
            The captured crop didn't clearly show a diagram — try recapturing the board photo.
          </p>
        )}
        {status === "wrong" && !!v.errors?.length && (
          <div className="space-y-1.5 pt-1">
            {v.errors.map((e, i) => (
              <div key={i} className="rounded-lg border border-red-100 bg-red-50 px-3 py-2">
                <p className="text-xs font-medium text-red-700">{e.issue}</p>
                {e.correct_version && (
                  <p className="text-xs text-red-600 mt-0.5">
                    <span className="font-semibold">Should be:</span> {e.correct_version}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Section header ───────────────────────────────────────────────────────────

function SectionHeading({ icon, title, badge }: { icon: React.ReactNode; title: string; badge?: string }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <span className="text-indigo-600">{icon}</span>
      <h3 className="font-semibold text-slate-800 text-sm">{title}</h3>
      {badge && (
        <span className="ml-auto text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full font-medium">{badge}</span>
      )}
    </div>
  );
}

// ─── PDF helpers ──────────────────────────────────────────────────────────────

const PDF_STYLES = `
  @import url('https://fonts.googleapis.com/css2?family=Noto+Sans:wght@400;600;700&family=Noto+Sans+Devanagari:wght@400;600;700&family=Noto+Sans+Kannada:wght@400;600;700&family=Noto+Sans+Telugu:wght@400;600;700&family=Noto+Sans+Tamil:wght@400;600;700&display=swap');
  * { box-sizing: border-box; }
  body { font-family: 'Noto Sans', 'Segoe UI', Arial, sans-serif; max-width: 760px; margin: 0 auto; padding: 32px 40px; color: #1e293b; line-height: 1.7; font-size: 14px; }
  .header { border-bottom: 3px solid #6366f1; padding-bottom: 16px; margin-bottom: 28px; display: flex; justify-content: space-between; align-items: flex-end; }
  .header-left h1 { margin: 0 0 4px; font-size: 22px; color: #312e81; font-weight: 700; }
  .header-left .meta { font-size: 13px; color: #64748b; }
  .header-right { text-align: right; font-size: 12px; color: #94a3b8; }
  .section { margin-bottom: 28px; }
  .section-title { font-size: 15px; font-weight: 700; color: #4338ca; border-left: 4px solid #6366f1; padding-left: 10px; margin: 0 0 12px; }
  .summary-box { background: #f0f4ff; border: 1px solid #c7d2fe; border-radius: 8px; padding: 14px 18px; font-size: 13px; font-style: italic; color: #3730a3; line-height: 1.8; }
  .score-row { display: flex; gap: 20px; margin-bottom: 16px; }
  .score-card { flex: 1; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 16px; text-align: center; }
  .score-val { font-size: 28px; font-weight: 800; }
  .score-label { font-size: 11px; color: #64748b; margin-top: 2px; }
  .score-green { color: #10b981; } .score-amber { color: #f59e0b; } .score-red { color: #ef4444; }
  .concept-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
  .concept-col h4 { font-size: 12px; font-weight: 700; margin: 0 0 8px; padding: 4px 8px; border-radius: 4px; }
  .col-green h4 { background: #dcfce7; color: #166534; }
  .col-amber h4  { background: #fef3c7; color: #92400e; }
  .col-red h4   { background: #fee2e2; color: #991b1b; }
  .concept-item { font-size: 12px; padding: 5px 8px; border-radius: 5px; margin-bottom: 5px; }
  .concept-item .sub { font-size: 10px; color: #64748b; margin-top: 1px; }
  .item-green { background: #f0fdf4; border: 1px solid #bbf7d0; }
  .item-amber  { background: #fffbeb; border: 1px solid #fde68a; }
  .item-red   { background: #fff1f2; border: 1px solid #fecdd3; }
  .badge { display: inline-block; font-size: 9px; font-weight: 700; padding: 1px 5px; border-radius: 3px; text-transform: uppercase; letter-spacing: 0.5px; margin-left: 4px; vertical-align: middle; }
  .badge-strong { background: #dcfce7; color: #166534; }
  .badge-medium { background: #fef3c7; color: #92400e; }
  .badge-weak   { background: #fee2e2; color: #991b1b; }
  .bloom-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-size: 12px; }
  .bloom-label { width: 72px; text-align: right; color: #64748b; text-transform: capitalize; }
  .bloom-track { flex: 1; height: 8px; background: #f1f5f9; border-radius: 4px; overflow: hidden; }
  .bloom-fill { height: 100%; border-radius: 4px; }
  .list-items { list-style: none; padding: 0; margin: 0; }
  .list-items li { font-size: 13px; padding: 6px 10px; border-radius: 6px; margin-bottom: 6px; display: flex; align-items: flex-start; gap: 8px; }
  .li-indigo { background: #eef2ff; border: 1px solid #c7d2fe; color: #3730a3; }
  .li-blue   { background: #eff6ff; border: 1px solid #bfdbfe; color: #1d4ed8; }
  .li-slate  { background: #f8fafc; border: 1px solid #e2e8f0; color: #334155; }
  .notes-content h1 { font-size: 18px; color: #312e81; margin: 20px 0 6px; }
  .notes-content h2 { font-size: 15px; color: #4338ca; margin: 16px 0 4px; border-left: 3px solid #6366f1; padding-left: 8px; }
  .notes-content h3 { font-size: 13px; color: #1e293b; margin: 12px 0 4px; }
  .notes-content p { margin: 6px 0; }
  .notes-content ul { margin: 6px 0 6px 20px; }
  .notes-content li { margin: 3px 0; }
  .notes-content code { background: #f1f5f9; padding: 1px 4px; border-radius: 3px; font-family: monospace; font-size: 12px; }
  .mindmap { background: #0f172a; border-radius: 8px; padding: 16px; margin: 8px 0; }
  .mindmap pre { color: #e2e8f0; font-family: 'Courier New', monospace; font-size: 11px; line-height: 1.5; margin: 0; white-space: pre-wrap; }
  .teacher-note { background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 14px 18px; margin-top: 20px; }
  .teacher-note h4 { color: #92400e; margin: 0 0 8px; font-size: 13px; }
  .footer { margin-top: 32px; padding-top: 10px; border-top: 1px solid #e2e8f0; font-size: 11px; color: #94a3b8; text-align: center; }
  @media print { body { padding: 16px; } }
`;

function mdToHtml(md: string): string {
  return md
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/^[-*] (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*?<\/li>\n?)+/gs, (m) => `<ul>${m}</ul>`)
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br/>');
}

function scoreColour(val: number | null | undefined, outOf10 = true): string {
  const pct = outOf10 ? (val ?? 0) * 10 : (val ?? 0);
  return pct >= 70 ? "score-green" : pct >= 40 ? "score-amber" : "score-red";
}

function downloadCurriculumPDF(opts: {
  notesData: NotesData | undefined;
  markdown: string | undefined;
  summaryText: string | undefined;
  subject: string;
  grade: string;
  date: string;
  teacherNotes: string;
  language: string;
}) {
  const { notesData, markdown, summaryText, subject, grade, date, teacherNotes, language } = opts;
  const langNote = language !== "english" ? ` · ${language.charAt(0).toUpperCase() + language.slice(1)}` : "";

  // Score row — hidden, unlock when ready
  // const score = notesData?.teaching_completeness_score;
  // const cvgPct = notesData?.curriculum_coverage?.syllabus_coverage_pct;
  // const scoreSection = (score != null || cvgPct != null) ? `
  //   <div class="score-row">
  //     ${score != null ? `<div class="score-card">...Teaching Score / 10...</div>` : ""}
  //     ${cvgPct != null ? `<div class="score-card">...Syllabus Coverage...</div>` : ""}
  //   </div>` : "";
  const scoreSection = "";

  // Concept grid
  const covered = notesData?.covered_concepts ?? [];
  const partial  = notesData?.partially_covered_concepts ?? [];
  const missing  = notesData?.missing_concepts ?? [];
  const conceptSection = (covered.length || partial.length || missing.length) ? `
    <div class="section">
      <div class="section-title">Concept Coverage</div>
      <div class="concept-grid">
        <div class="concept-col col-green"><h4>✅ Covered (${covered.length})</h4>
          ${covered.map(c => `<div class="concept-item item-green">${c.concept}<span class="badge badge-${c.depth}">${c.depth}</span><div class="sub">${c.bloom_level}</div></div>`).join("")}
        </div>
        <div class="concept-col col-amber"><h4>⚠️ Partial (${partial.length})</h4>
          ${partial.map(c => `<div class="concept-item item-amber">${c.concept}<div class="sub">${c.what_missing}</div></div>`).join("")}
        </div>
        <div class="concept-col col-red"><h4>❌ Not Covered (${missing.length})</h4>
          ${missing.map(c => `<div class="concept-item item-red">${c}</div>`).join("")}
        </div>
      </div>
    </div>` : "";

  // Bloom distribution
  const bloom = notesData?.bloom_distribution;
  const bloomKeys = ["remember","understand","apply","analyze","evaluate","create"] as const;
  const bloomTotal = bloom ? bloomKeys.reduce((s, k) => s + (bloom[k] ?? 0), 0) || 1 : 1;
  const bloomColours: Record<string, string> = { remember:"#94a3b8", understand:"#60a5fa", apply:"#2dd4bf", analyze:"#818cf8", evaluate:"#a78bfa", create:"#f472b6" };
  const bloomSection = bloom && bloomKeys.some(k => (bloom[k] ?? 0) > 0) ? `
    <div class="section">
      <div class="section-title">Bloom's Taxonomy Distribution</div>
      ${bloomKeys.map(k => {
        const v = bloom[k] ?? 0;
        const pct = Math.round((v / bloomTotal) * 100);
        return `<div class="bloom-row"><span class="bloom-label">${k}</span><div class="bloom-track"><div class="bloom-fill" style="width:${pct}%;background:${bloomColours[k]}"></div></div><span style="width:20px;text-align:right;font-size:11px;color:#64748b">${v}</span></div>`;
      }).join("")}
    </div>` : "";

  // Next topics + exercises
  const nextTopics = notesData?.recommended_next_topics ?? [];
  const exercises  = notesData?.suggested_exercises ?? [];
  const prereqs    = notesData?.missing_prerequisites ?? [];
  const extras = (nextTopics.length || exercises.length || prereqs.length) ? `
    <div style="display:grid;grid-template-columns:repeat(${[nextTopics, exercises, prereqs].filter(a=>a.length).length},1fr);gap:16px;margin-bottom:24px">
      ${nextTopics.length ? `<div><div class="section-title" style="font-size:13px">→ Recommended Next</div><ul class="list-items">${nextTopics.map(t=>`<li class="li-indigo">→ ${t}</li>`).join("")}</ul></div>` : ""}
      ${exercises.length  ? `<div><div class="section-title" style="font-size:13px">📝 Exercises</div><ul class="list-items">${exercises.map((e,i)=>`<li class="li-slate"><span style="background:#e0e7ff;color:#3730a3;border-radius:50%;width:18px;height:18px;display:inline-flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;flex-shrink:0">${i+1}</span>${e}</li>`).join("")}</ul></div>` : ""}
      ${prereqs.length    ? `<div><div class="section-title" style="font-size:13px">🔵 Missing Prerequisites</div><ul class="list-items">${prereqs.map(p=>`<li class="li-blue">🔵 ${p}</li>`).join("")}</ul></div>` : ""}
    </div>` : "";

  // Mind map
  const mindMapSection = notesData?.mind_map ? `
    <div class="section">
      <div class="section-title">Topic Mind Map</div>
      <div class="mindmap"><pre>${notesData.mind_map}</pre></div>
    </div>` : "";

  // Study notes (markdown)
  const notesSection = markdown ? `
    <div class="section">
      <div class="section-title">📄 Study Notes</div>
      <div class="notes-content"><p>${mdToHtml(markdown)}</p></div>
    </div>` : summaryText ? `
    <div class="section">
      <div class="section-title">📄 Session Summary</div>
      <p>${summaryText}</p>
    </div>` : "";

  const teacherSection = teacherNotes.trim() ? `
    <div class="teacher-note"><h4>Teacher's Notes</h4><p style="font-size:13px">${teacherNotes.replace(/\n/g,"<br/>")}</p></div>` : "";

  const html = `<!DOCTYPE html><html><head><meta charset="UTF-8"/>
<title>${subject || "Class"} — Curriculum Report${langNote}</title>
<style>${PDF_STYLES}</style></head><body>
<div class="header">
  <div class="header-left">
    <h1>${subject || "Class"} — Curriculum Intelligence Report${langNote}</h1>
    <div class="meta">${grade ? grade + " &nbsp;·&nbsp; " : ""}${date}</div>
  </div>
  <div class="header-right">Drishti</div>
</div>
${notesData?.session_summary || summaryText ? `<div class="section"><div class="section-title">Session Summary</div><div class="summary-box">${notesData?.session_summary ?? summaryText}</div></div>` : ""}
${scoreSection}
${conceptSection}
${bloomSection}
${extras}
${mindMapSection}
${notesSection}
${teacherSection}
<div class="footer">Generated by Drishti &nbsp;·&nbsp; ${date}${langNote}</div>
</body></html>`;

  const win = window.open("", "_blank");
  if (!win) return;
  win.document.write(html);
  win.document.close();
  win.focus();
  setTimeout(() => { win.print(); }, 500);
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function NotesPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  const [generating, setGenerating] = useState(false);
  const [genMsg, setGenMsg] = useState("");
  const [activeTab, setActiveTab] = useState<"intelligence" | "notes">("intelligence");
  const [teacherNotes, setTeacherNotes] = useState("");
  const { language, setLanguage, translating, translate, t } = useTranslation();

  const { data: outputs, error, isLoading, mutate } = useSWR(
    ["outputs", sessionId],
    () => fetchOutputsCached(sessionId),
    {
      refreshInterval: (data) => {
        const hasProcessing = Object.values(data?.outputs ?? {}).some(
          o => o.status === "pending" || o.status === "processing"
        );
        return hasProcessing ? 5000 : 30000;
      },
    }
  );

  async function handleGenerate() {
    setGenerating(true);
    setGenMsg("");
    try {
      await api.triggerGeneration(sessionId);
      setGenMsg("Generation queued — curriculum intelligence will appear in ~2 minutes.");
      mutate();
    } catch (err: unknown) {
      setGenMsg(err instanceof Error ? err.message : "Failed to trigger generation.");
    } finally {
      setGenerating(false);
    }
  }

  const { data: session } = useSWR(
    ["session", sessionId],
    () => api.getSession(sessionId),
    { revalidateOnFocus: false }
  );

  const notesOutput   = outputs?.outputs?.notes;
  const summaryOutput = outputs?.outputs?.summary;
  const notesData     = notesOutput?.data as NotesData | undefined;
  const summaryText   = summaryOutput?.data?.text as string | undefined;
  const markdown      = notesData?.markdown;
  const diagrams      = notesData?.diagrams ?? [];
  const boardDiagrams = notesData?.board_diagrams ?? [];
  const hasRichData   = !!(notesData?.mind_map || notesData?.covered_concepts?.length || diagrams.length);

  // Collect all translatable strings whenever data or language changes
  useEffect(() => {
    if (!notesData && !summaryText) return;
    const strings = [
      notesData?.session_summary,
      notesData?.topic_detected,
      summaryText,
      notesData?.mind_map,
      markdown,
      ...(notesData?.covered_concepts?.map(c => c.concept) ?? []),
      ...(notesData?.partially_covered_concepts?.flatMap(c => [c.concept, c.what_missing]) ?? []),
      ...(notesData?.missing_concepts ?? []),
      ...(notesData?.missing_prerequisites ?? []),
      ...(notesData?.recommended_next_topics ?? []),
      ...(notesData?.suggested_exercises ?? []),
      ...(notesData?.curriculum_coverage?.missing_learning_objectives ?? []),
    ].filter((s): s is string => Boolean(s));
    translate(strings);
  }, [language, notesData, summaryText, markdown, translate]);

  const sessionDate = session?.created_at
    ? new Date(session.created_at.endsWith("Z") ? session.created_at : session.created_at + "Z")
        .toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
    : new Date().toLocaleDateString("en-IN");

  // Voice command bridge — ClassroomBrain has no direct access to this
  // page's state, so it dispatches an event and this page does the actual
  // download with whatever data is currently loaded.
  useEffect(() => {
    const handler = () => {
      if (!notesData && !markdown) return;
      downloadCurriculumPDF({
        notesData, markdown, summaryText,
        subject: session?.subject ?? "",
        grade: session?.grade ?? "",
        date: sessionDate,
        teacherNotes,
        language,
      });
    };
    window.addEventListener("classroom-brain:download_pdf", handler);
    return () => window.removeEventListener("classroom-brain:download_pdf", handler);
  }, [notesData, markdown, summaryText, session, sessionDate, teacherNotes, language]);

  return (
    <div className="space-y-5">
      {/* ── Header ── */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <div className="flex items-center gap-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-600 text-white">
              <Brain className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-900">Curriculum Intelligence</h1>
              <p className="text-xs text-slate-500">Classroom insights &amp; study notes from today's session</p>
            </div>
          </div>
        </div>
        <div className="flex gap-2 flex-wrap items-center">
          <LanguageSelector value={language} onChange={setLanguage} translating={translating} />
          {(notesData || markdown) && (
            <button
              onClick={() => downloadCurriculumPDF({
                notesData,
                markdown,
                summaryText,
                subject: session?.subject ?? "",
                grade: session?.grade ?? "",
                date: sessionDate,
                teacherNotes,
                language,
              })}
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 shadow-sm transition-colors"
            >
              <Download className="h-3.5 w-3.5" /> Download PDF
            </button>
          )}
          <Button variant="secondary" size="sm" onClick={() => mutate()}>
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
          <Button size="sm" loading={generating} onClick={handleGenerate}>
            <Cpu className="h-4 w-4" /> Generate AI
          </Button>
        </div>
      </div>

      {/* ── Quick nav ── */}
      <div className="flex flex-wrap gap-2 text-xs">
        {[
          { href: "quiz",             label: "Quiz" },
          { href: "experiments",      label: "Experiments" },
          { href: "missing-concepts", label: "Opportunities" },
          { href: "tiqer",            label: "TiQer Export" },
          { href: "lesson-plan",      label: "Lesson Plan" },
          { href: "class-analysis",   label: "Classroom Snapshot" },
        ].map(({ href, label }) => (
          <Link key={href} href={`/sessions/${sessionId}/${href}`}>
            <span className="flex items-center gap-1 rounded-full border border-slate-200 bg-white px-3 py-1 text-slate-600 hover:border-indigo-300 hover:text-indigo-600 transition-colors">
              {label} <ChevronRight className="h-3 w-3" />
            </span>
          </Link>
        ))}
      </div>

      {genMsg && (
        <div className="rounded-lg bg-indigo-50 border border-indigo-100 px-4 py-3 text-sm text-indigo-700">{genMsg}</div>
      )}

      {isLoading && <LoadingScreen label="Loading curriculum intelligence…" />}

      {!isLoading && !outputs && (
        <Card>
          <CardContent className="py-16 text-center space-y-4">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-indigo-50">
              <Brain className="h-8 w-8 text-indigo-400" />
            </div>
            <div>
              <p className="font-semibold text-slate-700">No curriculum intelligence yet</p>
              <p className="text-sm text-slate-400 mt-1">Capture board photos, then generate AI outputs</p>
            </div>
            <Button size="sm" loading={generating} onClick={handleGenerate}>
              <Cpu className="h-4 w-4" /> Generate Now
            </Button>
          </CardContent>
        </Card>
      )}

      {outputs && (
        <>
          {/* ── Tab switcher (only when rich data) ── */}
          {hasRichData && (
            <div className="flex gap-1 rounded-xl bg-slate-100 p-1 w-fit">
              {(["intelligence", "notes"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setActiveTab(t)}
                  className={cn(
                    "rounded-lg px-4 py-1.5 text-xs font-semibold transition-all",
                    activeTab === t
                      ? "bg-white text-indigo-700 shadow-sm"
                      : "text-slate-500 hover:text-slate-700"
                  )}
                >
                  {t === "intelligence" ? "🧠 Curriculum Intelligence" : "📄 Study Notes"}
                </button>
              ))}
            </div>
          )}

          {/* ═══════════ CURRICULUM INTELLIGENCE TAB ═══════════ */}
          {(activeTab === "intelligence" || !hasRichData) && (
            <div className="space-y-5">

              {/* Row 1: Summary + Scores */}
              <div className="grid gap-4 md:grid-cols-3">

                {/* Session summary */}
                <Card className="md:col-span-2">
                  <CardHeader>
                    <div className="flex items-center gap-2">
                      <BookOpen className="h-4 w-4 text-indigo-600" />
                      <CardTitle>
                        {notesData?.topic_detected
                          ? `Today's Topic: ${t(notesData.topic_detected)}`
                          : "Class Summary"}
                      </CardTitle>
                    </div>
                    <OutputStatus status={notesOutput?.status ?? "pending"} />
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {notesData?.session_summary && (
                      <p className="text-sm text-slate-700 leading-relaxed border-l-4 border-indigo-200 pl-3 italic">
                        {t(notesData.session_summary)}
                      </p>
                    )}
                    {summaryText && (
                      <p className="text-sm text-slate-600 leading-relaxed">{t(summaryText)}</p>
                    )}
                    {!notesData?.session_summary && !summaryText && (
                      <p className="text-sm text-slate-400 italic">
                        {notesOutput?.status === "processing" ? "Generating…" : "Not yet generated."}
                      </p>
                    )}
                  </CardContent>
                </Card>

                {/* TEACHING SCORE — hidden, unlock when ready:
                <Card>
                  <CardHeader>
                    <div className="flex items-center gap-2">
                      <Award className="h-4 w-4 text-amber-500" />
                      <CardTitle>Teaching Score</CardTitle>
                    </div>
                  </CardHeader>
                  <CardContent className="flex flex-col items-center gap-4">
                    <ScoreRing score={notesData?.teaching_completeness_score} label="Completeness" />
                    {notesData?.curriculum_coverage && (
                      <div className="w-full">
                        <CoveragePill pct={notesData.curriculum_coverage.syllabus_coverage_pct} />
                      </div>
                    )}
                  </CardContent>
                </Card>
                */}
              </div>

              {/* Row 2: Mind Map */}
              {notesData?.mind_map && (
                <Card>
                  <CardHeader>
                    <div className="flex items-center gap-2">
                      <Layers className="h-4 w-4 text-indigo-600" />
                      <CardTitle>Topic Mind Map</CardTitle>
                    </div>
                    <span className="text-xs text-slate-400">
                      🟢 Covered &nbsp;🟡 Partial &nbsp;🔴 Not Covered &nbsp;⚪ Mentioned &nbsp;🔵 Prerequisite Missing
                    </span>
                  </CardHeader>
                  <CardContent>
                    <MindMap text={t(notesData.mind_map)} />
                  </CardContent>
                </Card>
              )}

              {/* Row 3: Diagrams */}
              {diagrams.length > 0 && (
                <Card>
                  <CardHeader>
                    <div className="flex items-center gap-2">
                      <GitBranch className="h-4 w-4 text-indigo-600" />
                      <CardTitle>Visual Diagrams</CardTitle>
                      <span className="ml-auto text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full font-medium">
                        {diagrams.length} diagram{diagrams.length !== 1 ? "s" : ""}
                      </span>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {diagrams.map((d, i) => (
                      <DiagramRenderer key={i} diagram={d} />
                    ))}
                  </CardContent>
                </Card>
              )}

              {/* Row 3b: Board Diagrams — actual photos of diagrams drawn on the board,
                  with AI correctness validation */}
              {boardDiagrams.length > 0 && (
                <Card>
                  <CardHeader>
                    <div className="flex items-center gap-2">
                      <BookOpen className="h-4 w-4 text-indigo-600" />
                      <CardTitle>Board Diagrams</CardTitle>
                      <span className="ml-auto text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full font-medium">
                        {boardDiagrams.length} diagram{boardDiagrams.length !== 1 ? "s" : ""}
                      </span>
                    </div>
                  </CardHeader>
                  <CardContent className="grid gap-4 sm:grid-cols-2">
                    {boardDiagrams.map((d, i) => (
                      <BoardDiagramCard key={`${d.frame_id}-${d.index}-${i}`} diagram={d} sessionId={sessionId} />
                    ))}
                  </CardContent>
                </Card>
              )}

              {/* Row 4: Concept Coverage grid */}
              {(notesData?.covered_concepts?.length || notesData?.partially_covered_concepts?.length || notesData?.missing_concepts?.length) ? (
                <div className="grid gap-4 md:grid-cols-3">

                  {/* Covered */}
                  {notesData.covered_concepts && notesData.covered_concepts.length > 0 && (
                    <Card>
                      <CardHeader>
                        <div className="flex items-center gap-2">
                          <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                          <CardTitle className="text-emerald-700">Covered Concepts</CardTitle>
                          <span className="ml-auto text-xs bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded-full font-medium">
                            {notesData.covered_concepts.length}
                          </span>
                        </div>
                      </CardHeader>
                      <CardContent>
                        <ul className="space-y-2">
                          {notesData.covered_concepts.map((c, i) => (
                            <li key={i} className="flex items-start justify-between gap-2 rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2">
                              <div>
                                <p className="text-sm font-medium text-emerald-900">{t(c.concept)}</p>
                                <p className="text-[0.6875rem] text-emerald-600 capitalize mt-0.5">{c.bloom_level}</p>
                              </div>
                              <DepthBadge depth={c.depth} />
                            </li>
                          ))}
                        </ul>
                      </CardContent>
                    </Card>
                  )}

                  {/* Partially covered */}
                  {notesData.partially_covered_concepts && notesData.partially_covered_concepts.length > 0 && (
                    <Card>
                      <CardHeader>
                        <div className="flex items-center gap-2">
                          <AlertTriangle className="h-4 w-4 text-amber-500" />
                          <CardTitle className="text-amber-700">Partially Covered</CardTitle>
                          <span className="ml-auto text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-medium">
                            {notesData.partially_covered_concepts.length}
                          </span>
                        </div>
                      </CardHeader>
                      <CardContent>
                        <ul className="space-y-2">
                          {notesData.partially_covered_concepts.map((c, i) => (
                            <li key={i} className="rounded-lg border border-amber-100 bg-amber-50 px-3 py-2">
                              <p className="text-sm font-medium text-amber-900">{t(c.concept)}</p>
                              <p className="text-[0.6875rem] text-amber-600 mt-0.5">{t(c.what_missing)}</p>
                            </li>
                          ))}
                        </ul>
                      </CardContent>
                    </Card>
                  )}

                  {/* Missing concepts */}
                  {notesData.missing_concepts && notesData.missing_concepts.length > 0 && (
                    <Card>
                      <CardHeader>
                        <div className="flex items-center gap-2">
                          <AlertTriangle className="h-4 w-4 text-red-500" />
                          <CardTitle className="text-red-700">Not Covered</CardTitle>
                          <span className="ml-auto text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-medium">
                            {notesData.missing_concepts.length}
                          </span>
                        </div>
                      </CardHeader>
                      <CardContent>
                        <ul className="space-y-2">
                          {notesData.missing_concepts.map((c, i) => (
                            <li key={i} className="flex items-center gap-2 rounded-lg border border-red-100 bg-red-50 px-3 py-2">
                              <span className="text-red-400">🔴</span>
                              <p className="text-sm text-red-800">{t(c)}</p>
                            </li>
                          ))}
                        </ul>
                      </CardContent>
                    </Card>
                  )}
                </div>
              ) : null}

              {/* Row 5: Bloom + Prerequisites + Next Topics */}
              <div className="grid gap-4 md:grid-cols-3">

                {notesData?.bloom_distribution && Object.values(notesData.bloom_distribution).some(v => v > 0) && (
                  <Card>
                    <CardHeader>
                      <div className="flex items-center gap-2">
                        <Brain className="h-4 w-4 text-purple-600" />
                        <CardTitle>Bloom's Taxonomy</CardTitle>
                      </div>
                    </CardHeader>
                    <CardContent>
                      <BloomBars dist={notesData.bloom_distribution} />
                    </CardContent>
                  </Card>
                )}

                {notesData?.missing_prerequisites && notesData.missing_prerequisites.length > 0 && (
                  <Card>
                    <CardHeader>
                      <div className="flex items-center gap-2">
                        <AlertTriangle className="h-4 w-4 text-blue-500" />
                        <CardTitle className="text-blue-700">Missing Prerequisites</CardTitle>
                      </div>
                    </CardHeader>
                    <CardContent>
                      <ul className="space-y-2">
                        {notesData.missing_prerequisites.map((p, i) => (
                          <li key={i} className="flex items-center gap-2 text-sm text-blue-700 bg-blue-50 rounded-lg px-3 py-2 border border-blue-100">
                            <span>🔵</span>{t(p)}
                          </li>
                        ))}
                      </ul>
                    </CardContent>
                  </Card>
                )}

                {notesData?.recommended_next_topics && notesData.recommended_next_topics.length > 0 && (
                  <Card>
                    <CardHeader>
                      <div className="flex items-center gap-2">
                        <ArrowRight className="h-4 w-4 text-indigo-600" />
                        <CardTitle>Recommended Next</CardTitle>
                      </div>
                    </CardHeader>
                    <CardContent>
                      <ul className="space-y-2">
                        {notesData.recommended_next_topics.map((topic, i) => (
                          <li key={i} className="flex items-center gap-2 text-sm text-indigo-700 bg-indigo-50 rounded-lg px-3 py-2 border border-indigo-100">
                            <span className="text-indigo-400">→</span>{t(topic)}
                          </li>
                        ))}
                      </ul>
                    </CardContent>
                  </Card>
                )}
              </div>

              {/* Row 6: Missing learning objectives + Exercises */}
              {(notesData?.curriculum_coverage?.missing_learning_objectives?.length || notesData?.suggested_exercises?.length) ? (
                <div className="grid gap-4 md:grid-cols-2">
                  {notesData?.curriculum_coverage?.missing_learning_objectives && notesData.curriculum_coverage.missing_learning_objectives.length > 0 && (
                    <Card>
                      <CardHeader>
                        <SectionHeading
                          icon={<Target className="h-4 w-4" />}
                          title="Missing Learning Objectives"
                          badge={`${notesData.curriculum_coverage.missing_learning_objectives.length}`}
                        />
                      </CardHeader>
                      <CardContent>
                        <ul className="space-y-2">
                          {notesData.curriculum_coverage.missing_learning_objectives.map((obj, i) => (
                            <li key={i} className="flex items-start gap-2 text-sm text-slate-700">
                              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-200 text-[0.625rem] font-bold text-slate-600 mt-0.5">{i+1}</span>
                              {t(obj)}
                            </li>
                          ))}
                        </ul>
                      </CardContent>
                    </Card>
                  )}
                  {notesData?.suggested_exercises && notesData.suggested_exercises.length > 0 && (
                    <Card>
                      <CardHeader>
                        <SectionHeading
                          icon={<TrendingUp className="h-4 w-4" />}
                          title="Suggested Exercises"
                          badge={`${notesData.suggested_exercises.length}`}
                        />
                      </CardHeader>
                      <CardContent>
                        <ul className="space-y-2">
                          {notesData.suggested_exercises.map((ex, i) => (
                            <li key={i} className="flex items-start gap-2 text-sm text-slate-700 bg-slate-50 rounded-lg px-3 py-2 border border-slate-100">
                              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-[0.625rem] font-bold text-indigo-600 mt-0.5">{i+1}</span>
                              {t(ex)}
                            </li>
                          ))}
                        </ul>
                      </CardContent>
                    </Card>
                  )}
                </div>
              ) : null}

              {/* All outputs status */}
              <Card>
                <CardHeader><CardTitle className="text-sm text-slate-600">All Output Statuses</CardTitle></CardHeader>
                <CardContent className="p-0">
                  <ul className="divide-y divide-slate-50">
                    {Object.entries(outputs.outputs).map(([key, val]) => (
                      <li key={key} className="flex items-center justify-between px-5 py-2.5">
                        <span className="text-sm text-slate-600 capitalize">{key.replace(/_/g, " ")}</span>
                        <OutputStatus status={val.status} />
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            </div>
          )}

          {/* ═══════════ STUDY NOTES TAB ═══════════ */}
          {activeTab === "notes" && (
            <div className="grid gap-6 lg:grid-cols-4">
              <div className="lg:col-span-1 space-y-4">
                {/* Summary sidebar */}
                {summaryText && (
                  <Card>
                    <CardHeader>
                      <CardTitle>Summary</CardTitle>
                      <OutputStatus status={summaryOutput?.status ?? "pending"} />
                    </CardHeader>
                    <CardContent>
                      <p className="text-sm text-slate-700 leading-relaxed">{t(summaryText)}</p>
                    </CardContent>
                  </Card>
                )}

                {/* TEACHING SCORE SIDEBAR — hidden, unlock when ready:
                {notesData?.teaching_completeness_score != null && (
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-sm">Teaching Score</CardTitle>
                    </CardHeader>
                    <CardContent className="flex flex-col items-center gap-3">
                      <ScoreRing score={notesData.teaching_completeness_score} label="/ 10" size={72} />
                      {notesData.curriculum_coverage && (
                        <CoveragePill pct={notesData.curriculum_coverage.syllabus_coverage_pct} />
                      )}
                    </CardContent>
                  </Card>
                )}
                */}

                <Card>
                  <CardHeader><CardTitle className="text-sm">All Outputs</CardTitle></CardHeader>
                  <CardContent className="p-0">
                    <ul className="divide-y divide-slate-50">
                      {Object.entries(outputs.outputs).map(([key, val]) => (
                        <li key={key} className="flex items-center justify-between px-4 py-2">
                          <span className="text-xs text-slate-600 capitalize">{key.replace(/_/g, " ")}</span>
                          <OutputStatus status={val.status} />
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              </div>

              {/* Notes content */}
              <div className="lg:col-span-3 space-y-4">
                <Card>
                  <CardHeader>
                    <div className="flex items-center gap-2">
                      <FileText className="h-4 w-4 text-indigo-600" />
                      <CardTitle>Structured Study Notes</CardTitle>
                    </div>
                    <div className="flex items-center gap-2">
                      <OutputStatus status={notesOutput?.status ?? "pending"} />
                    </div>
                  </CardHeader>
                  <CardContent>
                    {markdown ? (
                      <div
                        className="max-w-none"
                        dangerouslySetInnerHTML={{ __html: renderMarkdown(t(markdown)) }}
                      />
                    ) : (
                      <div className="flex flex-col items-center gap-3 py-16 text-slate-400">
                        <Lightbulb className="h-10 w-10" />
                        <p className="text-sm">
                          {notesOutput?.status === "processing"
                            ? "AI is generating notes…"
                            : "Notes will appear here after AI generation."}
                        </p>
                      </div>
                    )}
                  </CardContent>
                </Card>

                {/* Diagrams in Study Notes tab */}
                {diagrams.length > 0 && (
                  <Card>
                    <CardHeader>
                      <div className="flex items-center gap-2">
                        <GitBranch className="h-4 w-4 text-indigo-600" />
                        <CardTitle>Visual Diagrams</CardTitle>
                        <span className="ml-auto text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full font-medium">
                          {diagrams.length} diagram{diagrams.length !== 1 ? "s" : ""}
                        </span>
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      {diagrams.map((d, i) => (
                        <DiagramRenderer key={i} diagram={d} />
                      ))}
                    </CardContent>
                  </Card>
                )}

                {/* Board diagrams in Study Notes tab */}
                {boardDiagrams.length > 0 && (
                  <Card>
                    <CardHeader>
                      <div className="flex items-center gap-2">
                        <BookOpen className="h-4 w-4 text-indigo-600" />
                        <CardTitle>Board Diagrams</CardTitle>
                        <span className="ml-auto text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full font-medium">
                          {boardDiagrams.length} diagram{boardDiagrams.length !== 1 ? "s" : ""}
                        </span>
                      </div>
                    </CardHeader>
                    <CardContent className="grid gap-4 sm:grid-cols-2">
                      {boardDiagrams.map((d, i) => (
                        <BoardDiagramCard key={`${d.frame_id}-${d.index}-${i}`} diagram={d} sessionId={sessionId} />
                      ))}
                    </CardContent>
                  </Card>
                )}

                {/* Teacher annotations — appended to PDF */}
                <Card>
                  <CardHeader>
                    <div className="flex items-center gap-2">
                      <Lightbulb className="h-4 w-4 text-amber-500" />
                      <CardTitle>Teacher's Notes</CardTitle>
                    </div>
                    <span className="text-xs text-slate-400">Optional — included in PDF download</span>
                  </CardHeader>
                  <CardContent>
                    <textarea
                      value={teacherNotes}
                      onChange={e => setTeacherNotes(e.target.value)}
                      placeholder="Add any extra notes, reminders, or tips to include in the student handout…"
                      rows={4}
                      className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-700 placeholder:text-slate-400 focus:border-indigo-300 focus:outline-none focus:ring-1 focus:ring-indigo-300 resize-none"
                    />
                  </CardContent>
                </Card>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
