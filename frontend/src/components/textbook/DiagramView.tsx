"use client";

/**
 * Renders a labeled "cycle" or "sequence" diagram from plain text nodes —
 * deliberately NOT an image-generation call. The content is nothing but
 * boxes, arrows, and the model's own short labels (already validated
 * server-side: 2-6 short plain-language strings, see
 * app/ai/response_parser.py:_parse_diagram_spec), so there is no raster
 * content-safety surface here at all — the safest possible way to give a
 * segment a visual when no real textbook figure fits.
 */

import type { TextbookDiagramSpec } from "@/lib/api";

const BOX_FILL = "#eef2ff";
const BOX_STROKE = "#6366f1";
const TEXT_COLOUR = "#312e81";
const ARROW_COLOUR = "#818cf8";

function wrapLabel(label: string, maxCharsPerLine = 16): string[] {
  const words = label.split(/\s+/);
  const lines: string[] = [];
  let current = "";
  for (const word of words) {
    const next = current ? `${current} ${word}` : word;
    if (next.length > maxCharsPerLine && current) {
      lines.push(current);
      current = word;
    } else {
      current = next;
    }
  }
  if (current) lines.push(current);
  return lines.slice(0, 3);
}

function NodeBox({ x, y, w, h, label }: { x: number; y: number; w: number; h: number; label: string }) {
  const lines = wrapLabel(label);
  const lineHeight = 15;
  const startY = y + h / 2 - ((lines.length - 1) * lineHeight) / 2;
  return (
    <g>
      <rect
        x={x} y={y} width={w} height={h} rx={12}
        fill={BOX_FILL} stroke={BOX_STROKE} strokeWidth={1.5}
      />
      <text x={x + w / 2} y={startY} textAnchor="middle" fontSize={13} fontWeight={600} fill={TEXT_COLOUR}>
        {lines.map((line, i) => (
          <tspan key={i} x={x + w / 2} dy={i === 0 ? 0 : lineHeight}>{line}</tspan>
        ))}
      </text>
    </g>
  );
}

function SequenceDiagram({ nodes }: { nodes: string[] }) {
  const boxW = 130, boxH = 64, gap = 44;
  const totalW = nodes.length * boxW + (nodes.length - 1) * gap;
  const viewW = totalW + 40;
  const viewH = boxH + 40;
  return (
    <svg viewBox={`0 0 ${viewW} ${viewH}`} className="w-full h-auto max-w-xl mx-auto" role="img" aria-label={nodes.join(" then ")}>
      <defs>
        <marker id="seq-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill={ARROW_COLOUR} />
        </marker>
      </defs>
      {nodes.map((label, i) => {
        const x = 20 + i * (boxW + gap);
        const y = 20;
        return (
          <g key={i}>
            <NodeBox x={x} y={y} w={boxW} h={boxH} label={label} />
            {i < nodes.length - 1 && (
              <line
                x1={x + boxW} y1={y + boxH / 2} x2={x + boxW + gap} y2={y + boxH / 2}
                stroke={ARROW_COLOUR} strokeWidth={2} markerEnd="url(#seq-arrow)"
              />
            )}
          </g>
        );
      })}
    </svg>
  );
}

function CycleDiagram({ nodes }: { nodes: string[] }) {
  const size = 340;
  const cx = size / 2, cy = size / 2;
  const radius = size / 2 - 70;
  const boxW = 118, boxH = 60;

  const positions = nodes.map((_, i) => {
    const angle = (i / nodes.length) * 2 * Math.PI - Math.PI / 2;
    return { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) };
  });

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="w-full h-auto max-w-sm mx-auto" role="img" aria-label={`Cycle: ${nodes.join(", ")}`}>
      <defs>
        <marker id="cycle-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill={ARROW_COLOUR} />
        </marker>
      </defs>
      {positions.map((pos, i) => {
        const next = positions[(i + 1) % positions.length];
        // Pull the connecting arc slightly toward the circle's own centre
        // so it reads as a loop rather than straight spokes crossing the middle.
        const midX = (pos.x + next.x) / 2 + (cx - (pos.x + next.x) / 2) * 0.35;
        const midY = (pos.y + next.y) / 2 + (cy - (pos.y + next.y) / 2) * 0.35;
        return (
          <path
            key={`arc-${i}`}
            d={`M ${pos.x} ${pos.y} Q ${midX} ${midY} ${next.x} ${next.y}`}
            fill="none" stroke={ARROW_COLOUR} strokeWidth={2} markerEnd="url(#cycle-arrow)"
          />
        );
      })}
      {positions.map((pos, i) => (
        <NodeBox key={i} x={pos.x - boxW / 2} y={pos.y - boxH / 2} w={boxW} h={boxH} label={nodes[i]} />
      ))}
    </svg>
  );
}

export function DiagramView({ spec }: { spec: TextbookDiagramSpec }) {
  if (!spec.nodes?.length) return null;
  return spec.diagram_type === "cycle"
    ? <CycleDiagram nodes={spec.nodes} />
    : <SequenceDiagram nodes={spec.nodes} />;
}
