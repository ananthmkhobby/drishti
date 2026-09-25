# Skill: Model Routing

**Purpose:** Route each AI generation task to the appropriate model based on output quality requirements, output length, and cost budget.

---

## Model Options

| Model | Use Case | Cost (approx) | Speed |
|---|---|---|---|
| `gpt-4o` | Complex reasoning, structured JSON, long-form text | ~$5/1M tokens | Medium |
| `gpt-4o-mini` | Short summaries, simple extraction, one-liners | ~$0.15/1M tokens | Fast |
| `gpt-4o` (vision) | Diagram understanding, board image analysis (Phase 3) | ~$5/1M tokens + image | Slow |

---

## Routing Rules

### Route to `gpt-4o`
- Quiz generation (requires reliable structured JSON + reasoning)
- Bloom analysis (requires pedagogy reasoning)
- Missing concept detection (requires curriculum reasoning)
- Notes generation for sessions >10 frames (quality matters)
- Simplified explanation (requires coherent rewrite)
- Analogy generation (requires creative, contextual output)
- Any task where output will be shown directly to teachers

### Route to `gpt-4o-mini`
- One-sentence session tag / label generation
- Subject/topic extraction from short OCR text (<500 tokens)
- Quick recap for "Continue My Class" when context is simple
- Experiment suggestion pre-filtering (narrow down a large list)
- Any batch task processing >20 sessions simultaneously

### Route to `gpt-4o` (vision) — Phase 3 only
- Diagram classification from board frames
- Classroom replay generation
- Board progression summarisation from image sequence

---

## Routing Function

```python
def route_model(task: str, token_count: int, batch_size: int = 1) -> str:
    HIGH_QUALITY_TASKS = {
        "quiz", "bloom", "missing_concepts", "notes",
        "simplified", "analogies", "experiments"
    }
    MINI_TASKS = {
        "topic_tag", "quick_recap", "subject_extract"
    }

    if task in MINI_TASKS:
        return "gpt-4o-mini"

    if task in HIGH_QUALITY_TASKS:
        # Cost optimisation: use mini for very short sessions
        if token_count < 500 and task in {"notes", "quick_recap"}:
            return "gpt-4o-mini"
        return "gpt-4o"

    # Default: use gpt-4o for safety
    return "gpt-4o"
```

---

## Fallback on API Failure

If `gpt-4o` returns an error (5xx, rate limit):
1. Wait 10s, retry `gpt-4o` up to 2 times
2. On 3rd failure, if task allows quality degradation: retry with `gpt-4o-mini`
3. If `gpt-4o-mini` also fails: mark output as `failed`, surface to teacher dashboard

Tasks that must NOT fall back to `gpt-4o-mini` (quality too important):
- `quiz` (MCQ answer correctness)
- `bloom` (pedagogy classification accuracy)
- `missing_concepts` (curriculum reasoning)

---

## Cost Guardrails

Per-session cost cap: **$0.10 USD**
If estimated cost exceeds cap (very long sessions, many outputs):
1. Prioritise: notes → summary → quiz → bloom → rest
2. Skip lower-priority outputs, mark them as `skipped_cost_cap`
3. Log warning; teacher can manually trigger skipped outputs later

Monthly school-level cost alert: if a school exceeds $50/month, trigger review.

---

## Logging

Every AI call logs to `ai_outputs.content_json.metadata`:
```json
{
  "model": "gpt-4o",
  "prompt_tokens": 1200,
  "completion_tokens": 450,
  "total_tokens": 1650,
  "cost_usd": 0.0083,
  "routing_reason": "quiz_task_high_quality"
}
```
