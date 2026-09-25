# Skill: AI Generation

**Purpose:** Generate structured AI outputs (notes, quiz, bloom, missing concepts, experiments) from session OCR text. Defines the sequence, prompt construction, parsing, validation, and storage for each output type.

**Current status:** Placeholder path is active when `OPENAI_API_KEY` is not set. The placeholder returns synthetic but structurally correct JSON for all output types, letting the rest of the system (storage, dashboard, TiQer export) be fully tested without a live API key. All parser functions in `app/services/ai_service.py` are implemented and tested (41 unit tests).

---

## Trigger

Called after session OCR merge is complete. Invoked by:
- `POST /sessions/{id}/generate` with optional `{"outputs": ["notes","summary","quiz",...]}` body
- If `outputs` is omitted, all types are generated
- Currently runs as a FastAPI `BackgroundTask` (Celery in Phase 2)

**Output types (8 total):** `notes`, `summary`, `quiz`, `bloom`, `missing_concepts`, `experiments`, `analogies`, `homework`

---

## Pre-Generation Checks

Before calling any AI:
1. Verify `session.status == "completed"` and OCR is done
2. Load merged OCR text from `ocr_results`
3. Count tokens (estimate: `len(text) / 4`)
4. Apply context compaction if >4,000 tokens (see `context_compaction_skill.md`)
5. Load session context: subject, grade, board_type, classroom_memory

---

## Generation Sequence (order matters)

```
1. notes          → markdown structured notes
2. summary        → 3–5 sentence recap
3. quiz           → MCQ + T/F JSON array
4. bloom          → Bloom level distribution (uses quiz output)
5. missing_concepts → gaps vs memory + curriculum
6. experiments    → activity suggestions
7. visual_cards   → key concept cards (uses notes output)
```

Run steps 1–5 in parallel (they are independent except bloom depends on quiz).
Run bloom after quiz. Run visual_cards after notes.

---

## Prompt Construction Pattern

Every prompt follows this structure:
```python
def build_prompt(template: str, session: Session, ocr_text: str, **extras) -> dict:
    system = f"""You are an AI teaching assistant for Indian classrooms.
Subject: {session.subject}, Grade: {session.grade}.
Board type: {session.board_type}.
Output must be appropriate for {session.grade} students in India."""

    user = template.format(
        subject=session.subject,
        grade=session.grade,
        ocr_text=ocr_text,
        **extras
    )
    return {"system": system, "user": user}
```

---

## Output Type: Notes

**Model:** `gpt-4o`
**Prompt template:**
```
Board content from today's class:
{ocr_text}

Generate structured study notes with:
- A clear title (the main topic)
- Section headings for subtopics
- Key concepts as bullet points
- All formulas preserved exactly as written
- Language appropriate for {grade}
Format as markdown.
```

**Parse:** Return raw markdown. Store in `ai_outputs.content_json.markdown`.

**Validation:**
- Must contain at least one `#` heading
- Must be >100 characters
- Must not contain "I cannot" or "I don't have enough" (AI refusal detection)

---

## Output Type: Summary

**Model:** `gpt-4o-mini` (short output, fast)
**Prompt template:**
```
Board content:
{ocr_text}

Write a 3–5 sentence summary a student can use to recall what was taught today in {subject} class.
Keep language simple for {grade}.
```

**Parse:** Return plain text. Store in `ai_outputs.content_json.text`.

---

## Output Type: Quiz

**Model:** `gpt-4o`
**Prompt template:**
```
Board content:
{ocr_text}

Generate a quiz with exactly:
- 5 MCQ questions (4 options each)
- 3 True/False questions

For each question provide:
- type: "mcq" or "true_false"
- text: question text
- options: array of 4 strings (MCQ only)
- correct: index 0–3 (MCQ) or true/false (T/F)
- bloom_level: one of [remember, understand, apply, analyze, evaluate, create]
- topic: the specific topic this question covers

Return ONLY a valid JSON array. No explanation text.
```

**Parse:**
```python
def parse_quiz(raw: str) -> list:
    # Strip markdown code fences if present
    raw = re.sub(r'```json|```', '', raw).strip()
    questions = json.loads(raw)
    # Validate schema
    for q in questions:
        assert q["type"] in ("mcq", "true_false")
        assert "bloom_level" in q
        if q["type"] == "mcq":
            assert len(q["options"]) == 4
            assert isinstance(q["correct"], int)
    return questions
```

**On parse failure:** Retry once with stricter prompt ("Return ONLY raw JSON, no markdown wrapping"). On second failure, store raw text and mark `status=partial`.

**Storage:** Insert each question as a row in `quiz_questions` table.

---

## Output Type: Bloom Analysis

**Model:** `gpt-4o`
**Input:** Quiz questions JSON (from previous step)
**Prompt template:**
```
Quiz questions (JSON):
{quiz_json}

Analyse Bloom's Taxonomy coverage:
1. Count questions per level: remember, understand, apply, analyze, evaluate, create
2. Flag if lower-order (remember + understand) > 60% of total questions
3. If coverage is shallow, suggest 2 higher-order questions

Return JSON:
{
  "counts": {"remember": 0, "understand": 0, ...},
  "lower_order_dominant": true/false,
  "suggestions": ["...", "..."]
}
```

**Parse:** JSON parse, validate all 6 bloom keys present.

---

## Output Type: Missing Concepts

**Model:** `gpt-4o`
**Input:** OCR text + classroom memory topics
**Prompt template:**
```
Topics taught today:
{topics_from_notes}

Previous sessions' topics (last 3 sessions):
{memory_topics}

Subject: {subject}, Grade: {grade}

Identify:
1. Prerequisite concepts that were assumed but not explained today
2. Topics mentioned but not fully covered
3. The recommended next topic for the next class

Return JSON:
{
  "prerequisite_gaps": ["..."],
  "incomplete_topics": ["..."],
  "suggested_next": "..."
}
```

---

## Output Type: Experiments

**Model:** `gpt-4o-mini`
**Prompt template:**
```
Topics taught: {topics_list}
Subject: {subject}, Grade: {grade}

Suggest 3 hands-on classroom activities or experiments that reinforce today's concepts.
Assume: no electricity required, materials available in Indian government schools.
If any topic maps to an Xperimentor kit, mention it.

Return JSON:
[{
  "title": "...",
  "description": "...",
  "materials": ["..."],
  "xperimentor_kit": "Kit name or null"
}]
```

---

## Post-Generation Actions

After all outputs are stored:
1. Update `classroom_memory` for the teacher (topics + pending concepts)
2. If TiQer auto-export is enabled for this classroom: call TiQer API
3. Push notification to teacher: "Your class notes are ready"
4. Update `session.status = "ai_complete"`

---

## Error Handling Summary

| Error | Action |
|---|---|
| OpenAI timeout | Retry up to 3x, then mark output `failed` |
| JSON parse failure | Retry with stricter prompt once, then `partial` |
| Refusal detected | Log, mark `failed`, do not retry |
| Rate limit (429) | Delay 60s, re-queue |
| Context too long | Compact (see context_compaction_skill.md), retry |
| All outputs failed | Surface error to teacher dashboard |
