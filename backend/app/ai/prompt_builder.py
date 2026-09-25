"""
Prompt builder for ACI AI generation pipeline.

Each builder returns a PromptPair(system, user) ready for the OpenAI
chat-completions API.  All prompts are crafted for Indian classrooms and
are grade/subject-aware.
"""
from __future__ import annotations

from dataclasses import dataclass

BLOOM_LEVELS = "remember | understand | apply | analyze | evaluate | create"
_STRICT_PREFIX = (
    "CRITICAL: Return ONLY raw JSON. No markdown code fences. "
    "No preamble. No explanation after the JSON.\n\n"
)


@dataclass
class PromptPair:
    system: str
    user: str


# ---------------------------------------------------------------------------
# Shared base system messages
# ---------------------------------------------------------------------------

def _system(subject: str, grade: str, board_type: str) -> str:
    return (
        f"You are an AI teaching assistant for Indian classrooms. "
        f"Subject: {subject}. Grade: {grade}. Board type: {board_type}. "
        f"All output must be appropriate and curriculum-aligned for "
        f"{grade} students in India.\n\n"
        f"Use the board content (OCR text) to identify WHAT was taught — "
        f"the topic, keywords, formulas, and concepts written on the board. "
        f"Then generate helpful, complete educational content on those topics, "
        f"using your knowledge of the {grade} curriculum. "
        f"Always produce useful, actionable content — even when OCR is sparse, "
        f"use the detected topic as the starting point and expand appropriately."
    )


def _system_curriculum(subject: str, grade: str, board_type: str) -> str:
    return (
        f"You are an AI Educational Mind Map and Curriculum Coverage Analyzer for "
        f"Indian classrooms. Subject: {subject}. Grade: {grade}. Board: {board_type}.\n\n"
        f"You are an expert instructional designer and curriculum auditor. "
        f"Think like a curriculum architect: reconstruct the COMPLETE expected topic tree "
        f"even if partially taught, infer prerequisite dependencies, evaluate conceptual "
        f"progression, and identify hidden pedagogical gaps. "
        f"Use semantic understanding — do not merely summarize OCR text. "
        f"Always produce curriculum-aligned output suitable for {grade} students in India."
    )


def _system_gap(subject: str, grade: str, board_type: str) -> str:
    return (
        f"You are an advanced AI Pedagogical Intelligence Agent for Indian classrooms. "
        f"Subject: {subject}. Grade: {grade}. Board: {board_type}.\n\n"
        f"You analyze classroom teaching sessions for deep pedagogical gap analysis. "
        f"Think like an expert instructional designer, curriculum auditor, and learning scientist. "
        f"Use educational standards, curriculum alignment, concept dependency mapping, "
        f"Bloom's Taxonomy, and instructional quality frameworks. "
        f"Do not merely summarize — infer pedagogical intent, evaluate conceptual progression, "
        f"identify hidden instructional weaknesses, and prioritize learner understanding. "
        f"Be specific, evidence-based, and actionable."
    )


# ---------------------------------------------------------------------------
# Notes  (Curriculum Intelligence: mind map + study notes + coverage analysis)
# ---------------------------------------------------------------------------

def build_notes_prompt(
    ocr_text: str,
    subject: str,
    grade: str,
    board_type: str,
    topic: str = "",
) -> PromptPair:
    topic_hint = f"The main topic of today's class is: {topic}.\n\n" if topic else ""
    user = (
        f"CRITICAL: Return ONLY raw JSON. No markdown fences. No preamble.\n\n"
        f"{topic_hint}"
        f"Board content from today's class (OCR extracted):\n"
        f"---\n{ocr_text}\n---\n\n"
        f"Generate a complete Curriculum Intelligence report for {grade} students.\n\n"
        f"TASKS:\n"
        f"1. Generate comprehensive, structured study notes in markdown (min 300 words).\n"
        f"   FORMATTING RULES — follow exactly:\n"
        f"   - Start with a single '# heading' naming the topic, then a brief 2-sentence introduction\n"
        f"   - Use ## for main sections: Introduction, Key Concepts, Definitions, Important Rules/Formulas, Worked Examples, Quick Revision\n"
        f"   - Use ### for sub-sections within each\n"
        f"   - Use **bold** for ALL key terms, formulas, laws, and important words\n"
        f"   - Use bullet points (- item) for lists of facts, properties, characteristics\n"
        f"   - Use numbered lists (1. step) for sequences, processes, and procedures\n"
        f"   - Use > prefix for important rules, laws, formulas, and definitions (these render as callout boxes)\n"
        f"   - Add a '## Key Terms' section with one-line definitions for every new term introduced\n"
        f"   - End with a '## Quick Revision' section: 5–7 concise bullet points students can use to revise fast\n"
        f"   - Write in simple, clear language suitable for {grade} students\n"
        f"   - Include at least one worked example if the topic involves calculation or application\n"
        f"2. Build a full topic mind map using visual indicators:\n"
        f"   🟢 Fully Covered | 🟡 Partially Covered | 🔴 Not Covered | "
        f"⚪ Mentioned Briefly | 🔵 Prerequisite Missing\n"
        f"   Reconstruct the COMPLETE expected topic tree — include missing branches.\n"
        f"3. Classify every concept: covered / partial / missing.\n"
        f"4. Identify prerequisites assumed but not explicitly taught.\n"
        f"5. Map to {grade} CBSE/ICSE curriculum. Estimate syllabus coverage %.\n"
        f"6. Analyse Bloom's Taxonomy levels present in the teaching.\n"
        f"7. Assign a Teaching Completeness Score (0–10).\n"
        f"8. Generate 1-3 visual diagrams where they add learning value.\n"
        f"   Supported diagram types:\n"
        f"   - 'flowchart': linear process or cause-effect chain (steps array, max 6 steps)\n"
        f"   - 'cycle': closed loop / recurring process (nodes array, 3-6 nodes)\n"
        f"   - 'concept_map': central idea with branches (center + branches array)\n"
        f"   - 'comparison': side-by-side (title + left_label/right_label + left_items/right_items)\n"
        f"   Only add diagrams if they genuinely help understand the topic.\n\n"
        f"Return ONLY this exact JSON structure:\n"
        f'{{\n'
        f'  "markdown": "# Topic Title\\n\\n## Key Concepts\\n\\n...full study notes min 200 words...",\n'
        f'  "mind_map": "TopicName\\n├── 🟢 Concept\\n│   ├── 🟢 Subtopic\\n│   └── 🔴 Missing\\n└── 🟡 Partial",\n'
        f'  "session_summary": "2-3 sentence summary of what was taught today",\n'
        f'  "topic_detected": "Main Topic Name",\n'
        f'  "diagrams": [\n'
        f'    {{"type":"flowchart","title":"Process Name","steps":["Step 1","Step 2","Step 3"]}},\n'
        f'    {{"type":"cycle","title":"Cycle Name","nodes":["Stage A","Stage B","Stage C","Stage D"]}},\n'
        f'    {{"type":"concept_map","title":"Topic","center":"Central Concept","branches":["Branch 1","Branch 2","Branch 3"]}},\n'
        f'    {{"type":"comparison","title":"A vs B","left_label":"A","right_label":"B","left_items":["item1","item2"],"right_items":["item1","item2"]}}\n'
        f'  ],\n'
        f'  "covered_concepts": [{{"concept":"...","depth":"strong|medium|weak","bloom_level":"remember|understand|apply|analyze|evaluate|create"}}],\n'
        f'  "partially_covered_concepts": [{{"concept":"...","what_missing":"..."}}],\n'
        f'  "missing_concepts": ["concept not taught but expected"],\n'
        f'  "missing_prerequisites": ["prerequisite assumed but not taught"],\n'
        f'  "curriculum_coverage": {{"syllabus_coverage_pct":70,"missing_learning_objectives":["..."]}},\n'
        f'  "bloom_distribution": {{"remember":3,"understand":2,"apply":1,"analyze":0,"evaluate":0,"create":0}},\n'
        f'  "teaching_completeness_score": 7.5,\n'
        f'  "recommended_next_topics": ["next topic to teach"],\n'
        f'  "suggested_exercises": ["exercise for students"]\n'
        f'}}'
    )
    return PromptPair(system=_system_curriculum(subject, grade, board_type), user=user)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def build_summary_prompt(
    ocr_text: str,
    subject: str,
    grade: str,
    board_type: str,
) -> PromptPair:
    user = (
        f"Board content from today's {subject} class:\n"
        f"---\n{ocr_text}\n---\n\n"
        f"Write a 3–5 sentence summary that a {grade} student can use to "
        f"recall what was taught today.\n"
        f"Use simple, direct language. Write as flowing prose — no bullet points."
    )
    return PromptPair(system=_system(subject, grade, board_type), user=user)


# ---------------------------------------------------------------------------
# Quiz (MCQ + T/F)
# ---------------------------------------------------------------------------

def build_quiz_prompt(
    ocr_text: str,
    subject: str,
    grade: str,
    board_type: str,
    strict: bool = False,
) -> PromptPair:
    prefix = _STRICT_PREFIX if strict else ""
    user = (
        f"{prefix}"
        f"Board content:\n---\n{ocr_text}\n---\n\n"
        f"Generate a quiz using the concepts and facts visible in the board content above. "
        f"Questions should be based on what was written on the board. "
        f"You may use general subject knowledge to add plausible wrong options "
        f"but questions must test what was on the board.\n\n"
        f"Generate as many questions as the content supports:\n"
        f"- 3–5 MCQ questions (4 options each) — fewer if content is sparse\n"
        f"- 1–3 True/False questions — fewer if content is sparse\n"
        f"If the content only supports 1–2 questions, that is fine — generate what you can.\n\n"
        f"For EVERY question include these fields:\n"
        f'  "type"        : "mcq" or "true_false"\n'
        f'  "text"        : question string\n'
        f'  "options"     : array of exactly 4 strings (MCQ only; omit for true_false)\n'
        f'  "correct"     : integer 0–3 for MCQ; boolean true/false for T/F\n'
        f'  "bloom_level" : one of [{BLOOM_LEVELS}]\n'
        f'  "topic"       : specific topic this question covers\n'
        f'  "skill_tag"   : one keyword describing the cognitive skill '
        f'(e.g. "recall", "calculation", "inference")\n\n'
        f"Return ONLY a valid JSON array. No explanation text. No markdown.\n"
        f"If you truly cannot generate any question from the content, return []."
    )
    return PromptPair(system=_system(subject, grade, board_type), user=user)


# ---------------------------------------------------------------------------
# Bloom analysis (depends on quiz)
# ---------------------------------------------------------------------------

def build_bloom_prompt(
    quiz_json: str,
    subject: str,
    grade: str,
    board_type: str,
) -> PromptPair:
    user = (
        f"Quiz questions (JSON):\n{quiz_json}\n\n"
        f"Analyse Bloom's Taxonomy coverage:\n"
        f"1. Count questions at each level: "
        f"remember, understand, apply, analyze, evaluate, create\n"
        f'2. Set "lower_order_dominant": true '
        f"if (remember + understand) > 60 % of total questions\n"
        f"3. Suggest exactly 2 higher-order questions (strings) if coverage is shallow\n\n"
        f"Return ONLY this exact JSON structure (no extra keys):\n"
        f'{{"counts":{{"remember":0,"understand":0,"apply":0,'
        f'"analyze":0,"evaluate":0,"create":0}},'
        f'"lower_order_dominant":false,"suggestions":["...","..."]}}'
    )
    return PromptPair(system=_system(subject, grade, board_type), user=user)


# ---------------------------------------------------------------------------
# Pedagogical Gap Analysis  (deep 8-step framework)
# ---------------------------------------------------------------------------

def build_missing_concepts_prompt(
    topics_from_notes: str,
    memory_topics: str,
    subject: str,
    grade: str,
    board_type: str,
    strict: bool = False,
) -> PromptPair:
    prefix = _STRICT_PREFIX if strict else ""
    user = (
        f"{prefix}"
        f"CRITICAL: Return ONLY raw JSON. No markdown fences. No preamble.\n\n"
        f"Topics taught in today's class:\n{topics_from_notes}\n\n"
        f"Topics covered in previous sessions (last 3 sessions):\n"
        f"{memory_topics or 'None recorded yet'}\n\n"
        f"Subject: {subject}, Grade: {grade}\n\n"
        f"Perform a comprehensive Pedagogical Gap Analysis using this 8-step framework:\n\n"
        f"STEP 1 – Content Understanding: extract main topic, subtopics, key concepts, formulas, examples.\n"
        f"STEP 2 – Curriculum Alignment: map to CBSE/ICSE {grade} curriculum. "
        f"Identify expected competencies, learning outcomes, and prerequisite concepts.\n"
        f"STEP 3 – Gap Analysis:\n"
        f"  A. Conceptual gaps (concepts without prerequisites, disconnected ideas)\n"
        f"  B. Sequencing gaps (wrong progression, abrupt jumps, advanced before basics)\n"
        f"  C. Reinforcement gaps (no examples, exercises, recap, repetition)\n"
        f"  D. Assessment gaps (no comprehension checks, no formative assessment)\n"
        f"  E. Cognitive depth gaps (over-reliance on recall vs higher-order thinking)\n"
        f"  F. Learner accessibility gaps (abstract explanations, missing scaffolding, cognitive overload)\n"
        f"STEP 4 – Knowledge Graph: identify prerequisite dependency breaks.\n"
        f"STEP 5 – Classroom Metrics: score concept density, explanation depth, example density, "
        f"assessment density, curriculum alignment (0-10 each).\n"
        f"STEP 6 – Student Risk Analysis: predict likely confusion areas, misconceptions, "
        f"cognitive load regions.\n"
        f"STEP 7 – Recommendations: specific remediation, next lesson plan, activities.\n\n"
        f"Return ONLY this exact JSON (no extra text or keys):\n"
        f'{{\n'
        f'  "session_summary": "2-3 sentence overview of the teaching session",\n'
        f'  "topics_detected": ["main topics taught"],\n'
        f'  "concepts_covered": ["list of concepts explicitly taught"],\n'
        f'  "pedagogical_gaps": {{\n'
        f'    "conceptual_gaps": ["specific gap 1", "..."],\n'
        f'    "sequencing_gaps": ["sequencing issue 1", "..."],\n'
        f'    "reinforcement_gaps": ["reinforcement issue 1", "..."],\n'
        f'    "assessment_gaps": ["assessment issue 1", "..."],\n'
        f'    "cognitive_depth_gaps": ["depth issue 1", "..."],\n'
        f'    "accessibility_gaps": ["accessibility issue 1", "..."]\n'
        f'  }},\n'
        f'  "bloom_analysis": {{\n'
        f'    "distribution": {{"remember":0,"understand":0,"apply":0,"analyze":0,"evaluate":0,"create":0}},\n'
        f'    "dominant_level": "remember",\n'
        f'    "higher_order_missing": true\n'
        f'  }},\n'
        f'  "classroom_metrics": {{\n'
        f'    "concept_density": "medium",\n'
        f'    "explanation_depth": "medium",\n'
        f'    "example_density": "low",\n'
        f'    "assessment_density": "none",\n'
        f'    "curriculum_alignment_score": 7,\n'
        f'    "instructional_balance_score": 5,\n'
        f'    "progression_coherence_score": 6,\n'
        f'    "learner_readiness_score": 5\n'
        f'  }},\n'
        f'  "student_risk_areas": [{{"concept":"concept name","risk_level":"high|medium|low","reason":"why students will struggle"}}],\n'
        f'  "missing_prerequisites": ["prerequisite concept not taught"],\n'
        f'  "instructional_weaknesses": ["specific teaching weakness"],\n'
        f'  "recommended_interventions": ["specific actionable recommendation"],\n'
        f'  "suggested_next_steps": ["specific next step for teacher"],\n'
        f'  "remediation_plan": "Brief 2-3 sentence plan for the next class",\n'
        f'  "teaching_effectiveness_score": 6.5,\n'
        f'  "prerequisite_gaps": ["prerequisite concept missing"],\n'
        f'  "incomplete_topics": ["topic that was not fully covered"],\n'
        f'  "suggested_next": "The single best next topic to cover in next class"\n'
        f'}}'
    )
    return PromptPair(system=_system_gap(subject, grade, board_type), user=user)


# ---------------------------------------------------------------------------
# Lesson Plan — topic extraction from raw text
# ---------------------------------------------------------------------------

def build_topic_extraction_prompt(raw_text: str) -> PromptPair:
    system = (
        "You are an expert curriculum analyst. Extract a clean, structured list of teaching "
        "topics from the provided lesson plan text. Each topic should be a concise noun phrase "
        "(2-8 words). Remove duplicates and administrative details. Return ONLY a JSON array of strings."
    )
    user = (
        f"Extract all teaching topics from this lesson plan. Return a JSON array of topic strings.\n\n"
        f"Lesson plan text:\n{raw_text[:4000]}\n\n"
        f'Example output: ["Newton\'s First Law", "Inertia", "Force and Mass relationship", "Friction types"]'
    )
    return PromptPair(system=system, user=user)


# ---------------------------------------------------------------------------
# Lesson Plan — coverage analysis
# ---------------------------------------------------------------------------

def build_lesson_plan_coverage_prompt(
    lesson_topics: list[str],
    session_ocr_text: str,
    subject: str,
    grade: str,
    audio_transcript: str = "",
    strict: bool = False,
) -> PromptPair:
    prefix = _STRICT_PREFIX if strict else ""
    has_audio = bool(audio_transcript and audio_transcript.strip())
    system = (
        f"You are an expert curriculum analyst for Indian {grade} {subject} classrooms. "
        f"You compare what a teacher PLANNED to teach (lesson plan topics) against what was "
        f"ACTUALLY covered — using board OCR text{' AND the teacher audio transcript' if has_audio else ''}. "
        f"Use semantic matching — 'Newton's Third Law' matches 'action-reaction pairs'. "
        f"A topic counts as covered if there is evidence in EITHER the board text OR the audio. "
        f"Return ONLY valid JSON."
    )
    topics_json = str(lesson_topics)
    audio_section = (
        f"TEACHER AUDIO TRANSCRIPT (what the teacher said during class):\n"
        f"{audio_transcript[:4000]}\n\n"
        if has_audio else
        "AUDIO: Not available — base analysis on board OCR only.\n\n"
    )
    user = (
        f"{prefix}"
        f"LESSON PLAN TOPICS (what teacher planned to cover):\n{topics_json}\n\n"
        f"BOARD OCR TEXT (what was written on the board during class):\n"
        f"{session_ocr_text[:4000]}\n\n"
        f"{audio_section}"
        f"Analyse coverage and return this exact JSON structure:\n"
        f'{{\n'
        f'  "lesson_plan_topics": {topics_json},\n'
        f'  "covered": [{{"topic": "topic name", "evidence": "exact or paraphrased text from board or audio"}}],\n'
        f'  "partial": [{{"topic": "topic name", "covered_aspect": "what was covered", "missing_aspect": "what was skipped"}}],\n'
        f'  "missing": ["topic not found in board or audio at all"],\n'
        f'  "teaching_notes": [{{"topic": "missing topic", "note": "Brief teaching note: key points to cover, suggested approach, common misconceptions to address, prerequisite links"}}],\n'
        f'  "coverage_score": 72,\n'
        f'  "summary": "2-3 sentence overview of what was covered vs planned",\n'
        f'  "suggestions": "Specific actionable advice for the next class to address gaps"\n'
        f'}}'
    )
    return PromptPair(system=system, user=user)


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------

def build_experiments_prompt(
    topics_list: str,
    subject: str,
    grade: str,
    board_type: str,
    strict: bool = False,
) -> PromptPair:
    prefix = _STRICT_PREFIX if strict else ""
    user = (
        f"{prefix}"
        f"Topics taught: {topics_list}\n"
        f"Subject: {subject}, Grade: {grade}\n\n"
        f"Suggest exactly 3 hands-on classroom activities / experiments "
        f"that reinforce today's concepts.\n"
        f"Constraints:\n"
        f"- No electricity required\n"
        f"- Materials available in Indian government schools or households\n"
        f"- Safe for {grade} students\n"
        f"- If any topic maps to an Xperimentor kit, name the kit\n\n"
        f"Return ONLY a JSON array:\n"
        f'[{{"title":"...","topic":"...","difficulty":"easy|medium|hard",'
        f'"description":"...","materials":["..."],"steps":["..."],'
        f'"expected_outcome":"...","safety_note":"...","xperimentor_kit":null}}]'
    )
    return PromptPair(system=_system(subject, grade, board_type), user=user)


# ---------------------------------------------------------------------------
# Visual cards (depends on notes)
# ---------------------------------------------------------------------------

def build_visual_cards_prompt(
    notes_markdown: str,
    subject: str,
    grade: str,
    board_type: str,
    strict: bool = False,
) -> PromptPair:
    prefix = _STRICT_PREFIX if strict else ""
    user = (
        f"{prefix}"
        f"Study notes (markdown):\n---\n{notes_markdown}\n---\n\n"
        f"Extract 5–8 key concept flash cards for visual revision.\n"
        f"Each card = one concept the student must remember.\n\n"
        f"Return ONLY a JSON array:\n"
        f'[{{"title":"...","content":"...","formula":null,'
        f'"bloom_level":"remember|understand"}}]'
    )
    return PromptPair(system=_system(subject, grade, board_type), user=user)


# ---------------------------------------------------------------------------
# Homework suggestions
# ---------------------------------------------------------------------------

def build_homework_prompt(
    ocr_text: str,
    subject: str,
    grade: str,
    board_type: str,
    strict: bool = False,
) -> PromptPair:
    prefix = _STRICT_PREFIX if strict else ""
    user = (
        f"{prefix}"
        f"Board content from today's {subject} class:\n"
        f"---\n{ocr_text}\n---\n\n"
        f"Suggest 3–5 homework tasks appropriate for {grade} students "
        f"based on today's lesson.\n"
        f"Mix Bloom's levels: at least one recall task, one apply task, "
        f"one explore/research task.\n"
        f"Tasks must be completable at home without lab equipment.\n"
        f"For EACH task, also provide a model answer and a short explanation "
        f"the teacher can use to check a student's work: 'answer' is the "
        f"expected outcome — a worked solution for a practice task, or, for "
        f"an open-ended explore/research/creative task, a concrete example "
        f"of what a strong answer looks like. 'explanation' is 2-4 sentences "
        f"on the reasoning/approach behind that answer, written so a "
        f"{grade} student could follow it.\n\n"
        f"Return ONLY a JSON array:\n"
        f'[{{"task":"...","type":"practice|explore|research|creative",'
        f'"bloom_level":"...","estimated_minutes":15,"topic":"...",'
        f'"answer":"...","explanation":"..."}}]'
    )
    return PromptPair(system=_system(subject, grade, board_type), user=user)


# ---------------------------------------------------------------------------
# Analogy suggestions
# ---------------------------------------------------------------------------

def build_analogies_prompt(
    ocr_text: str,
    subject: str,
    grade: str,
    board_type: str,
    strict: bool = False,
) -> PromptPair:
    prefix = _STRICT_PREFIX if strict else ""
    user = (
        f"{prefix}"
        f"Board content from today's {subject} class:\n"
        f"---\n{ocr_text}\n---\n\n"
        f"Generate real-life analogies that help {grade} students in India "
        f"understand the abstract concepts taught today.\n"
        f"Use everyday objects, local context, and familiar experiences "
        f"(e.g. cricket, monsoon, dosa, auto-rickshaw).\n\n"
        f"Return ONLY a JSON array:\n"
        f'[{{"concept":"...","analogy":"...","explanation":"..."}}]'
    )
    return PromptPair(system=_system(subject, grade, board_type), user=user)


# ---------------------------------------------------------------------------
# Combined class analysis (board OCR + audio transcript)
# ---------------------------------------------------------------------------

def build_combined_analysis_prompt(
    ocr_text: str,
    audio_transcript: str,
    lesson_plan_topics: list[str],
    subject: str,
    grade: str,
    engagement_metrics: dict | None = None,
    audience_data: dict | None = None,
    audio_sources: list[dict] | None = None,
    strict: bool = False,
) -> PromptPair:
    """
    Source-split combined analysis.

    Output JSON has four source sections + a complete_analysis synthesis:
      from_board, from_audio, from_audience, from_video, complete_analysis
    """
    import json as _json

    prefix = _STRICT_PREFIX if strict else ""
    has_audio = bool(audio_transcript and audio_transcript.strip())

    # Detect video recordings among audio sources
    video_recordings = [s for s in (audio_sources or []) if s.get("source") == "video"]
    standalone_audio = [s for s in (audio_sources or []) if s.get("source") == "audio"]
    has_video = bool(video_recordings)
    has_standalone_audio = bool(standalone_audio)

    # ── Source context blocks ────────────────────────────────────────────────
    lp_note = (
        f"Lesson plan topics planned: {_json.dumps(lesson_plan_topics)}\n\n"
        if lesson_plan_topics else ""
    )

    engagement_section = ""
    if engagement_metrics:
        silence_pct = round(engagement_metrics.get("silence_ratio", 0) * 100)
        wpm = engagement_metrics.get("speech_density_wpm", 0)
        q_count = engagement_metrics.get("question_count", 0)
        liveness = engagement_metrics.get("liveness_score", 0)
        high_mins = engagement_metrics.get("high_engagement_minutes", [])
        low_mins  = engagement_metrics.get("low_engagement_minutes", [])
        engagement_section = (
            f"PRE-COMPUTED AUDIO METRICS:\n"
            f"  silence={silence_pct}% · wpm={wpm:.0f} · questions={q_count} "
            f"· liveness={liveness}/10\n"
            f"  high-activity minutes: {high_mins or 'none'}\n"
            f"  low-activity minutes: {low_mins or 'none'}\n\n"
        )

    audience_section = ""
    has_audience = bool(audience_data and audience_data.get("minute_count", 0) > 0)
    if has_audience:
        avg_att = audience_data.get("avg_attention_pct", 0)   # type: ignore[union-attr]
        n_min   = audience_data.get("minute_count", 0)         # type: ignore[union-attr]
        metrics = audience_data.get("metrics", [])             # type: ignore[union-attr]
        low_minutes  = [m["minute"] for m in metrics if m["attention_pct"] < 50]
        high_minutes = [m["minute"] for m in metrics if m["attention_pct"] >= 75]
        audience_section = (
            f"AUDIENCE FACE ANALYSIS ({n_min} minutes, MediaPipe on-device):\n"
            f"  avg attention={avg_att:.0f}% · high minutes: {high_minutes or 'none'} "
            f"· low minutes: {low_minutes or 'none'}\n\n"
        )

    if has_audio:
        audio_block = f"AUDIO TRANSCRIPT:\n---\n{audio_transcript}\n---\n\n"
    else:
        audio_block = "AUDIO: Not available — infer from board only.\n\n"

    video_meta = ""
    if has_video:
        durations = [v.get("duration_sec") for v in video_recordings if v.get("duration_sec")]
        total_dur = sum(durations) if durations else None
        # Estimate frames extracted: 1 frame every 10s per recording
        estimated_video_frames = sum(
            max(1, round((v.get("duration_sec") or 0) / 10))
            for v in video_recordings
        )
        transcribed_count = sum(1 for v in video_recordings if v.get("transcribed"))
        video_meta = (
            f"VIDEO RECORDING: {len(video_recordings)} video file(s) uploaded"
            + (f", total duration ~{total_dur:.0f}s" if total_dur else "")
            + f". Extracted ~{estimated_video_frames} frames (1 per 10s) which are included in board content above."
            + (f" Audio track transcribed from {transcribed_count}/{len(video_recordings)} recordings." if transcribed_count else " Audio transcription pending.")
            + " Analyse the video recording's contribution to the lesson: what the teacher showed visually, board writing progression, and teaching style visible through the recording.\n\n"
        )

    # ── Output schema ────────────────────────────────────────────────────────
    audience_availability = "true" if has_audience else "false"
    video_availability    = "true" if has_video    else "false"
    audio_availability    = "true" if has_audio    else "false"
    board_frame_count     = len(ocr_text.split()) // 20 or 1  # rough estimate
    estimated_video_frames = sum(
        max(1, round((v.get("duration_sec") or 0) / 10))
        for v in video_recordings
    ) if has_video else 0

    user = (
        f"{prefix}"
        f"Analyse this {subject} class for grade {grade} students.\n\n"
        f"BOARD CONTENT (OCR from frames):\n---\n{ocr_text}\n---\n\n"
        f"{audio_block}"
        f"{engagement_section}"
        f"{audience_section}"
        f"{video_meta}"
        f"{lp_note}"
        f"Return ONLY a single JSON object with EXACTLY these five top-level keys:\n"
        f"{{\n"
        f'  "from_board": {{\n'
        f'    "frames_analysed": {board_frame_count},\n'
        f'    "topics": ["topic1", "topic2"],\n'
        f'    "board_summary": "1-2 sentences: what was written on the board"\n'
        f'  }},\n'
        f'  "from_audio": {{\n'
        f'    "available": {audio_availability},\n'
        f'    "topics_spoken": [{{"topic": "...", "evidence": "quote or inferred", "approximate_time": "early|mid|late"}}],\n'
        f'    "questions_detected": [{{"question": "...", "approximate_time": "early|mid|late", "answered": true}}],\n'
        f'    "student_responses_detected": false,\n'
        f'    "pacing": {{"rating": "fast|good|slow", "explanation": "..."}},\n'
        f'    "engagement_highlights": [{{"minute": 1, "observation": "...", "type": "high|low|notable"}}],\n'
        f'    "audio_summary": "1-2 sentences: what the audio recording revealed"\n'
        f'  }},\n'
        f'  "from_audience": {{\n'
        f'    "available": {audience_availability},\n'
        f'    "avg_attention_pct": {"null" if not has_audience else audience_data.get("avg_attention_pct", 0)},\n'  # type: ignore[union-attr]
        f'    "high_attention_minutes": [],\n'
        f'    "low_attention_minutes": [],\n'
        f'    "audience_summary": "1-2 sentences: what audience face analysis showed (or \'Audience mode was not used\' if unavailable)"\n'
        f'  }},\n'
        f'  "from_video": {{\n'
        f'    "available": {video_availability},\n'
        f'    "recording_count": {len(video_recordings)},\n'
        f'    "frames_extracted": {estimated_video_frames},\n'
        f'    "audio_transcribed": {"true" if has_video and has_audio else "false"},\n'
        f'    "video_summary": "1 sentence: what the video recording contributed (or \'No video recording\' if unavailable)"\n'
        f'  }},\n'
        f'  "complete_analysis": {{\n'
        f'    "summary": "2-3 sentence overall class summary combining all sources",\n'
        f'    "interactivity_score": 0,\n'
        f'    "liveness_score": 0,\n'
        f'    "overall_score": 0,\n'
        f'    "topics_on_board_not_spoken": [],\n'
        f'    "topics_spoken_not_on_board": [],\n'
        f'    "key_moments": [{{"description": "...", "approximate_time": "early|mid|late"}}],\n'
        f'    "suggestions": "2-3 concrete improvements for next class"\n'
        f'  }}\n'
        f"}}\n\n"
        f"Scoring: interactivity 0=lecture-only 10=highly-interactive; "
        f"liveness = energy level of the class; overall = weighted average of all sources. "
        f"from_audience and from_video: populate from the data above or mark available=false and explain."
    )

    system = (
        f"You are an expert classroom analytics AI for {subject}, grade {grade} in India. "
        f"Analyse the class from multiple sources and produce a structured source-split report. "
        f"Be precise, evidence-based, and constructive. Return ONLY valid JSON."
    )
    return PromptPair(system=system, user=user)


def build_absorption_map_prompt(
    frames_data: list[dict],
    subject: str,
    grade: str,
    avg_attention: float | None = None,
    strict: bool = False,
) -> PromptPair:
    """
    Generates targeted revision content from frame-level absorption data.
    frames_data: list of {sequence_no, minute, ocr_preview, attention_pct, absorption_level}
    """
    prefix = _STRICT_PREFIX if strict else ""
    avg_str = f"{avg_attention:.0f}%" if avg_attention is not None else "unknown"

    frames_text = ""
    for f in frames_data:
        ocr = (f.get("ocr_preview") or "").strip()
        if not ocr:
            continue
        level = f.get("absorption_level", "unknown")
        att = f.get("attention_pct")
        att_str = f"{att:.0f}%" if att is not None else "no data"
        minute = f.get("minute", 0)
        seq = f.get("sequence_no", "?")
        frames_text += f"Frame {seq} (min {minute}, attention={att_str}, level={level}):\n  {ocr}\n\n"

    system = (
        f"You are an AI teaching assistant for Indian classrooms. "
        f"Subject: {subject}. Grade: {grade}.\n\n"
        f"You analyse classroom absorption data — board content cross-referenced with "
        f"live student attention levels — to generate targeted revision materials. "
        f"Your output helps students revise the right content in the right depth."
    )

    user = (
        f"{prefix}"
        f"Below is board content from each captured frame of a classroom session, "
        f"annotated with the student attention level at that moment.\n"
        f"Average session attention: {avg_str}\n"
        f"Absorption levels: high = attention ≥65%, medium = 35–64%, low = <35%, unknown = no data.\n\n"
        f"Frame data:\n{frames_text or '(no OCR text available)'}\n\n"
        f"Generate a targeted revision pack as JSON with this exact structure:\n"
        f'{{\n'
        f'  "revision_sections": [\n'
        f'    {{\n'
        f'      "level": "high",\n'
        f'      "heading": "Well absorbed — quick review",\n'
        f'      "items": [{{"topic": "Newton\'s First Law", "summary": "one-line recap of the concept"}}]\n'
        f'    }},\n'
        f'    {{\n'
        f'      "level": "medium",\n'
        f'      "heading": "Revisit these — partial attention",\n'
        f'      "items": [{{"topic": "...", "summary": "...", "detail": "fuller explanation"}}]\n'
        f'    }},\n'
        f'    {{\n'
        f'      "level": "low",\n'
        f'      "heading": "Re-study these — attention dropped here",\n'
        f'      "items": [{{"topic": "...", "summary": "...", "detail": "clear re-explanation with analogy or example"}}]\n'
        f'    }}\n'
        f'  ],\n'
        f'  "insight": "1-2 sentence finding about the absorption pattern",\n'
        f'  "replan_suggestion": "What the teacher should revisit or reinforce next class"\n'
        f"}}\n\n"
        f"Rules:\n"
        f"- Only include sections for levels that appear in the frames data\n"
        f"- For high-absorption: brief summary only (1 sentence)\n"
        f"- For low-absorption: full re-explanation using a different angle, analogy, or everyday example\n"
        f"- Language appropriate for {grade} students\n"
        f"- Return ONLY valid JSON"
    )
    return PromptPair(system=system, user=user)


def build_session_report_prompt(
    ocr_text: str,
    audio_transcript: str,
    subject: str,
    grade: str,
    frame_count: int = 0,
    duration_sec: int = 0,
    engagement_metrics: dict | None = None,
) -> PromptPair:
    """
    Simple one-page session report combining board OCR, audio transcript, and
    video/frame metadata.  Returns a flat JSON — no deep nesting, no scores.
    """
    has_audio = bool(audio_transcript and audio_transcript.strip())

    meta = f"Subject: {subject} | Grade: {grade}"
    if frame_count:
        meta += f" | Board frames captured: {frame_count}"
    if duration_sec:
        mins = duration_sec // 60
        meta += f" | Session duration: ~{mins} min"

    eng_notes = ""
    if engagement_metrics:
        wpm = engagement_metrics.get("speech_density_wpm", 0)
        silence = round(engagement_metrics.get("silence_ratio", 0) * 100)
        qs = engagement_metrics.get("question_count", 0)
        eng_notes = (
            f"\nAUDIO STATS: {wpm:.0f} words/min · {silence}% silence · {qs} questions detected"
        )

    board_section = f"BOARD CONTENT (from {frame_count} frames):\n---\n{ocr_text}\n---"
    audio_section = (
        f"\n\nAUDIO TRANSCRIPT:\n---\n{audio_transcript}\n---"
        if has_audio
        else "\n\nAUDIO: Not available — base report on board content only."
    )

    user = (
        f"{meta}{eng_notes}\n\n"
        f"{board_section}"
        f"{audio_section}\n\n"
        f"Write a plain-language session report. Return ONLY this JSON:\n"
        f"{{\n"
        f'  "headline": "one sentence: what this class was about",\n'
        f'  "what_was_covered": "2-3 sentences on the main topics taught, with evidence from board/audio",\n'
        f'  "how_it_went": "2-3 sentences on pacing, teacher engagement, and student interaction",\n'
        f'  "highlights": ["notable moment 1", "notable moment 2", "notable moment 3"],\n'
        f'  "gaps": ["something not covered", "concept that needs revisiting"],\n'
        f'  "next_class": "one concrete sentence on what to teach or do next time",\n'
        f'  "sources": {{"board_frames": {frame_count}, "audio": {"true" if has_audio else "false"}}}\n'
        f"}}\n\n"
        f"Rules: plain English only, no jargon, no scores or numbers in the text fields, "
        f"be warm and constructive, highlight only what is evidenced in the data."
    )
    system = (
        f"You are a friendly teaching assistant writing a quick post-class summary for a "
        f"{subject} teacher. Be concise, warm, and practical. Return ONLY valid JSON."
    )
    return PromptPair(system=system, user=user)


# ---------------------------------------------------------------------------
# Textbook — chapter detection
# ---------------------------------------------------------------------------

_SUPPORTED_LANGUAGE_CODES = "en (English), hi (Hindi), kn (Kannada), te (Telugu), mr (Marathi), ta (Tamil)"


def build_chapter_detection_prompt(paginated_text: str, title_hint: str | None = None) -> PromptPair:
    """
    `paginated_text` has each page prefixed with a `[PAGE n]` marker (n is
    1-based, matching how a teacher/student would refer to a printed page
    number) so the model can report chapter boundaries in the same terms
    a person reading the physical book would use.

    Also detects the textbook's own language in this same call (cheap —
    the full text is already being read for chapter boundaries) so the
    teaching-segment generator can later write and narrate in that same
    language rather than defaulting to English.
    """
    system = (
        "You are an expert at analyzing scanned textbook PDFs: identifying chapter "
        "boundaries and the book's language. You will be given the extracted text of a "
        "textbook, with [PAGE n] markers showing where each page starts.\n\n"
        "CHAPTERS: identify every chapter (skip front matter like table of contents, "
        "preface, and back matter like the index/glossary unless they are the only "
        "content). start_page/end_page are the [PAGE n] numbers where that chapter "
        "begins and ends (inclusive). Titles should match the book's own chapter titles "
        "exactly, without a leading \"Chapter N\" numeral unless the book has no separate "
        "title.\n\n"
        "LANGUAGE: identify the main language the book's body text is actually written "
        f"in (not the language of this instruction). If it is one of {_SUPPORTED_LANGUAGE_CODES}, "
        "set language_code to that exact 2-letter code. For any other language, set "
        "language_code to \"other\". Always set language_name to that language's own "
        "common English name (e.g. \"Hindi\", \"Bengali\", \"English\"), regardless of "
        "which code you chose.\n\n"
        "SUBJECT: identify the single school curriculum subject this textbook belongs to "
        "— a short, standard subject name a school timetable would use (e.g. \"Science\", "
        "\"Mathematics\", \"Social Studies\", \"English\", \"Hindi\", \"Computer Science\"). "
        "Use the subject's own name in the book's language if that's clearly more natural "
        "(e.g. a Hindi-medium book) — otherwise use the English name.\n\n"
        "Return ONLY this JSON object:\n"
        "{\n"
        '  "language_code": "en|hi|kn|te|mr|ta|other",\n'
        '  "language_name": "English name of the detected language",\n'
        '  "subject": "short curriculum subject name",\n'
        '  "chapters": [{"title": "Light", "start_page": 45, "end_page": 58}, ...]\n'
        "}"
    )
    hint = f"The book is titled or described as: {title_hint}\n\n" if title_hint else ""
    user = (
        f"{hint}Analyze this textbook and return the JSON object described above.\n\n{paginated_text}"
    )
    return PromptPair(system=system, user=user)


def build_concept_notes_analysis_prompt(paginated_text: str, title_hint: str | None = None) -> PromptPair:
    """
    For a short, single-topic document (a worksheet, activity sheet, or set
    of concept notes) rather than a formal multi-chapter textbook — no
    chapter-boundary detection needed since there's only one topic. Detects
    the document's language and a short topic title (e.g. "What is an
    Electric Circuit?"), covering the whole document as a single unit.
    """
    system = (
        "You are analyzing a short educational document — a worksheet, activity sheet, "
        "or set of concept notes on ONE topic (not a full textbook with multiple "
        "chapters). You will be given its extracted text, with [PAGE n] markers.\n\n"
        "TOPIC: identify a short, clear title for the single topic this document teaches "
        "(e.g. \"What is an Electric Circuit?\"), matching the document's own heading if "
        "it has one.\n\n"
        "LANGUAGE: identify the main language the document's body text is actually "
        f"written in. If it is one of {_SUPPORTED_LANGUAGE_CODES}, set language_code to "
        "that exact 2-letter code; for any other language, set language_code to \"other\". "
        "Always set language_name to that language's own common English name.\n\n"
        "SUBJECT: identify the single school curriculum subject this document belongs to "
        "— a short, standard subject name a school timetable would use (e.g. \"Science\", "
        "\"Mathematics\", \"Social Studies\", \"English\"). Use the subject's own name in "
        "the document's language if that's clearly more natural, otherwise English.\n\n"
        "Return ONLY this JSON object:\n"
        "{\n"
        '  "topic_title": "short topic title",\n'
        '  "language_code": "en|hi|kn|te|mr|ta|other",\n'
        '  "language_name": "English name of the detected language",\n'
        '  "subject": "short curriculum subject name"\n'
        "}"
    )
    hint = f"The document is titled or described as: {title_hint}\n\n" if title_hint else ""
    user = f"{hint}Analyze this document and return the JSON object described above.\n\n{paginated_text}"
    return PromptPair(system=system, user=user)


def build_page_ocr_prompt() -> PromptPair:
    """
    Vision-OCR fallback for a PDF page pdfplumber extracted no real text
    from — confirmed live: a design-tool-exported (e.g. Canva/Figma)
    worksheet PDF can have all its "text" as vector outlines with no text
    layer at all, which pdfplumber silently returns as an empty string for
    rather than erroring, and without this fallback the teaching-segment
    generator would end up hallucinating content it never actually read.
    Plain-text transcription, not JSON — this becomes raw page text.
    """
    system = (
        "Transcribe ALL visible text on this page of an educational document (a textbook "
        "page, worksheet, or activity sheet) exactly and completely, in natural reading "
        "order (top to bottom, left to right within a row of columns). Include headings, "
        "body text, labeled lists, numbered steps, table contents, and captions. Preserve "
        "the structure with plain-text formatting (line breaks between sections, '-' for "
        "list items, numbers for numbered steps) but do not add markdown symbols like # or "
        "** or ``` code fences. Do not describe images/diagrams themselves, only transcribe actual text — if a "
        "diagram has text labels on it, include those labels. Do not add any commentary, "
        "preamble, or explanation — output only the transcribed text itself."
    )
    user = "Transcribe all the text on this page."
    return PromptPair(system=system, user=user)


# ---------------------------------------------------------------------------
# Textbook — teaching segment generation
# ---------------------------------------------------------------------------

def build_teaching_segment_prompt(
    chapter_title: str,
    chapter_text: str,
    taught_log: list[str],
    is_first_segment: bool,
    nearing_budget: bool = False,
    available_figures: list[dict] | None = None,
    language_name: str = "English",
) -> PromptPair:
    """
    Generates ONE paced segment of a live explanation of `chapter_text`,
    in the voice of a teacher speaking to the class — not a reformatted
    copy of the textbook. Each call produces the NEXT segment given what
    has already been taught (taught_log), stopping at a natural pause
    point rather than trying to cover the whole chapter at once.

    `nearing_budget` is set once the caller's own segment-count safety
    cap is close, as a hint to wrap up — the model has no innate sense of
    "how much of the chapter is left" and, left alone, keeps elaborating
    with plausible but invented sub-topics that were never in the source
    text (confirmed live: without this, a 4-page chapter kept generating
    genuinely new content — angle-of-reflection laws, periscopes — past
    seven straight segments with is_last_segment never set).

    `available_figures` is [{"figure_id": str, "caption": str}, ...] —
    diagrams already extracted from the textbook's own pages and passed
    through a vision content-safety gate (see textbook_service). The model
    may reference at most one per segment by id; it is NEVER allowed to
    invent a figure_id, only pick one from this exact list or return null.
    """
    system = (
        "You are an experienced, warm classroom teacher explaining a textbook chapter "
        "out loud to your students, live. You are NOT reading the textbook verbatim — you "
        "explain concepts in your own words, the way a good teacher does: give an intuitive "
        "hook or everyday example before the formal definition, build up step by step, and "
        "check for understanding. Speak directly to the student ('you'), in a natural, "
        "spoken register (short sentences, contractions), not a textbook register.\n\n"
        f"LANGUAGE: write segment_text and taught_summary entirely in {language_name}, in "
        f"its own native script (not transliterated into Latin letters), exactly as a "
        f"teacher fluent in {language_name} would actually speak to students — this "
        f"matches the textbook's own language. Keep proper nouns and internationally "
        f"standard technical terms (chemical symbols, formulas, unit names) in their usual "
        f"form even if that form is borrowed from English, the way a real "
        f"{language_name}-medium classroom would.\n\n"
        "PUNCTUATION AND DELIVERY: this text is read aloud by a text-to-speech voice, so "
        "punctuate for how it should SOUND, not just for how it reads. Use commas for "
        "brief natural pauses, an ellipsis (…) for a thoughtful beat before revealing "
        "something, exclamation marks where a teacher would genuinely sound enthusiastic "
        "(sparingly — not every sentence), and question marks for the check-in questions. "
        "Vary sentence length like real speech does. Do not overdo it — this should still "
        "read as one warm, natural take, not a script full of stage directions.\n\n"
        "OPENING WORDS: do not default to the same filler word (\"Alright\", \"Okay\", \"So\", "
        "\"Now\") to open every segment — a real teacher doesn't start every single thing "
        "they say the same way. Vary it genuinely: sometimes dive straight into the idea or "
        "example, sometimes open with a question, sometimes reference what was just said, "
        "sometimes just a natural connector. If in doubt, prefer starting directly with "
        "content over any throat-clearing opener at all.\n\n"
        "You teach in SEGMENTS. Each response is ONE segment — a few connected points that "
        "a student can absorb before needing a pause, roughly 45-90 seconds of spoken content "
        "(about 100-220 words). End every segment at a natural breathing point, often with a "
        "short check-in question ('Does that make sense so far?' / 'Ready to continue?') — "
        "the student will tap Continue or say so to hear the next segment, so do not try to "
        "cover everything at once and do not summarize the whole chapter in one go.\n\n"
        "STAY GROUNDED IN THE SOURCE TEXT: teach only what the source material below actually "
        "contains, plus the minimum everyday context needed to make it click (an analogy, a "
        "worked example). Do not invent additional named laws, devices, or sub-topics that "
        "are not in the source text just to keep going — a short chapter should produce a "
        "short number of segments, not be padded out indefinitely. Once every idea in the "
        "source text has been taught, the NEXT segment must be a short wrap-up (what was "
        "covered, in one or two sentences) with is_last_segment set to true — do not keep "
        "teaching past the source material.\n\n"
        "You may also illustrate this segment with ONE visual. Check the AVAILABLE "
        "FIGURES list below FIRST: these are real diagrams already extracted from this "
        "exact textbook and captioned specifically so they can be shown at the right "
        "teaching moment — if any figure's caption clearly matches what THIS segment is "
        "teaching, use it. Do not save a good figure for later or skip it because an "
        "earlier segment already showed a different one; each one that fits its moment "
        "should be shown when that moment comes, otherwise the images the student "
        "uploaded go unused. Only leave the visual out when nothing in the list is "
        "actually relevant to this specific segment. Two ways to do this, pick at most "
        "one:\n"
        "1. figure_id: if one of the AVAILABLE FIGURES below (real diagrams from this "
        "textbook) matches what THIS segment is teaching, set figure_id to its exact id "
        "string. Never invent an id that isn't in the list.\n"
        "2. diagram_spec: if no available figure fits but a simple labeled diagram would "
        "help, describe one as {\"diagram_type\": \"cycle\" or \"sequence\", \"nodes\": "
        "[\"Step one\", \"Step two\", ...]} — 2 to 6 short plain-language labels (a few "
        f"words each, grade-appropriate, no symbols beyond ordinary punctuation), written "
        f"in {language_name} in its native script, same as segment_text. Use "
        "\"cycle\" for a process that loops back on itself (e.g. water cycle), "
        "\"sequence\" for a straight progression (e.g. solid to liquid to gas). This "
        "renders as plain labeled boxes and arrows — do not describe colors, characters, "
        "people, or artwork, only the concept's own steps/parts.\n\n"
        "Return ONLY this JSON object:\n"
        "{\n"
        '  "segment_text": "what the teacher says for this segment, in spoken style",\n'
        '  "taught_summary": "one short clause noting what THIS segment covered, e.g. '
        '\\"introduced what light is and that it travels in straight lines\\"",\n'
        '  "is_last_segment": false,\n'
        '  "figure_id": "id string from AVAILABLE FIGURES, or null",\n'
        '  "diagram_spec": {"diagram_type": "cycle|sequence", "nodes": ["...", "..."]} or null\n'
        "}\n"
        "Set is_last_segment to true on the segment that finishes covering the source "
        "material (a short wrap-up segment, as above) — not before, and not much after."
    )
    progress = (
        "This is the FIRST segment — start from the very beginning of the chapter, with an "
        "engaging opening (do not say \"today we will learn\", just start teaching)."
        if is_first_segment
        else (
            "Already taught in this chapter, in order:\n- " + "\n- ".join(taught_log) + "\n\n"
            "Continue naturally from there with the NEXT segment — do not repeat what was "
            "already covered, and do not re-introduce the topic."
        )
    )
    budget_note = (
        "\n\nYou are running long for how much source material this chapter has. Wrap up "
        "now: this segment (or the next one at the latest) should be the closing summary "
        "with is_last_segment = true, even if you'd normally add more."
        if nearing_budget else ""
    )
    if available_figures:
        figures_block = "\n\nAVAILABLE FIGURES (real diagrams from this textbook — reference by id if relevant):\n" + "\n".join(
            f'- {{"figure_id": "{f["figure_id"]}", "caption": "{f["caption"]}"}}' for f in available_figures
        )
    else:
        figures_block = "\n\nAVAILABLE FIGURES: none — use diagram_spec instead if a visual would help, else leave both null."

    user = (
        f"Chapter: {chapter_title}\n\n"
        f"{progress}{budget_note}{figures_block}\n\n"
        f"Source material for this chapter (your reference — explain it, don't read it aloud "
        f"verbatim, and don't go beyond it):\n---\n{chapter_text}\n---\n\n"
        f"Generate the next teaching segment as the JSON object described above."
    )
    return PromptPair(system=system, user=user)


def build_quest_teaching_segment_prompt(
    chapter_title: str,
    chapter_text: str,
    taught_log: list[str],
    quest_phase_history: list[str],
    is_first_segment: bool,
    nearing_budget: bool = False,
    available_figures: list[dict] | None = None,
    language_name: str = "English",
) -> PromptPair:
    """
    Same segment-by-segment pacing contract as build_teaching_segment_prompt
    (same JSON response shape, same figure/diagram mechanism, same caller-
    side budget/hard-cap safety net — see textbook_service.generate_next_segment),
    but follows an inquiry-based GUESS -> INVESTIGATE -> OBSERVE -> INFER
    cycle instead of a straight explanation. Meant for a short, single-topic
    worksheet/activity sheet (Textbook.content_type == "concept_notes") that
    is often already structured this way in the source material itself.

    `quest_phase_history` is the sequence of quest_phase values already
    produced (e.g. ["guess", "investigate", "investigate"]) — the model
    decides for itself, each call, whether to continue the current phase or
    advance to the next one, the same way taught_log lets standard-mode
    pacing self-regulate; there is no rigid one-phase-per-segment rule.
    """
    system = (
        "You are an experienced, warm classroom teacher running a HANDS-ON INQUIRY "
        "ACTIVITY with your students, live — not lecturing. You are guiding them through "
        "a four-phase inquiry cycle grounded in the activity sheet below:\n\n"
        "1. GUESS: pose the activity's own opening question (from the source material) "
        "and ask the student to predict an answer BEFORE any explanation. Do not reveal "
        "or hint at the answer yet — a real guess requires genuine uncertainty. Just ask, "
        "warmly, and invite them to think or say their guess out loud.\n"
        "2. INVESTIGATE: narrate the activity/experiment from the source material as a "
        "guided walkthrough — what materials are used, what steps are taken, in the "
        "same order as the source. Speak as if setting it up together ('let's connect "
        "this wire to...'). If the student has the real materials they can follow along; "
        "if not, describe it vividly enough that they can still picture it. Do NOT reveal "
        "the outcome yet.\n"
        "3. OBSERVE: describe what actually happens/what one would see, grounded in the "
        "source material's own observations/results — this is the payoff of the "
        "investigation, stated clearly and concretely.\n"
        "4. INFER: help the student connect the observation back to their original guess, "
        "then clearly state the actual concept/rule/definition (grounded in the source "
        "material's own explanation) — confirm or gently correct their guess, and land on "
        "the real takeaway.\n\n"
        "Progress through these four phases IN ORDER across the segments of this "
        "conversation — do not skip a phase or jump ahead. A phase may take more than one "
        "segment if the activity has multiple steps (e.g. INVESTIGATE for a multi-step "
        "experiment); move to the next phase only once the current one is genuinely done. "
        "After INFER's concluding segment, set is_last_segment to true.\n\n"
        f"LANGUAGE: write segment_text and taught_summary entirely in {language_name}, in "
        f"its own native script (not transliterated into Latin letters), exactly as a "
        f"teacher fluent in {language_name} would actually speak to students. Keep proper "
        f"nouns and internationally standard technical terms in their usual form even if "
        f"borrowed from English, the way a real {language_name}-medium classroom would.\n\n"
        "PUNCTUATION AND DELIVERY: this text is read aloud by a text-to-speech voice, so "
        "punctuate for how it should SOUND. Commas for brief pauses, an ellipsis (…) for a "
        "thoughtful beat (especially before revealing an observation or the answer), "
        "genuine but sparing enthusiasm, question marks for real questions. Vary sentence "
        "length like real speech. One warm, natural take — not stage directions.\n\n"
        "OPENING WORDS: do not default to the same filler word (\"Alright\", \"Okay\", \"So\", "
        "\"Now\") to open every segment — a real teacher doesn't start every single thing "
        "they say the same way. Vary it genuinely: sometimes dive straight into the "
        "question/step/observation, sometimes reference what was just said, sometimes just "
        "a natural connector. If in doubt, prefer starting directly with content over any "
        "throat-clearing opener at all.\n\n"
        "Each response is ONE segment, roughly 45-90 seconds of spoken content (about "
        "100-220 words), ending at a natural pause point — the student taps Continue or "
        "says so for the next segment.\n\n"
        "STAY GROUNDED IN THE SOURCE MATERIAL below — the question, the activity steps, "
        "the materials, the observations, and the final concept must all come from it. Do "
        "not invent a different experiment or add unrelated content.\n\n"
        "You may also illustrate this segment with ONE visual. Check the AVAILABLE "
        "FIGURES list below FIRST: these are real images already extracted from this "
        "exact activity sheet (materials, setup steps, the concept diagram, etc.) and "
        "captioned specifically so they can be shown at the right teaching moment — if "
        "any figure's caption clearly matches what THIS segment is describing, use it. "
        "This is especially likely during INVESTIGATE (showing the materials/setup) and "
        "OBSERVE (showing the result) — do not save a matching figure for later or skip "
        "it because an earlier segment already showed a different one; each one that "
        "fits its moment should be shown when that moment comes, otherwise the images "
        "the student uploaded go unused. Only leave the visual out when nothing in the "
        "list is actually relevant to this specific segment. Two ways, pick at most one:\n"
        "1. figure_id: if one of the AVAILABLE FIGURES below (real diagrams from this "
        "document) matches what THIS segment is describing, set figure_id to its exact id "
        "string. Never invent an id that isn't in the list.\n"
        "2. diagram_spec: if no available figure fits but a simple labeled diagram would "
        "help, describe one as {\"diagram_type\": \"cycle\" or \"sequence\", \"nodes\": "
        "[\"Step one\", \"Step two\", ...]} — 2 to 6 short plain-language labels, written "
        f"in {language_name} in its native script. \"sequence\" for ordered steps (most "
        "common here), \"cycle\" only if the process genuinely loops. Plain labeled boxes "
        "and arrows only — no colors, characters, people, or artwork.\n\n"
        "Return ONLY this JSON object:\n"
        "{\n"
        '  "segment_text": "what the teacher says for this segment, in spoken style",\n'
        '  "taught_summary": "one short clause noting what THIS segment covered",\n'
        '  "quest_phase": "guess|investigate|observe|infer",\n'
        '  "is_last_segment": false,\n'
        '  "figure_id": "id string from AVAILABLE FIGURES, or null",\n'
        '  "diagram_spec": {"diagram_type": "cycle|sequence", "nodes": ["...", "..."]} or null\n'
        "}"
    )
    if is_first_segment:
        progress = (
            "This is the FIRST segment — start the GUESS phase: pose the activity's own "
            "opening question and ask the student to predict, without teaching anything yet."
        )
    else:
        phase_note = (
            f"Phases covered so far, in order: {', '.join(quest_phase_history)}. "
            if quest_phase_history else ""
        )
        progress = (
            f"{phase_note}Already said, in order:\n- " + "\n- ".join(taught_log) + "\n\n"
            "Continue naturally from there — either continue the current phase if it's not "
            "done, or advance to the next phase in the GUESS -> INVESTIGATE -> OBSERVE -> "
            "INFER order. Do not repeat what was already said."
        )
    budget_note = (
        "\n\nYou are running long for how much source material this activity has. Move to "
        "wrap up the INFER phase now — this segment (or the next one at the latest) should "
        "land on the final concept with is_last_segment = true, even if you'd normally take "
        "more time."
        if nearing_budget else ""
    )
    if available_figures:
        figures_block = "\n\nAVAILABLE FIGURES (real diagrams from this document — reference by id if relevant):\n" + "\n".join(
            f'- {{"figure_id": "{f["figure_id"]}", "caption": "{f["caption"]}"}}' for f in available_figures
        )
    else:
        figures_block = "\n\nAVAILABLE FIGURES: none — use diagram_spec instead if a visual would help, else leave both null."

    user = (
        f"Topic: {chapter_title}\n\n"
        f"{progress}{budget_note}{figures_block}\n\n"
        f"Source material (the activity sheet itself):\n---\n{chapter_text}\n---\n\n"
        f"Generate the next teaching segment as the JSON object described above."
    )
    return PromptPair(system=system, user=user)


# ---------------------------------------------------------------------------
# Textbook — figure classification (content-safety gate for extracted images)
# ---------------------------------------------------------------------------

def build_figure_classification_prompt() -> PromptPair:
    """
    Every image cropped from a textbook PDF passes through this gate before
    it can ever be stored or shown to a student — see
    textbook_service.classify_and_caption_figure. Rejects by default on any
    doubt; only a confident, genuine educational diagram is approved.
    """
    system = (
        "You are reviewing an image cropped from a children's school textbook (grades "
        "1-12), to decide whether it should be shown to a student as a teaching diagram "
        "inside an AI tutoring app. Approve ONLY a genuine educational diagram, labeled "
        "illustration, chart, or photograph of a real experiment/object directly relevant "
        "to learning — the kind of figure a textbook captions as 'Fig. N.N'.\n\n"
        "REJECT (approve=false): decorative mascot/character art, speech-bubble callout "
        "boxes, page borders or background textures, watermarks, logos, icons, QR codes, "
        "blank or near-blank crops, page-number badges, and anything you are not "
        "confident is a genuine content diagram.\n\n"
        "REJECT with reason=\"unsafe\" if the image shows a real photograph of an "
        "identifiable child's or person's face, or anything else that would not belong "
        "in front of a classroom of children — even though this comes from a vetted "
        "textbook, treat this as a hard safety check, not a judgment call. When genuinely "
        "unsure whether something is safe or is really a diagram, REJECT — never approve "
        "on a guess.\n\n"
        "Return ONLY this JSON object, no other text:\n"
        '{"approve": true|false, "caption": "short factual description of what the '
        'diagram shows, under 20 words, or null if rejected", "reason": "why rejected, '
        'or null if approved"}'
    )
    user = "Classify this image and return the JSON object described above."
    return PromptPair(system=system, user=user)


# ---------------------------------------------------------------------------
# Textbook — check understanding (teacher-triggered mid-lesson MCQ)
# ---------------------------------------------------------------------------

def build_check_understanding_prompt(
    chapter_title: str, taught_log: list[str], language_name: str = "English",
) -> PromptPair:
    """
    ONE multiple-choice question grounded ONLY in what has actually been
    taught so far (taught_log) — not the whole source document — since the
    point is to check whether THIS lesson, as delivered, landed, not to
    quiz on material the student hasn't reached yet. Teacher-paced: the
    teacher clicks to reveal this, then clicks again to reveal the answer,
    per app/routers/textbooks.py's check-understanding endpoint.
    """
    system = (
        "You are a teacher pausing a live lesson to check whether the class understood "
        "what's been taught SO FAR. Write ONE multiple-choice question testing the single "
        "most important idea covered in the 'Taught so far' list below — not something "
        "from later in the topic that hasn't been reached yet, and not pure recall of a "
        "trivial detail. A good check-understanding question tests whether the student can "
        "apply or reason with the concept, not just repeat a definition.\n\n"
        f"LANGUAGE: write everything in {language_name}, in its native script, exactly as "
        f"a {language_name}-medium classroom teacher would ask it aloud.\n\n"
        "Exactly 4 options, exactly one correct. Wrong options should be plausible "
        "misconceptions a student might actually have, not silly distractors. Keep the "
        "question and options short enough to read aloud and hold in mind.\n\n"
        "Return ONLY this JSON object:\n"
        "{\n"
        '  "question": "the question, spoken register",\n'
        '  "options": ["option A", "option B", "option C", "option D"],\n'
        '  "correct_index": 0,\n'
        '  "explanation": "1-2 sentences a teacher would say when revealing the answer — '
        'why it\'s correct, and briefly why the closest wrong option is a common mix-up"\n'
        "}"
    )
    user = (
        f"Topic: {chapter_title}\n\n"
        f"Taught so far, in order:\n- " + "\n- ".join(taught_log) + "\n\n"
        f"Generate the check-understanding question as the JSON object described above."
    )
    return PromptPair(system=system, user=user)


def build_revision_recap_prompt(
    chapter_title: str, taught_log: list[str], language_name: str = "English",
) -> PromptPair:
    """
    A short "here's what we covered" recap, shown once when a teacher
    resumes a chapter that already has progress on it (e.g. picking a
    lesson back up the next day, or revising before an exam) — condenses
    chapter.taught_log's per-segment notes into a tight bullet list rather
    than just dumping that raw list verbatim, since taught_log entries can
    be numerous and repetitive by the time a chapter is half-taught.
    """
    system = (
        "You are a teacher about to continue a lesson that was already partly taught in "
        "an earlier session. Before moving on to new material, give the class a QUICK "
        "recap of what was already covered — condensed into clear bullet points, not a "
        "restatement of every single note.\n\n"
        f"LANGUAGE: write every point in {language_name}, in its native script, exactly "
        f"as a {language_name}-medium classroom teacher would say it aloud.\n\n"
        "Merge closely related notes into one point rather than listing each separately, "
        "and drop anything that was just a transition or check-in with no real content of "
        "its own. Produce 3 to 6 points — fewer, well-chosen points beat an exhaustive "
        "list. Each point should be a short, complete phrase a student could read at a "
        "glance or a teacher could say in one breath (roughly 5-15 words) — not a full "
        "sentence with subordinate clauses.\n\n"
        "Return ONLY this JSON object:\n"
        '{"points": ["first thing covered", "second thing covered", "..."]}'
    )
    user = (
        f"Topic: {chapter_title}\n\n"
        f"Taught so far, in order:\n- " + "\n- ".join(taught_log) + "\n\n"
        f"Generate the recap as the JSON object described above."
    )
    return PromptPair(system=system, user=user)


# ---------------------------------------------------------------------------
# Guided Practice — batch student-region detection (one photo, many students)
# ---------------------------------------------------------------------------

def build_batch_student_detection_prompt(question_text: str) -> PromptPair:
    """
    One photo covering several students' desks/notebooks side by side, each
    with the student's name handwritten above or beside their own work —
    detect each name and the bounding box of THEIR work only (not the name
    itself, not a neighbor's work), so each region can be cropped out and
    graded independently through the normal single-student attempt
    pipeline. bbox convention matches the rest of the app's vision
    prompts (app/ocr/ocr_engine.py): normalized 0-1000, origin top-left.
    """
    system = (
        "You are looking at ONE photo that covers MULTIPLE students' notebooks or desks "
        "side by side — a teacher walked down a row and took a single wide photo instead "
        "of one photo per student. Each student has handwritten their own name somewhere "
        "near their work (usually just above or beside it) so it's clear whose work is "
        "whose.\n\n"
        "For EACH student visible in the photo:\n"
        "1. Read their handwritten name exactly as written. If a name is genuinely "
        "illegible, use \"Student\" plus the position left-to-right (e.g. \"Student 3\") "
        "rather than guessing wildly at letters you can't actually make out.\n"
        "2. Find the bounding box of ONLY that student's own work — their answer/steps, "
        "not their name label, and not any part of a neighboring student's notebook. When "
        "two students' work areas are close together or their edges are unclear, draw the "
        "box a little conservatively (smaller, safely inside their own area) rather than "
        "risk including a neighbor's handwriting — a grading pipeline runs on each crop "
        "independently, so any overlap would grade one student on another's work.\n\n"
        "Only report a student if you can see actual written work near their name — skip "
        "a name with nothing (yet) written under it rather than reporting an empty region.\n\n"
        f"The question every student is answering: {question_text}\n\n"
        "bbox is [x1, y1, x2, y2] in a 0-1000 normalized coordinate space (0,0 = top-left "
        "of the whole photo, 1000,1000 = bottom-right) — NOT pixels, NOT 0-1.\n\n"
        "Return ONLY this JSON object:\n"
        "{\n"
        '  "students": [\n'
        '    {"name": "as written, or \\"Student N\\" if illegible", "bbox": [x1, y1, x2, y2]},\n'
        "    ...\n"
        "  ]\n"
        "}\n"
        "Empty list if you can't confidently make out any distinct named regions at all — "
        "never invent a student that isn't really there."
    )
    user = "Detect each student's name and work region as the JSON object described above."
    return PromptPair(system=system, user=user)
