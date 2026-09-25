# ACI – AI Pipeline

---

## Overview

The AI pipeline takes the merged OCR text from a session and generates multiple structured outputs. All AI calls go through OpenAI APIs (GPT-4o for MVP). Processing is async via Celery workers.

---

## Processing Phases

### Phase 1 – OCR + Basic AI (MVP)
```
Merged OCR Text → GPT-4o → Notes, Summary, Quiz, Bloom Tags
```

### Phase 2 – Teacher Intelligence
```
+ Session history → Missing Concept Detection
+ Curriculum map → Bloom gap analysis
+ TiQer export → One-click engagement
+ Xperimentor map → Experiment suggestions
```

### Phase 3 – Vision AI
```
+ Frame images → GPT-4o Vision → Diagram understanding
+ Multi-frame → Classroom replay, board progression
+ Historical patterns → Confusion prediction engine
```

---

## Output Types

| Output | Model | Input | Description |
|---|---|---|---|
| `notes` | GPT-4o | OCR text | Structured teaching notes (headings, bullets, formulas) |
| `summary` | GPT-4o | OCR text | 3–5 sentence class recap |
| `quiz` | GPT-4o | OCR text | MCQ + T/F, bloom-tagged |
| `bloom` | GPT-4o | OCR text + quiz | Bloom level distribution + gap alerts |
| `missing_concepts` | GPT-4o | OCR text + memory | Topics implied but not covered |
| `experiments` | GPT-4o | OCR text | Hands-on activity + Xperimentor kit suggestions |
| `visual_cards` | GPT-4o | Summary | Key-concept cards for visual revision |
| `simplified` | GPT-4o | Notes | Grade-appropriate simplified explanation |
| `analogies` | GPT-4o | Notes | Real-life analogies for abstract concepts |

---

## Prompt Templates

### Notes Generation
```
System: You are an AI teaching assistant converting classroom board content into structured study notes.
User:
Subject: {subject}, Grade: {grade}
Board content (OCR extracted):
{merged_ocr_text}

Generate structured notes with:
- Clear headings
- Key concepts as bullet points
- Formulas preserved exactly as written
- Simple language appropriate for {grade} students
Output as markdown.
```

---

### Summary Generation
```
System: You are an AI teaching assistant creating class recap summaries.
User:
Subject: {subject}, Grade: {grade}
Board content:
{merged_ocr_text}

Write a 3–5 sentence summary a student can use to recall what was taught today.
```

---

### Quiz Generation
```
System: You are an AI quiz generator for classroom assessments.
User:
Subject: {subject}, Grade: {grade}
Board content:
{merged_ocr_text}

Generate:
- 5 MCQ questions (4 options each, mark correct answer)
- 3 True/False questions
- Tag each question with Bloom's level: remember | understand | apply | analyze | evaluate | create
- Tag each question with the topic it covers

Output as JSON array matching this schema:
[{
  "type": "mcq",
  "text": "...",
  "options": ["A","B","C","D"],
  "correct": 0,
  "bloom_level": "understand",
  "topic": "..."
}]
```

---

### Bloom Analysis
```
System: You are a pedagogy analyst reviewing classroom questions for Bloom's Taxonomy coverage.
User:
Subject: {subject}, Grade: {grade}
Quiz questions (JSON): {quiz_json}

Provide:
1. Count of questions per Bloom level
2. Whether lower-order (remember/understand) dominates
3. Suggest 2 higher-order questions if Bloom coverage is shallow
Output as JSON.
```

---

### Missing Concept Detection
```
System: You are a curriculum gap analyser.
User:
Subject: {subject}, Grade: {grade}
Topics covered in class today: {topics_list}
Previous sessions' topics: {memory_topics}
Standard curriculum topics for this grade/subject: {curriculum_hint}

Identify:
1. Prerequisite concepts that were assumed but not covered
2. Concepts mentioned but not explained
3. Suggested next topics
Output as JSON.
```

---

### Experiment Suggestions
```
System: You are an experiential learning advisor for classroom teachers.
User:
Subject: {subject}, Grade: {grade}
Topics covered: {topics_list}

Suggest:
1. 2–3 hands-on classroom experiments or activities
2. Any relevant Xperimentor kit that matches (if applicable)
3. Real-life demonstration ideas
Keep suggestions feasible for low-resource classrooms.
Output as JSON.
```

---

## Model Routing Logic

| Task | Model | Reason |
|---|---|---|
| Notes, summary, analogies | GPT-4o | High quality text generation |
| Quiz generation | GPT-4o | Structured JSON output reliability |
| Bloom analysis | GPT-4o | Reasoning task |
| Missing concept detection | GPT-4o | Reasoning + curriculum awareness |
| Simplified explanation | GPT-4o | Rewrite quality |
| Diagram understanding (Phase 3) | GPT-4o Vision | Multimodal |
| Simple one-liner summaries | GPT-4o-mini | Cost optimization |

Route to `gpt-4o-mini` for tasks where output is <100 words or is purely extractive.

---

## Processing Flow (Celery)

```
POST /sessions/{id}/generate
    │
    ▼
Celery task: ai_generation_job(session_id, outputs=[...])
    │
    ├── fetch merged OCR text from DB
    ├── for each requested output_type:
    │       ├── load prompt template
    │       ├── fill template with session context
    │       ├── call OpenAI API
    │       ├── parse + validate response
    │       ├── store in ai_outputs table
    │       └── update status = 'ready'
    │
    └── trigger: classroom memory update
                 TiQer export (if enabled)
                 notification to teacher
```

---

## Error Handling

| Failure | Action |
|---|---|
| OpenAI timeout | Retry up to 3x with 10s backoff |
| Invalid JSON response | Retry with stricter prompt; fallback to raw text |
| Rate limit (429) | Queue with 60s delay |
| Context too long | Truncate OCR text to last 4000 tokens; note truncation in output |
| Completely unreadable OCR | Skip AI generation; surface "low quality session" warning |

---

## Token Budget (per session)

| Output | Estimated Tokens (input+output) |
|---|---|
| Notes | ~2,000 |
| Summary | ~800 |
| Quiz (8 questions) | ~1,500 |
| Bloom analysis | ~600 |
| Missing concepts | ~1,200 |
| Experiments | ~800 |
| **Total per session** | **~7,000** |

At GPT-4o pricing (~$5/1M tokens), cost per session ≈ **$0.035** (3.5 paise equivalent per session).

---

## Classroom Memory Engine

After each session's AI generation completes:
1. Extract topics covered (from notes headings)
2. Merge with existing `classroom_memory` for that teacher
3. Update `pending_concepts` by removing covered topics
4. Update `suggested_next` using missing concept output
5. Store `last_session_id`

Used by the "Continue My Class" assistant before the next session.

---

## Teacher-Facing AI Features (MVP)

| Feature | Trigger | Output |
|---|---|---|
| AI Notes | Auto after session | Markdown notes |
| Session Recap | Auto after session | 3–5 sentence summary |
| Quiz Generator | Auto + editable | MCQ + T/F JSON |
| Bloom Report | Auto | Level distribution |
| Missing Concepts | Auto | Concept list |
| Experiment Suggestions | Auto | Activity list |
| Explain Simpler | Teacher request | Rewritten explanation |
| Analogy Generator | Teacher request | Real-life examples |
| Continue My Class | Before next session | Recap + next step |
