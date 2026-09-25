# Skill: Context Compaction

**Purpose:** Manage and compact context when processing large classroom sessions. A single session can produce 40–80 OCR'd frames totalling thousands of tokens. This skill defines how to reduce context size without losing essential content before sending to the AI pipeline.

---

## When to Apply

- Session OCR text exceeds 4,000 tokens
- Multiple sessions being processed in a batch
- Classroom memory engine reading multi-week history
- Dashboard generating reports over long date ranges

---

## Compaction Strategy

### Step 1: Deduplicate Repeated Content
Board content is often repeated across frames (teacher doesn't erase for 10 minutes). Remove near-duplicate text blocks before concatenating frames.

```python
def deduplicate_frames(frame_texts: list[str]) -> list[str]:
    seen = []
    for text in frame_texts:
        if not any(similarity(text, s) > 0.85 for s in seen):
            seen.append(text)
    return seen
```

Use difflib `SequenceMatcher` ratio for similarity. Threshold: 0.85.

---

### Step 2: Extract Key Structures First
Before sending raw OCR to the AI, extract high-signal regions:
- Headings (typically larger font, standalone lines, possibly underlined)
- Formulas (lines containing `=`, `+`, `×`, `÷`, `∫`, `Σ`)
- Numbered/bulleted lists

Prioritise these in the context window. Body text is lower priority.

---

### Step 3: Token Budget Enforcement

| Output Type | Max Input Tokens |
|---|---|
| Notes generation | 4,000 |
| Summary | 2,000 |
| Quiz generation | 3,000 |
| Bloom analysis | 2,500 |
| Missing concepts | 3,500 |

If OCR text exceeds the budget for a given output type:
1. Trim from the middle of the text (preserve first and last sections — teachers often write the topic at the top and conclusions at the bottom)
2. Add a system note: `[Content truncated: X tokens omitted from middle of session]`
3. Log the truncation in `ai_outputs` metadata

---

### Step 4: Session History Compaction (Classroom Memory)

When building the classroom memory context for "Continue My Class":
- Keep last 3 sessions' topic lists (not full text)
- Keep only `pending_concepts` list from memory engine (not full session notes)
- Do NOT pass full previous session notes to the next session prompt

```python
memory_context = f"""
Previous sessions (last 3):
{format_topic_list(last_3_sessions)}

Concepts still pending:
{format_concept_list(pending_concepts)}
"""
```

This keeps memory context under 500 tokens regardless of history length.

---

## Output Preservation Rules

Never compact away:
- Subject name and grade (always in system prompt)
- First heading in the session (establishes the topic)
- Any formula or equation
- Last paragraph (often contains summary or homework)

Always compact away:
- Repeated identical text blocks
- OCR noise fragments (<3 words, no sentence structure)
- Whitespace-only regions

---

## Monitoring

Log to `ai_outputs.content_json.metadata`:
```json
{
  "original_tokens": 6200,
  "sent_tokens": 3950,
  "truncated": true,
  "dedup_frames_removed": 12
}
```
