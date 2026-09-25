"""
Voice command intent parsing.

Turns a transcribed voice command ("start a new physics class for grade 8")
into a structured action the frontend can execute ({"intent": "create_session",
"params": {"subject": "Physics", "grade": "Grade 8"}}).

This is NOT OCR/vision — that stays on OpenAI vision unconditionally. This
module only classifies short spoken text into one of a fixed set of app
actions, which is a task small enough for a local model to handle well:

  1. Local Qwen (via Ollama) — fast, free, works offline.
  2. OpenAI GPT-4o-mini — fallback when Ollama is unreachable or its output
     doesn't parse into a valid intent.
"""
from __future__ import annotations

import json
import logging
import re

import httpx

logger = logging.getLogger(__name__)

# Every intent the voice assistant can currently trigger. Keep this in sync
# with what the frontend actually knows how to execute.
VALID_INTENTS = {
    "create_session",
    "capture_frame",
    "start_camera",
    "stop_camera",
    "start_recording",
    "stop_recording",
    "reprocess_ocr",
    "generate_notes",
    "generate_quiz",
    "generate_summary",
    "generate_experiments",
    "generate_practice_questions",
    "set_auto_capture",
    "approve_question",
    "reject_question",
    "create_station",
    "assign_question_to_station",
    "generate_homework",
    "generate_lesson_plan",
    "generate_class_analysis",
    "generate_session_report",
    "generate_absorption_map",
    "start_station_capture",
    "stop_station_capture",
    "end_session",
    "ask_question",
    "open_session",
    "delete_session",
    "view_tab",
    "download_pdf",
    "start_teaching",
    "check_understanding",
    "mute_audio",
    "unmute_audio",
    # The Welcome/attendance flow (frontend/src/app/welcome/page.tsx) —
    # its own 4-step wizard, not session-related at all, hence the
    # separate "welcome_" prefix rather than overloading an existing
    # intent name.
    "welcome_begin",
    "welcome_take_attendance",
    "welcome_see_summary",
    "welcome_go_to_dashboard",
    # The student-facing Guided Practice station device
    # (frontend/src/app/practice-station/[stationId]/page.tsx) — its own
    # camera/voice-answer controls, distinct from the teacher's
    # start_camera/start_recording (the session board-capture page) and
    # start_station_capture (the teacher's dashboard toggling a station
    # CARD from afar). A student saying "pause" or "record my answer" while
    # standing at their own station means THIS page's own controls.
    "station_toggle_capture",
    "station_record_answer",
    "unknown",
}

_SYSTEM_PROMPT = """You are a voice command classifier for a classroom app. \
Given a spoken command, output ONLY a single JSON object (no other text, no \
markdown fences) with this exact shape:

{"intent": "<one of the intents below>", "params": {}}

You are a CLASSIFIER, not an assistant — never answer the question yourself, \
never write example content, never explain anything. Just pick the intent.

Intents:
- create_session: START a NEW class/session — requires an explicit "start" / \
"create" / "begin" / "new session" verb. The VERB alone decides this, never \
the topic — a bare "open <topic>" is ALWAYS open_session and NEVER
create_session, no matter how much the topic sounds like a textbook chapter
title (Newton's laws, the water cycle, photosynthesis, etc. are all just as
likely to be a session someone wants to open as one they want to start —
the verb is the only signal that matters). params may include "subject",
"grade", and "title" (the topic for today, e.g. "on fractions" ->
title=Fractions), and "author" if an instructor's name is given (e.g.
"start a new class for Priya" -> author=Priya) — this device is shared by
multiple instructors, so naming who's teaching is common and useful.
- capture_frame: take a photo of the board right now. Requires the camera to
  already be on — if it's off, this can't fire (that's start_camera instead).
- start_camera: turn the camera ON so it's ready to capture — "start the
  camera", "turn on the camera", "open the camera". NOT the same as
  capture_frame — this only activates the camera, it doesn't take a photo.
- stop_camera: turn the camera OFF — "stop the camera", "turn off the
  camera", "close the camera".
- start_recording: begin recording the LECTURE audio or video (the session's
  own microphone/webcam recording, separate from the board camera) — "start
  recording", "record my voice", "start recording audio", "record a video
  of this". If no type is said, default to {"type": "audio"} — audio-only
  recording is the common case; only say "video" when video/webcam was
  explicitly named. NOT start_camera — that's the board-capture camera used
  for photos, a different feature from this session/lecture recording.
  params: {"type": "audio"} or {"type": "video"}.
- stop_recording: stop the current recording — "stop recording", "stop the
  recording", "stop recording video". Same params shape as start_recording;
  default to {"type": "audio"} if no type is said.
- start_station_capture: START a Guided Practice STUDENT STATION's auto-capture
  loop — "start capturing for Aisha", "start Priya's station", "begin capture
  for station 2", "let's open Arjun's work station and start". This is a
  per-student capture channel on the Guided Practice page, NOT the same as
  start_camera/start_recording (those are the session's own board capture,
  not a student's). "Open <name>'s station and start" means the same thing
  as "start <name>'s station" — there's no separate action for opening a
  station card, so treat the whole phrase as this one intent. params:
  {"station": "<the student/desk name or station reference, as said,
  verbatim — e.g. 'Aisha', 'station 2', 'Priya', 'Arjun'>"}, omit if
  genuinely no name was said (only safe when there's just one station).
- stop_station_capture: STOP a Guided Practice student station's auto-capture
  loop — "stop capturing for Aisha", "pause Priya's station". Same params
  shape as start_station_capture.
- create_station: CREATE a new Guided Practice station for ONE named
  student/desk — "create a station for Ananth", "add a station for Row 2",
  "new station for Priya". This is a SINGLE named station, never confuse
  with a request to photograph/scan multiple students' notebooks at once
  (that has no intent — it's a manual on-screen action, "one photo, every
  student"). params: {"station": "<the student/desk name, as said>"} —
  required, this intent is meaningless without a name.
- assign_question_to_station: ASSIGN one of the approved guided-practice
  questions to a station — "assign the second question to Aisha", "give
  Priya's station question 1", "set station 2 to the third question". Which
  QUESTION is meant by its position in the approved list (first/1st/second/
  2nd/etc, as said, verbatim — don't convert to a number yourself), which
  STATION by the student/desk name. params: {"station": "<name, as said>",
  "which": "<the question's position, as said, e.g. '2nd', 'the third
  one'>"} — both required.
- approve_question: APPROVE one or more pending guided-practice questions
  awaiting teacher review — "approve the first question", "approve 1st,
  2nd and 3rd", "approve all". params: {"which": "<verbatim reference to
  which pending question(s) — an ordinal like '1st', a list like '1st, 2nd
  and 3rd', or literally 'all'>"} — required.
- reject_question: REJECT one or more pending guided-practice questions —
  same phrasing/params shape as approve_question ("reject the second one",
  "reject all").
- reprocess_ocr: re-run OCR/text-extraction on the most recently captured
  photo — "reprocess that", "try OCR again", "re-scan the last photo", "redo
  the text extraction". For when a capture came out garbled/empty and
  they want another attempt at reading the SAME photo (no new capture).
- generate_notes: CREATE/build study notes from what's been captured so far.
  Only for an explicit "generate/make/create the notes" instruction — NOT
  for a question about a topic that could go in notes, and NOT for a
  request to just go look at notes that already exist (that's view_tab).
- generate_quiz: CREATE a quiz from what's been captured so far. Same rule —
  only an explicit "make/create a quiz" instruction, never "show me" / "take
  me to" the quiz (that's view_tab).
- generate_summary: CREATE a summary from what's been captured so far.
- generate_experiments: CREATE/suggest experiments from what's been
  captured. NOT "show me" / "take me to" / "go to" experiments — that's
  view_tab, even though it's the same word.
- generate_practice_questions: CREATE guided-practice / ThinkStep questions —
  either from what's been captured/uploaded so far ("generate practice
  questions", "make some ThinkStep questions"), OR from a spoken
  subject+topic with no capture needed at all ("generate 5 practice
  questions for grade 5 on light", "make ThinkStep questions on
  photosynthesis for grade 8 science"). Same rule as the other generate_*
  intents: only an explicit create/generate/make instruction, never
  "show me"/"go to" guided practice (that's view_tab). params: "subject"
  and/or "grade" and/or "topic" ONLY if said (a topic/chapter name, e.g.
  "on light" -> topic=Light — omit entirely if no topic was named, don't
  invent one), "count" (integer) if a specific number was said (e.g.
  "generate 5 questions" -> count=5), omit count if none was said.
- set_auto_capture: SET the board camera's auto-capture interval on the
  Capture page — "auto-capture every 5 seconds", "switch on auto capture
  for every 10 seconds", "capture every 30 seconds". "stop auto capture" /
  "turn off auto capture" means the same intent with seconds=0. Only these
  exact values are valid on this page: 0 (off), 5, 10, 20, 30, 60 — round
  a spoken value to the NEAREST of those, never invent another number.
  params: {"seconds": <0|5|10|20|30|60>} — required, always include it.
- generate_homework: CREATE homework from what's been captured so far —
  "generate homework", "make homework for this class". NOT "show me the
  homework" (that's view_tab).
- generate_lesson_plan: CREATE the lesson-plan coverage report — "generate
  the lesson plan", "make a lesson plan coverage report". NOT "show me the
  lesson plan" (that's view_tab).
- generate_class_analysis: CREATE the classroom/audience analysis — "analyze
  the classroom", "generate the class analysis", "run the classroom
  snapshot". NOT "show me the classroom snapshot" (that's view_tab).
- generate_session_report: CREATE the full session report — "generate the
  session report", "create a report for this class". NOT "show me the
  session report" (that's view_tab).
- generate_absorption_map: CREATE the absorption map (which concepts landed
  vs. didn't) — "generate the absorption map", "make the absorption map".
  NOT "show me the absorption map" (that's view_tab).
- view_tab: NAVIGATE to a tab/page WITHIN THE SESSION CURRENTLY OPEN — "take
  me to the experiments page", "go to the quiz tab", "show me the notes",
  "switch to the OCR view". The verb is the tell: "take me to" / "go to" /
  "show me" / "open the ... tab" / "switch to" = navigation (view_tab).
  "generate" / "make" / "create" = new content (generate_*). params:
  {"output": the tab, from this exact list of every tab in the session view —
  "overview", "capture", "ocr", "notes", "quiz", "experiments",
  "missing-concepts", "homework", "class-analysis", "lesson-plan",
  "session-report", "tiqer", "textbook", "guided-practice", "absorption-map". Several labels don't sound like their tab name:
  "opportunities" -> "missing-concepts", "classroom snapshot" -> "class-analysis",
  "thinkstep" -> "guided-practice", "summary" -> "overview" (the Overview tab
  was renamed "Summary" on screen, but the route/param value stays
  "overview" — the SAME distinction as generate_summary applies: "show
  me/go to the summary" is this navigation, "generate/make a summary" is
  generate_summary, a different intent, for NEW content)}.
- end_session: finish and mark the CURRENT session complete — it stays,
  just moves out of "active" status. NOT the same as deleting it.
- delete_session: REMOVE a session — "delete the grade 5 session", "remove
  my physics class from 10 days ago", "delete the Newton's laws session".
  This is destructive (even though it's a soft delete under the hood, the
  teacher doesn't know that) so it always asks for confirmation before
  actually happening — you're just identifying WHICH session. params:
  "subject" and/or "grade" ONLY if named, "title" if a topic/session name is
  named (many sessions have no subject set, so a named topic is often the
  ONLY reliable identifier — always capture it when said), "author" if a
  teacher's name is named (e.g. "delete Jane's physics session" ->
  author=Jane), plus "days_ago" (integer) if a recency reference is given —
  convert "yesterday" -> 1, "last week" -> 7, "N days ago" -> N. Omit any
  key not said.
- ask_question: ANY question, request for an example, request for an
  explanation, or request for a recap — including "where did we stop",
  "what's pending", "what should I teach next", a general subject question,
  a request like "give me an example of X" or "explain X", or a question
  about you/the assistant itself ("who are you", "what can you do"). params:
  {"question": "<verbatim>"}, plus "subject" and/or "grade" ONLY if the
  teacher explicitly named one (e.g. "in physics" -> subject=physics; "for
  grade 8" -> grade=Grade 8). Do not guess a subject/grade that wasn't said.
- open_session: navigate to a PAST session (a different one from whatever is
  currently open) — ONLY when a subject, grade, topic/session name, author,
  or time/recency reference is named ("my physics notes", "grade 8's quiz",
  "yesterday's session", "my last session", "the Newton's laws session",
  "Jane's physics class"). If NONE of those is present, it's view_tab, not
  open_session — a bare "show me the lesson plan" / "open tiqer" means the
  session already open, not a search for a different one. The word "session"
  or "class" does NOT need to be said — "open Newton's Laws of Motion" and
  "open the Newton's Laws of Motion session" mean exactly the same thing:
  open_session with title="Newton's Laws of Motion". A bare "open <topic
  name>" is ALWAYS open_session, NEVER create_session — "open" is never a
  creation verb. params: "subject"
  and/or "grade" ONLY if named, "title" if a topic/session name is named
  (many sessions have no subject set, so a named topic is often the ONLY
  reliable identifier — always capture it when said), "author" if a
  teacher's name is named, plus "output" using the EXACT SAME tab list and
  label mapping as view_tab above, if a specific tab was asked for (omit
  "output" if they just want the session itself, e.g. "open my last session"),
  plus "days_ago" (integer) if a recency reference is given — convert
  "yesterday" -> 1, "last week" -> 7, "N days ago" -> N.
- download_pdf: download/export/save/print the report page CURRENTLY OPEN as a
  PDF — "download this as a PDF", "export the quiz", "save this report",
  "print the notes". The verbs "download" / "export" / "save" / "print" ALWAYS
  mean this, even for a page like "quiz" that also has a generate_quiz intent —
  "export the quiz" is download_pdf (verb=export), NOT generate_quiz (that
  needs "generate"/"make"/"create"). Applies to whatever page is already
  open, not a different session — no params.
- start_teaching: begin (or resume) a live AI-narrated explanation of a
  TEXTBOOK CHAPTER already uploaded to the current session — "let's start
  the light chapter", "teach me chapter 3", "let's revise yesterday's
  chapter", plus bare resumes with no chapter said: "continue", "continue
  teaching", "resume teaching", "start teaching". Contrast with
  create_session (a NEW class/session, always needs "class"/"session"/
  "new"): "start a new physics class" -> create_session; "continue" /
  "start teaching" -> start_teaching. params: {"chapter": "<name as said>"}
  when a chapter/topic is named, else omit "chapter" entirely (params: {}).
- check_understanding: quiz the student on what was just taught — "check
  my understanding", "quiz me on this". No params.
- mute_audio: turn OFF the teaching page's spoken narration — "mute",
  "turn off the audio", "stop reading it out loud". No params.
- unmute_audio: turn narration back ON — "unmute", "turn the audio back
  on". No params.
- welcome_begin: on the app's opening Welcome screen, move past it into
  grade/section selection — "let's begin", "begin". No params.
- welcome_take_attendance: on the grade/section screen, move to the
  attendance grid AND start the roll-call scan — "take attendance",
  "start attendance". No params.
- welcome_see_summary: once attendance is fully marked, move to the
  present/absent summary screen — "see summary", "show summary". No params.
- welcome_go_to_dashboard: from the attendance summary screen, enter the
  session dashboard — "go to dashboard", "go to the dashboard". No params.
- station_toggle_capture: on a student's OWN Guided Practice station device,
  pause or resume that station's own auto-capture loop — bare "pause",
  "resume", "pause capturing", "stop capturing", "start capturing" with NO
  student/desk name attached. If a name IS said ("pause Priya's station"),
  that's start_station_capture/stop_station_capture instead — a teacher
  controlling a station from the dashboard, not a student at their own
  device. No params.
- station_record_answer: on a student's OWN Guided Practice station device,
  start recording a spoken answer to the current question — "record my
  answer", "record answer", "say my answer". No params.
- unknown: the command doesn't clearly match any of the above.

Examples (these are the ONLY keys that ever belong in params — never invent
a "text", "answer", "content", or "example" key):
"Give me a real life example of non-uniform motion" -> {"intent": "ask_question", "params": {"question": "Give me a real life example of non-uniform motion"}}
"Explain photosynthesis simply" -> {"intent": "ask_question", "params": {"question": "Explain photosynthesis simply"}}
"What can you do" -> {"intent": "ask_question", "params": {"question": "What can you do"}}
"Who are you" -> {"intent": "ask_question", "params": {"question": "Who are you"}}
"Generate my notes now" -> {"intent": "generate_notes", "params": {}}
"Make a quiz from today's class" -> {"intent": "generate_quiz", "params": {}}
"Start a new physics class for grade 8" -> {"intent": "create_session", "params": {"subject": "Physics", "grade": "Grade 8"}}
"Open the quiz from my physics class" -> {"intent": "open_session", "params": {"subject": "Physics", "output": "quiz"}}
"Show me last week's grade 5 notes" -> {"intent": "open_session", "params": {"grade": "Grade 5", "output": "notes"}}
"Take me to the opportunities page" -> {"intent": "view_tab", "params": {"output": "missing-concepts"}}
"Show me the lesson plan" -> {"intent": "view_tab", "params": {"output": "lesson-plan"}}
"Open tiqer" -> {"intent": "view_tab", "params": {"output": "tiqer"}}
"Go to the classroom snapshot" -> {"intent": "view_tab", "params": {"output": "class-analysis"}}
"Go to guided practice" -> {"intent": "view_tab", "params": {"output": "guided-practice"}}
"Go to the summary" -> {"intent": "view_tab", "params": {"output": "overview"}}
"Show me the summary" -> {"intent": "view_tab", "params": {"output": "overview"}}
"Generate a summary" -> {"intent": "generate_summary", "params": {}}
(^ contrast: "go to/show me the summary" navigates to the renamed Overview tab; "generate/make a summary" creates new summary content — same word, different verb decides it, same rule as quiz/homework/experiments above)
"Open ThinkStep" -> {"intent": "view_tab", "params": {"output": "guided-practice"}}
"Show me the lesson plan for my grade 5 class" -> {"intent": "open_session", "params": {"grade": "Grade 5", "output": "lesson-plan"}}
"Open the quiz from my grade 5 class" -> {"intent": "open_session", "params": {"grade": "Grade 5", "output": "quiz"}}
"Open the grade 5 session created 10 days ago" -> {"intent": "open_session", "params": {"grade": "Grade 5", "days_ago": 10}}
"Open the grade 5 session from 48 days ago" -> {"intent": "open_session", "params": {"grade": "Grade 5", "days_ago": 48}}
"Delete the grade 5 session from 10 days ago" -> {"intent": "delete_session", "params": {"grade": "Grade 5", "days_ago": 10}}
"Delete my physics class" -> {"intent": "delete_session", "params": {"subject": "Physics"}}
"End the session" -> {"intent": "end_session", "params": {}}
"Start the camera" -> {"intent": "start_camera", "params": {}}
"Turn on the camera" -> {"intent": "start_camera", "params": {}}
"Stop the camera" -> {"intent": "stop_camera", "params": {}}
"Turn off the camera" -> {"intent": "stop_camera", "params": {}}
"Start recording" -> {"intent": "start_recording", "params": {"type": "audio"}}
"Record my voice" -> {"intent": "start_recording", "params": {"type": "audio"}}
"Start recording a video" -> {"intent": "start_recording", "params": {"type": "video"}}
"Record a video of this" -> {"intent": "start_recording", "params": {"type": "video"}}
"Stop recording" -> {"intent": "stop_recording", "params": {"type": "audio"}}
"Stop the video recording" -> {"intent": "stop_recording", "params": {"type": "video"}}
(^ contrast: start_recording/stop_recording are the session's own lecture mic/webcam; start_camera/stop_camera are the board-photo camera — different features, same-ish wording)
"Start capturing for Aisha" -> {"intent": "start_station_capture", "params": {"station": "Aisha"}}
"Start Priya's station" -> {"intent": "start_station_capture", "params": {"station": "Priya"}}
"Let's open Arjun's work station and start" -> {"intent": "start_station_capture", "params": {"station": "Arjun"}}
"Stop capturing for Aisha" -> {"intent": "stop_station_capture", "params": {"station": "Aisha"}}
"Pause station 2" -> {"intent": "stop_station_capture", "params": {"station": "station 2"}}
"Pause" -> {"intent": "station_toggle_capture", "params": {}}
(^ no name said at all — a student's own device, not a teacher naming someone else's station)
"Record my answer" -> {"intent": "station_record_answer", "params": {}}
"Take a photo of the board" -> {"intent": "capture_frame", "params": {}}
"Reprocess that photo" -> {"intent": "reprocess_ocr", "params": {}}
"Try OCR again" -> {"intent": "reprocess_ocr", "params": {}}
"Re-scan the last capture" -> {"intent": "reprocess_ocr", "params": {}}
"Download this as a PDF" -> {"intent": "download_pdf", "params": {}}
"Export the quiz" -> {"intent": "download_pdf", "params": {}}
"Save this report" -> {"intent": "download_pdf", "params": {}}
"Print this page" -> {"intent": "download_pdf", "params": {}}
"Make a quiz from today's class" -> {"intent": "generate_quiz", "params": {}}
(^ contrast: "make/create/generate a quiz" builds new content; "export/download/save/print the quiz" saves the existing one — same noun, different verb, different intent)
"Suggest experiments" -> {"intent": "generate_experiments", "params": {}}
"Generate some experiments for this topic" -> {"intent": "generate_experiments", "params": {}}
"Make a summary" -> {"intent": "generate_summary", "params": {}}
"Generate practice questions" -> {"intent": "generate_practice_questions", "params": {}}
"Make some ThinkStep questions" -> {"intent": "generate_practice_questions", "params": {}}
"Generate practice questions for 5th grade on light" -> {"intent": "generate_practice_questions", "params": {"grade": "Grade 5", "topic": "Light"}}
"Make 5 ThinkStep questions on photosynthesis for grade 8 science" -> {"intent": "generate_practice_questions", "params": {"subject": "Science", "grade": "Grade 8", "topic": "Photosynthesis", "count": 5}}
"Generate 3 practice questions" -> {"intent": "generate_practice_questions", "params": {"count": 3}}
"Switch on auto capture for every 5 seconds" -> {"intent": "set_auto_capture", "params": {"seconds": 5}}
"Auto-capture every 10 seconds" -> {"intent": "set_auto_capture", "params": {"seconds": 10}}
"Stop auto capture" -> {"intent": "set_auto_capture", "params": {"seconds": 0}}
"Turn off auto capture" -> {"intent": "set_auto_capture", "params": {"seconds": 0}}
"Create a station for Ananth" -> {"intent": "create_station", "params": {"station": "Ananth"}}
"Add a new station for Priya" -> {"intent": "create_station", "params": {"station": "Priya"}}
"Assign the second question to Aisha" -> {"intent": "assign_question_to_station", "params": {"station": "Aisha", "which": "2nd"}}
"Give Priya's station question 1" -> {"intent": "assign_question_to_station", "params": {"station": "Priya", "which": "1"}}
"Approve the first question" -> {"intent": "approve_question", "params": {"which": "1st"}}
"Approve 1st, 2nd and 3rd" -> {"intent": "approve_question", "params": {"which": "1st, 2nd and 3rd"}}
"Approve all" -> {"intent": "approve_question", "params": {"which": "all"}}
"Reject the second one" -> {"intent": "reject_question", "params": {"which": "2nd"}}
"Reject all" -> {"intent": "reject_question", "params": {"which": "all"}}
"Generate homework for this class" -> {"intent": "generate_homework", "params": {}}
"Show me the homework" -> {"intent": "view_tab", "params": {"output": "homework"}}
(^ contrast: "generate/make homework" builds new content; "show me/go to the homework" navigates to it — same noun, different verb, different intent, same rule as quiz/experiments above)
"Make the lesson plan" -> {"intent": "generate_lesson_plan", "params": {}}
"Analyze the classroom" -> {"intent": "generate_class_analysis", "params": {}}
"Run the classroom snapshot" -> {"intent": "generate_class_analysis", "params": {}}
"Generate the session report" -> {"intent": "generate_session_report", "params": {}}
"Show me the session report" -> {"intent": "view_tab", "params": {"output": "session-report"}}
"Make the absorption map" -> {"intent": "generate_absorption_map", "params": {}}
"Show me the absorption map" -> {"intent": "view_tab", "params": {"output": "absorption-map"}}
"Open the Newton's laws session" -> {"intent": "open_session", "params": {"title": "Newton's laws"}}
"Open Newton's Laws of Motion" -> {"intent": "open_session", "params": {"title": "Newton's Laws of Motion"}}
"Open Newton's Laws of Motion, over" -> {"intent": "open_session", "params": {"title": "Newton's Laws of Motion"}}
"Create a new class on Newton's laws" -> {"intent": "create_session", "params": {"title": "Newton's laws"}}
(^ same topic, different verb — "open" always finds an existing one, "create" always makes a new one)
"Open photosynthesis" -> {"intent": "open_session", "params": {"title": "photosynthesis"}}
"Delete the session about photosynthesis" -> {"intent": "delete_session", "params": {"title": "photosynthesis"}}
"Open the water cycle" -> {"intent": "open_session", "params": {"title": "The Water Cycle"}}
"Begin a session on the water cycle" -> {"intent": "create_session", "params": {"title": "The Water Cycle"}}
"Start a new session on fractions for grade 8" -> {"intent": "create_session", "params": {"title": "Fractions", "grade": "Grade 8"}}
"Create a new session on photosynthesis" -> {"intent": "create_session", "params": {"title": "photosynthesis"}}
"Start a new grade 5 class for Priya on fractions" -> {"intent": "create_session", "params": {"grade": "Grade 5", "author": "Priya", "title": "Fractions"}}
"Open Jane's physics class" -> {"intent": "open_session", "params": {"subject": "Physics", "author": "Jane"}}
"Delete the grade 5 session created by Priya" -> {"intent": "delete_session", "params": {"grade": "Grade 5", "author": "Priya"}}
"Take me to the experiments page" -> {"intent": "view_tab", "params": {"output": "experiments"}}
"Take me from quiz to experiments" -> {"intent": "view_tab", "params": {"output": "experiments"}}
"Go to the quiz tab" -> {"intent": "view_tab", "params": {"output": "quiz"}}
"Show me the notes" -> {"intent": "view_tab", "params": {"output": "notes"}}
"Ok let's start grade 6 light chapter" -> {"intent": "start_teaching", "params": {"chapter": "light", "grade": "Grade 6"}}
"Teach me the chapter on photosynthesis" -> {"intent": "start_teaching", "params": {"chapter": "photosynthesis"}}
"Let's revise yesterday's chapter" -> {"intent": "start_teaching", "params": {"chapter": "yesterday's chapter"}}
"Start chapter 3" -> {"intent": "start_teaching", "params": {"chapter": "chapter 3"}}
"Continue" -> {"intent": "start_teaching", "params": {}}
"Continue teaching" -> {"intent": "start_teaching", "params": {}}
"Let's continue" -> {"intent": "start_teaching", "params": {}}
"Continue where we left off" -> {"intent": "start_teaching", "params": {}}
"Resume teaching" -> {"intent": "start_teaching", "params": {}}
"Start teaching" -> {"intent": "start_teaching", "params": {}}
(^ contrast: "start a new physics class" is create_session — has "new" + "class"; "start teaching" has neither, just the bare verb "teaching")
"Check my understanding" -> {"intent": "check_understanding", "params": {}}
"Quiz me on this" -> {"intent": "check_understanding", "params": {}}
"Test my understanding" -> {"intent": "check_understanding", "params": {}}
"Quiz me on what we just covered" -> {"intent": "check_understanding", "params": {}}
"Turn off the audio" -> {"intent": "mute_audio", "params": {}}
"Mute the narration" -> {"intent": "mute_audio", "params": {}}
"Stop reading it out loud" -> {"intent": "mute_audio", "params": {}}
"Turn the audio back on" -> {"intent": "unmute_audio", "params": {}}
"Unmute" -> {"intent": "unmute_audio", "params": {}}
(^ contrast: "start a new physics class for grade 8" is create_session — no "chapter", and explicitly a new class/session)
"Let's begin" -> {"intent": "welcome_begin", "params": {}}
"Begin" -> {"intent": "welcome_begin", "params": {}}
"Take attendance" -> {"intent": "welcome_take_attendance", "params": {}}
"Start attendance" -> {"intent": "welcome_take_attendance", "params": {}}
"See summary" -> {"intent": "welcome_see_summary", "params": {}}
"Show summary" -> {"intent": "welcome_see_summary", "params": {}}
"Go to dashboard" -> {"intent": "welcome_go_to_dashboard", "params": {}}
"Go to the dashboard" -> {"intent": "welcome_go_to_dashboard", "params": {}}

If no subject/grade/type/output is mentioned, omit that key from params — do not guess.
Output ONLY the JSON object."""

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)

# The only params keys any intent is ever allowed to return. A response with
# a key outside this set (e.g. "text", "answer") means the model didn't
# follow the classifier-only instruction and likely tried to answer the
# question itself instead of classifying it — that response is unreliable
# and gets rejected rather than trusted, triggering the cloud fallback.
_ALLOWED_PARAM_KEYS = {"subject", "grade", "title", "author", "type", "question", "output", "days_ago", "chapter", "station", "topic", "count", "seconds", "which"}


def _extract_json(raw: str) -> dict | None:
    match = _JSON_BLOCK.search(raw)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _validate(data: dict) -> dict | None:
    intent = data.get("intent")
    if intent not in VALID_INTENTS:
        return None
    params = data.get("params")
    if not isinstance(params, dict):
        params = {}
    if not set(params.keys()) <= _ALLOWED_PARAM_KEYS:
        return None
    return {"intent": intent, "params": params}


async def _classify_local(transcript: str, base_url: str, model: str, timeout: int) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{base_url}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": transcript},
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0,
                        # Ollama silently truncates the prompt to its default
                        # context window (historically 2048 tokens) when
                        # num_ctx isn't set explicitly — NOT an error, just a
                        # quiet drop of however much of the system prompt
                        # doesn't fit, which is far worse than a visible
                        # failure: the model still answers confidently, just
                        # without ever having seen the parts of its own
                        # instructions/intent list that got cut off. This
                        # prompt is now consistently 2000+ tokens (it grows
                        # every time a new intent/example is added), which
                        # crossed exactly that default right as previously-
                        # reliable, unrelated intents started misclassifying
                        # for no apparent reason (confirmed 2026-09-22 via a
                        # raw /api/chat call: prompt_eval_count=2050, and the
                        # model failed to reproduce its own verbatim few-shot
                        # examples). 8192 leaves real headroom for future
                        # growth; qwen2.5:3b supports up to 32768.
                        "num_ctx": 8192,
                    },
                    # Request-level keep-alive, not a systemd/env setting — this
                    # way the model stays warm regardless of how Ollama itself
                    # was launched (works the same on a Mac dev box and the
                    # Pi's systemd service). Ollama's default unload-after-5-min
                    # was exactly the "cold load costs 15-19s" problem measured
                    # earlier in this project — asking to keep it loaded
                    # indefinitely on every call is what actually fixes that.
                    "keep_alive": -1,
                },
            )
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content", "")
    except Exception as exc:
        logger.warning("Voice intent: local Ollama call failed: %s", exc)
        return None

    data = _extract_json(content)
    if data is None:
        logger.warning("Voice intent: local model returned unparseable output: %.200s", content)
        return None
    validated = _validate(data)
    if validated is None:
        logger.warning("Voice intent: local model returned invalid intent: %.200s", content)
        return None
    return validated


async def _classify_cloud(transcript: str, api_key: str, timeout: int) -> dict | None:
    try:
        from openai import AsyncOpenAI
    except ImportError:
        return None

    client = AsyncOpenAI(api_key=api_key)
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=150,
            temperature=0,
            timeout=timeout,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": transcript},
            ],
        )
        content = resp.choices[0].message.content or ""
    except Exception as exc:
        logger.warning("Voice intent: OpenAI fallback call failed: %s", exc)
        return None

    data = _extract_json(content)
    if data is None:
        return None
    return _validate(data)


_LEADING_FILLER = re.compile(r"^(please|can you|could you|let'?s|hey|so|um)\s+", re.I)
# A bare "continue"/"resume" with nothing else said is short enough that the
# local 3B model doesn't reliably map it to start_teaching — confirmed
# 2026-09-22: it echoes the verb itself back as an invented intent name
# ("continue") rather than the actual start_teaching label, even with a
# matching few-shot example in the prompt. There's no real ambiguity to
# resolve here (unlike _apply_verb_override's cases), so skip the model
# entirely for this narrow, common phrase — faster and fully reliable.
_BARE_RESUME = re.compile(r"^(continue|resume)( teaching)?( where we left off)?$", re.I)
_LEADS_WITH_OPEN = re.compile(r"^open\b", re.I)
_SOUNDS_LIKE_NEW_SESSION = re.compile(r"\bnew (session|class)\b", re.I)
_LEADS_WITH_EXPORT_VERB = re.compile(r"^(download|export|save|print)\b", re.I)
_LEADS_WITH_VIEW_VERB = re.compile(r"^(show|go to|take me to|switch to|open)\b", re.I)
_GENERATE_INTENTS = {
    "generate_notes", "generate_quiz", "generate_summary", "generate_experiments",
    "generate_practice_questions", "generate_homework", "generate_lesson_plan",
    "generate_class_analysis", "generate_session_report", "generate_absorption_map",
}
# Mirrors GENERATE_OUTPUT_BY_INTENT in ClassroomBrain.tsx — the tab a
# generate_* intent's output lands on, needed to redirect a misclassified
# "show me the X" onto view_tab with the right params.output.
_TAB_BY_GENERATE_INTENT = {
    "generate_notes": "notes",
    "generate_quiz": "quiz",
    "generate_summary": "overview",
    "generate_experiments": "experiments",
    "generate_practice_questions": "guided-practice",
    "generate_homework": "homework",
    "generate_lesson_plan": "lesson-plan",
    "generate_class_analysis": "class-analysis",
    "generate_session_report": "session-report",
    "generate_absorption_map": "absorption-map",
}


def _strip_filler(transcript: str) -> str:
    """Strip repeated leading filler words, e.g. "hey so open..." -> "open...".
    Shared by _apply_verb_override, _classify_deterministic, and the bare-resume
    check in classify_intent() — all three need the exact same normalization."""
    t = transcript.strip()
    for _ in range(3):
        stripped = _LEADING_FILLER.sub("", t)
        if stripped == t:
            break
        t = stripped
    return t


# ---------------------------------------------------------------------------
# Deterministic classification layer.
#
# Voice command classification is, for most of the ~34 intents above, a
# small closed problem: a fixed leading verb plus a keyword/slot, not
# open-ended generation. Measured on the deployed Pi (2026-09-23): a single
# OpenAI classification call took 13.2s vs. 1.6s for an otherwise-identical
# call — confirmed via timestamps to be OpenAI's own response-time variance
# for that endpoint, not our retry logic, not Pi CPU, not Pi network (all
# separately ruled out). Rather than accept that variance, this layer
# handles the common, unambiguous commands with zero model calls at all,
# generalizing the _BARE_RESUME fast path below into a full but
# conservative rule set. Anything it isn't confident about returns None and
# falls through UNCHANGED to the existing local-Ollama -> cloud-OpenAI
# pipeline, so nothing it doesn't cover can regress.
#
# Deliberately NOT covered here: create_session/open_session/delete_session
# (need genuinely free-form subject/grade/title/author/days_ago extraction —
# an LLM's flexibility matters, and these fire once per class, not
# repeatedly, so occasional cloud latency is far more tolerable), ask_question
# (genuinely open-ended text), and start_teaching with a named chapter (the
# bare-resume case is already deterministic and untouched above; named-
# chapter extraction stays on the model).

_START_CAMERA = re.compile(r"^(start|turn on|open)( the)? camera$", re.I)
_STOP_CAMERA = re.compile(r"^(stop|turn off|close)( the)? camera$", re.I)
_MUTE_AUDIO = re.compile(r"^(mute( the narration)?|turn off the audio|stop reading( it)?( out loud)?)$", re.I)
_UNMUTE_AUDIO = re.compile(r"^(unmute|turn( the)? audio( back)? on)$", re.I)
_CAPTURE_FRAME = re.compile(r"^(take a (photo|picture)( of the board)?|capture( the board)?)$", re.I)
_REPROCESS_OCR = re.compile(
    r"^(reprocess( that( photo)?)?|try ocr again|re-?scan the last (photo|capture)|redo the text extraction)$",
    re.I,
)
_CHECK_UNDERSTANDING = re.compile(r"^((check|test) my understanding|quiz me( on (this|what we just covered))?)$", re.I)
_END_SESSION = re.compile(r"^end( the)? session$", re.I)

# Student-facing Guided Practice station (practice-station/[stationId]/page.tsx)
# — bare, no-name phrasing only. A name present ("pause Priya's station")
# is a teacher-dashboard command instead (start_station_capture/
# stop_station_capture), handled by the _LEADS_WITH_*_STATION checks below.
_STATION_TOGGLE_CAPTURE = re.compile(
    # No "auto capture" wording here — "start/stop auto capture" is already
    # set_auto_capture (the session capture page's interval control, an
    # existing canonical example: "Stop auto capture" -> set_auto_capture
    # seconds=0). Different feature, so keep the phrasing disjoint rather
    # than racing regex order to disambiguate identical text.
    r"^(pause|resume|start capturing|stop capturing)$", re.I
)
_STATION_RECORD_ANSWER = re.compile(r"^(record (my|the) answer|record answer|say my answer)$", re.I)

# Welcome/attendance flow (frontend/src/app/welcome/page.tsx) — see the
# matching intent descriptions above. "begin" alone (not just "let's
# begin") because _strip_filler already strips a leading "let's" before
# these run, same as every other filler-stripped pattern in this file.
_WELCOME_BEGIN = re.compile(r"^begin$", re.I)
_WELCOME_TAKE_ATTENDANCE = re.compile(r"^(take|start) attendance$", re.I)
_WELCOME_SEE_SUMMARY = re.compile(r"^(see|show)( the)? summary$", re.I)
_WELCOME_GO_TO_DASHBOARD = re.compile(r"^go to( the)? dashboard$", re.I)

_START_RECORDING = re.compile(r"^(start recording( (a|the) video)?|record (my voice|a video( of this)?))$", re.I)
_STOP_RECORDING = re.compile(r"^stop( the)? (recording|video recording)$", re.I)

# Tab slug -> keyword phrases that identify it in speech. Mirrors the
# view_tab prose above (this file) and SESSION_TABS/TAB_LABEL in
# frontend/src/components/brain/ClassroomBrain.tsx — no shared
# machine-readable source exists between the three yet; not addressed here.
_TAB_KEYWORDS: dict[str, tuple[str, ...]] = {
    "missing-concepts": ("missing concepts", "missing-concepts", "opportunities"),
    "class-analysis": ("classroom snapshot", "class analysis", "classroom analysis"),
    "lesson-plan": ("lesson plan",),
    "session-report": ("session report",),
    "absorption-map": ("absorption map",),
    "guided-practice": ("guided practice", "thinkstep", "think step"),
    "overview": ("summary", "overview"),
    "capture": ("capture",),
    "ocr": ("ocr",),
    "notes": ("notes",),
    "quiz": ("quiz",),
    "experiments": ("experiments", "experiment"),
    "homework": ("homework",),
    "tiqer": ("tiqer",),
    "textbook": ("textbook",),
}
_LEADS_WITH_VIEW_VERB_FROM = re.compile(r"^take me from\s+.+?\s+to\s+(?P<rest>.+)$", re.I)
# A view-verb + tab keyword can also legitimately be an open_session request
# for a PAST session's tab (e.g. "Show me last week's grade 5 notes" ->
# open_session, NOT view_tab) — the system prompt's own rule is that a
# subject/grade/author/recency reference makes it open_session instead.
# Without this guard the deterministic layer would misfire view_tab for
# those canonical examples; with it, it correctly defers to the LLM.
_SESSION_SEARCH_SIGNAL = re.compile(
    r"\bgrade\s*\d|\d+(st|nd|rd|th)?\s*grade|\byesterday\b|\blast week\b|\d+\s*days?\s*ago|'s\b|\bmy\s+\w+\s+class\b",
    re.I,
)

_LEADS_WITH_GENERATE_VERB = re.compile(r"^(generate|make|create|build|suggest|analyze|run)\b", re.I)
# Ordered: multi-word/more-specific phrases before shorter ones they could
# otherwise be mistaken to contain (e.g. "classroom snapshot" before the
# bare "classroom" that "analyze the classroom" reduces to).
_GENERATE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("practice questions", "generate_practice_questions"),
    ("thinkstep questions", "generate_practice_questions"),
    ("think step questions", "generate_practice_questions"),
    ("thinkstep", "generate_practice_questions"),
    ("classroom snapshot", "generate_class_analysis"),
    ("class analysis", "generate_class_analysis"),
    ("classroom", "generate_class_analysis"),
    ("session report", "generate_session_report"),
    ("lesson plan", "generate_lesson_plan"),
    ("absorption map", "generate_absorption_map"),
    ("homework", "generate_homework"),
    ("experiments", "generate_experiments"),
    ("experiment", "generate_experiments"),
    ("quiz", "generate_quiz"),
    ("notes", "generate_notes"),
    ("summary", "generate_summary"),
)
_SUBJECT_MAP = {
    "mathematics": "Mathematics", "math": "Mathematics", "science": "Science",
    "physics": "Physics", "chemistry": "Chemistry", "biology": "Biology",
}
_COUNT_RE = re.compile(r"\b(\d+)\s+(?:practice\s+)?(?:thinkstep\s+)?questions?\b", re.I)
_GRADE_RE = re.compile(r"grade\s*(\d+)|(\d+)(?:st|nd|rd|th)?\s*grade", re.I)
_TOPIC_RE = re.compile(r"\bon\s+(.+?)(?:\s+for\s+grade|\s+for\s+\d|$)", re.I)

_VALID_SECONDS = (0, 5, 10, 20, 30, 60)
_AUTO_CAPTURE_ANY = re.compile(r"\bauto[- ]?capture\b", re.I)
_AUTO_CAPTURE_OFF_VERB = re.compile(r"\b(stop|turn off|disable)\b", re.I)
_SECONDS_RE = re.compile(r"(\d+)\s*second", re.I)

_STATION_REF = re.compile(
    # name2 allows up to two filler words between the possessive and
    # "station" ("Arjun's WORK station", "Priya's PRACTICE station") — a
    # bare "Arjun's station" is still just zero filler words, so this is a
    # strict widening, not a behavior change for the phrasing that already
    # worked. Confirmed missing 2026-09-25: "Arjun's work station" fell
    # through to None because "'s" wasn't immediately followed by "station".
    r"(?:for\s+(?P<name1>.+)$)|(?:(?P<name2>[\w']+)'s\s+(?:\w+\s+){0,2}station\b)|(?:\b(?P<name3>station\s+\w+)$)",
    re.I,
)
_LEADS_WITH_CREATE_STATION = re.compile(r"^(create|add|make)\b.*\bstation\b", re.I)
_LEADS_WITH_START_STATION = re.compile(r"^(start|begin)\b.*\b(station|capturing)\b", re.I)
_LEADS_WITH_STOP_STATION = re.compile(r"^(stop|pause)\b.*\b(station|capturing)\b", re.I)
# "let's OPEN Arjun's work station and START" — a teacher opening a
# student's station card and starting it in one breath. Doesn't lead with
# start/begin so _LEADS_WITH_START_STATION never matches; searched anywhere
# in the utterance (not anchored to the start) since "open" fronts it.
_MENTIONS_OPEN_STATION_THEN_START = re.compile(r"\bopen\b.*\bstation\b.*\b(start|begin|go)\b", re.I)

_ORDINAL_WORDS = {"first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th"}
_ORDINAL_WORD_RE = re.compile(r"\b(" + "|".join(_ORDINAL_WORDS) + r")\b", re.I)
_WHICH_VALID_RE = re.compile(r"(\d+(st|nd|rd|th)?)([,\s]+(and\s+)?\d+(st|nd|rd|th)?)*$", re.I)
_APPROVE_REJECT = re.compile(r"^(approve|reject)\b\s*(?P<rest>.*)$", re.I)

_ASSIGN_A = re.compile(r"^assign (?:the )?(?P<which>.+?) question to (?P<station>.+)$", re.I)
_ASSIGN_B = re.compile(r"^give (?P<station>[\w']+)'s station question (?P<which>.+)$", re.I)
_ASSIGN_C = re.compile(r"^set station (?P<station>\w+) to (?:the )?(?P<which>.+?)( question)?$", re.I)


def _normalize_which(s: str) -> str | None:
    """Approve/reject's "which" param is verbatim per the prompt, but the
    canonical examples show word-ordinals get normalized ("the first
    question" -> "1st") while already-numeric forms and lists pass through
    unchanged ("1st, 2nd and 3rd" stays as-is, "1" stays "1" not "1st").
    Returns None for anything that doesn't resolve to a recognizable
    reference, so the caller can safely fall through to the LLM instead of
    guessing (e.g. "the sixth question" — no ordinal word beyond fifth is
    evidenced anywhere in the prompt's examples)."""
    s = s.strip()
    if not s:
        return None
    if s.lower() == "all":
        return "all"
    s = re.sub(r"\s+(questions?|one)\s*$", "", s, flags=re.I).strip()
    s = re.sub(r"^the\s+", "", s, flags=re.I).strip()
    if not s:
        return None
    s = _ORDINAL_WORD_RE.sub(lambda m: _ORDINAL_WORDS[m.group(0).lower()], s)
    return s if _WHICH_VALID_RE.fullmatch(s) else None


def _extract_station(remainder: str) -> str | None:
    m = _STATION_REF.search(remainder)
    if not m:
        return None
    for group in ("name1", "name2", "name3"):
        val = m.group(group)
        if val:
            return val.strip()
    return None


def _classify_deterministic(transcript: str) -> dict | None:
    """Zero-network classification for the intents that are simple, closed
    verb+keyword patterns — see the module comment above this block. Each
    check below returns None to mean "doesn't apply, try the next check,"
    never "abort the whole function" — several verb spaces overlap (e.g.
    "create" leads both generate_* phrasing and create_station phrasing),
    so a narrower, more specific check not matching must let a later,
    narrower-still check still get a chance, all the way down to the
    catch-all generate_* check at the end."""
    t = _strip_filler(transcript)
    if not t:
        return None
    tl = t.lower()

    for rx, intent in (
        (_START_CAMERA, "start_camera"), (_STOP_CAMERA, "stop_camera"),
        (_MUTE_AUDIO, "mute_audio"), (_UNMUTE_AUDIO, "unmute_audio"),
        (_CAPTURE_FRAME, "capture_frame"), (_REPROCESS_OCR, "reprocess_ocr"),
        (_CHECK_UNDERSTANDING, "check_understanding"), (_END_SESSION, "end_session"),
        (_WELCOME_BEGIN, "welcome_begin"), (_WELCOME_TAKE_ATTENDANCE, "welcome_take_attendance"),
        (_WELCOME_SEE_SUMMARY, "welcome_see_summary"), (_WELCOME_GO_TO_DASHBOARD, "welcome_go_to_dashboard"),
        (_STATION_TOGGLE_CAPTURE, "station_toggle_capture"), (_STATION_RECORD_ANSWER, "station_record_answer"),
    ):
        if rx.match(tl):
            return {"intent": intent, "params": {}}

    if _START_RECORDING.match(tl):
        return {"intent": "start_recording", "params": {"type": "video" if "video" in tl else "audio"}}
    if _STOP_RECORDING.match(tl):
        return {"intent": "stop_recording", "params": {"type": "video" if "video" in tl else "audio"}}

    if _LEADS_WITH_EXPORT_VERB.match(tl):
        return {"intent": "download_pdf", "params": {}}

    view_remainder = None
    m = _LEADS_WITH_VIEW_VERB.match(t)
    if m:
        view_remainder = t[m.end():]
    else:
        m = _LEADS_WITH_VIEW_VERB_FROM.match(t)
        if m:
            view_remainder = m.group("rest")
    if view_remainder is not None and not _SESSION_SEARCH_SIGNAL.search(view_remainder):
        vrl = view_remainder.lower()
        for tab, keywords in _TAB_KEYWORDS.items():
            if any(kw in vrl for kw in keywords):
                return {"intent": "view_tab", "params": {"output": tab}}

    if _LEADS_WITH_CREATE_STATION.match(t):
        name = _extract_station(t)
        if name:
            return {"intent": "create_station", "params": {"station": name}}
    if _LEADS_WITH_START_STATION.match(t) or _MENTIONS_OPEN_STATION_THEN_START.search(t):
        name = _extract_station(t)
        if name:
            return {"intent": "start_station_capture", "params": {"station": name}}
    if _LEADS_WITH_STOP_STATION.match(t):
        name = _extract_station(t)
        if name:
            return {"intent": "stop_station_capture", "params": {"station": name}}

    for rx in (_ASSIGN_A, _ASSIGN_B, _ASSIGN_C):
        m = rx.match(t)
        if m:
            which = _normalize_which(m.group("which"))
            station = m.group("station").strip()
            if which is not None and station:
                return {"intent": "assign_question_to_station", "params": {"station": station, "which": which}}

    m = _APPROVE_REJECT.match(t)
    if m:
        which = _normalize_which(m.group("rest"))
        if which is not None:
            intent = "approve_question" if m.group(1).lower() == "approve" else "reject_question"
            return {"intent": intent, "params": {"which": which}}

    if _AUTO_CAPTURE_ANY.search(t):
        if _AUTO_CAPTURE_OFF_VERB.search(t):
            return {"intent": "set_auto_capture", "params": {"seconds": 0}}
        sm = _SECONDS_RE.search(t)
        if sm:
            n = int(sm.group(1))
            seconds = min(_VALID_SECONDS, key=lambda v: abs(v - n))
            return {"intent": "set_auto_capture", "params": {"seconds": seconds}}

    m = _LEADS_WITH_GENERATE_VERB.match(t)
    if m:
        remainder = t[m.end():]
        rl = remainder.lower()
        intent = None
        for kw, iv in _GENERATE_KEYWORDS:
            if kw in rl:
                intent = iv
                break
        if intent is not None:
            params: dict = {}
            if intent == "generate_practice_questions":
                cm = _COUNT_RE.search(remainder)
                if cm:
                    params["count"] = int(cm.group(1))
                gm = _GRADE_RE.search(remainder)
                if gm:
                    params["grade"] = f"Grade {gm.group(1) or gm.group(2)}"
                for subj_kw, subj_label in _SUBJECT_MAP.items():
                    if subj_kw in rl:
                        params["subject"] = subj_label
                        break
                tm = _TOPIC_RE.search(remainder)
                if tm:
                    params["topic"] = tm.group(1).strip().title()
            return {"intent": intent, "params": params}

    return None


def _apply_verb_override(transcript: str, result: dict) -> dict:
    """
    Deterministic safety net for the one ambiguity the local model keeps
    getting wrong: a bare "open <topic>" with no other creation verb, where
    a textbook-sounding topic (e.g. "Newton's laws of motion") pulls a
    small model toward create_session even with matching few-shot examples
    in the prompt. The verb is a hard rule, not a judgment call, so enforce
    it in code rather than continuing to fight it with more examples.
    """
    t = _strip_filler(transcript)

    if (
        result["intent"] == "create_session"
        and _LEADS_WITH_OPEN.match(t)
        and not _SOUNDS_LIKE_NEW_SESSION.search(t)
    ):
        logger.info("Voice intent: verb override create_session -> open_session for %r", transcript)
        return {**result, "intent": "open_session"}

    # Same idea for "export/download/save/print the quiz" landing on
    # generate_quiz — the noun overlaps with a generate_* example ("the
    # quiz") even though the verb clearly means save-the-existing-one, not
    # build-new-content.
    if result["intent"] in (_GENERATE_INTENTS | {"view_tab"}) and _LEADS_WITH_EXPORT_VERB.match(t):
        logger.info("Voice intent: verb override %s -> download_pdf for %r", result["intent"], transcript)
        return {"intent": "download_pdf", "params": {}}

    # Same idea again for "show me the session report" / "go to the
    # absorption map" — a viewing verb landing on the matching generate_*
    # intent instead of view_tab, the newer generate_* intents (added after
    # the original create_session/download_pdf overrides above) being the
    # ones most likely to pull a small model this way since they're each
    # backed by only 1-2 few-shot examples.
    if result["intent"] in _GENERATE_INTENTS and _LEADS_WITH_VIEW_VERB.match(t):
        tab = _TAB_BY_GENERATE_INTENT.get(result["intent"])
        if tab:
            logger.info("Voice intent: verb override %s -> view_tab(%s) for %r", result["intent"], tab, transcript)
            return {"intent": "view_tab", "params": {"output": tab}}

    return result


async def classify_intent(
    transcript: str,
    *,
    ollama_base_url: str,
    ollama_model: str,
    openai_api_key: str,
    timeout_sec: int = 15,
    local_enabled: bool = True,
) -> dict:
    """
    Returns {"intent": str, "params": dict, "source": "local"|"cloud"|"deterministic"|"none"}.
    Tries a zero-network deterministic classifier first for the many intents
    that are simple closed verb+keyword patterns (see _classify_deterministic
    above), then the local model (unless local_enabled is False — e.g. on
    hardware too slow to prefill the system prompt inside timeout_sec, where
    trying local first just wastes the full timeout before falling back
    anyway), falls back to OpenAI, and finally returns intent="unknown" if
    both fail.
    """
    transcript = (transcript or "").strip()
    if not transcript:
        return {"intent": "unknown", "params": {}, "source": "none"}

    if _BARE_RESUME.match(_strip_filler(transcript)):
        logger.info("Voice intent (bare-resume fast path): %r -> start_teaching", transcript)
        return {"intent": "start_teaching", "params": {}, "source": "local"}

    det_result = _classify_deterministic(transcript)
    if det_result is not None:
        logger.info("Voice intent (deterministic): %r -> %s", transcript, det_result)
        return {**det_result, "source": "deterministic"}

    local_result = (
        await _classify_local(transcript, ollama_base_url, ollama_model, timeout_sec)
        if local_enabled else None
    )
    if local_result is not None:
        local_result = _apply_verb_override(transcript, local_result)
        logger.info("Voice intent (local): %r -> %s", transcript, local_result)
        return {**local_result, "source": "local"}

    if openai_api_key:
        cloud_result = await _classify_cloud(transcript, openai_api_key, timeout_sec)
        if cloud_result is not None:
            cloud_result = _apply_verb_override(transcript, cloud_result)
            logger.info("Voice intent (cloud fallback): %r -> %s", transcript, cloud_result)
            return {**cloud_result, "source": "cloud"}

    logger.warning("Voice intent: both local and cloud classification failed for %r", transcript)
    return {"intent": "unknown", "params": {}, "source": "none"}
