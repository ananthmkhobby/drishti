#!/usr/bin/env python3
"""
Measures real voice-command and OCR/vision performance against a running
ACI backend (intended to run ON the Pi, against its own localhost:8000).

Voice commands: hits /v1/voice/classify-intent (text-in, intent-out — skips
audio/microphone entirely) for every intent the app supports, and /v1/voice/ask
for the Classroom Brain path. Each response already reports which model
answered ("local" | "cloud" | "none") and this script times the full
round-trip, so this measures exactly what matters: does it work, how fast,
and which model.

Whisper transcription is NOT re-tested here — deliberately. Whether
whisper-server exists is a yes/no infrastructure fact (checked separately via
`systemctl status whisper-server`), not something worth timing per-call.

OCR/vision: reads the REAL, already-stored latency_ms_breakdown from recent
ThinkStep practice_attempts rows (genuine production captures, not synthetic
timing noise) — no new API calls made for this part.

Usage (on the Pi):
  cd ~/aci/backend && .venv/bin/python scripts/measure_voice_and_ocr.py
"""
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("ACI_BASE_URL", "http://localhost:8000/v1")

# (intent, representative transcript) — phrasing matches the classifier's own
# few-shot examples where one exists, so this measures realistic accuracy.
VOICE_COMMANDS = [
    ("start_camera", "Start the camera"),
    ("stop_camera", "Stop the camera"),
    ("capture_frame", "Take a photo of the board"),
    ("reprocess_ocr", "Reprocess that photo"),
    ("start_recording", "Start recording the audio"),
    ("stop_recording", "Stop recording"),
    ("generate_notes", "Generate my notes now"),
    ("generate_quiz", "Make a quiz from today's class"),
    ("generate_summary", "Summarize today's class"),
    ("generate_experiments", "Suggest some experiments for this topic"),
    ("view_tab", "Take me to the opportunities page"),
    ("open_session", "Open the quiz from my physics class"),
    ("create_session", "Start a new physics class for grade 8"),
    ("delete_session", "Delete my physics class"),
    ("end_session", "End the session"),
    ("download_pdf", "Download this as a PDF"),
    ("ask_question", "Explain photosynthesis simply"),
]

ASK_QUESTIONS = [
    "What should I teach next?",
    "Give me a real life example of non-uniform motion",
]


def _post(path: str, payload: dict) -> tuple[dict | None, float, int]:
    url = f"{BASE}{path}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read())
            return body, time.monotonic() - t0, resp.status
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()[:200]}, time.monotonic() - t0, e.code
    except Exception as e:
        return {"error": str(e)}, time.monotonic() - t0, 0


def measure_voice():
    print("=" * 100)
    print("VOICE COMMAND INTENT CLASSIFICATION  (text-in -> intent-out, no audio — isolates model latency/source)")
    print("=" * 100)
    print(f"{'expected_intent':<22}{'transcript':<42}{'got':<22}{'source':<8}{'ms':>8}  ok")
    print("-" * 106)
    results = []
    for expected, transcript in VOICE_COMMANDS:
        body, elapsed, status = _post("/voice/classify-intent", {"transcript": transcript})
        got = body.get("intent", "ERROR") if body else "ERROR"
        source = body.get("source", "-") if body else "-"
        ok = "YES" if got == expected else "NO"
        ms = round(elapsed * 1000)
        results.append({"expected": expected, "got": got, "source": source, "ms": ms, "ok": got == expected, "status": status})
        print(f"{expected:<22}{transcript[:40]:<42}{got:<22}{source:<8}{ms:>8}  {ok}")

    correct = sum(1 for r in results if r["ok"])
    local_n = sum(1 for r in results if r["source"] == "local")
    cloud_n = sum(1 for r in results if r["source"] == "cloud")
    none_n = sum(1 for r in results if r["source"] == "none")
    avg_ms = round(sum(r["ms"] for r in results) / len(results)) if results else 0
    print("-" * 106)
    print(f"Accuracy: {correct}/{len(results)}   Source: local={local_n} cloud={cloud_n} none={none_n}   Avg latency: {avg_ms}ms")
    print()
    return results


def measure_ask():
    print("=" * 100)
    print("CLASSROOM BRAIN (/voice/ask)")
    print("=" * 100)
    for q in ASK_QUESTIONS:
        body, elapsed, status = _post("/voice/ask", {"question": q})
        source = body.get("source", "-") if body else "-"
        answer = (body.get("answer") or body.get("error") or "")[:80] if body else ""
        print(f"[{round(elapsed*1000):>6}ms] source={source:<6} Q: {q}")
        print(f"           A: {answer}")
    print()


def measure_ocr_from_db():
    print("=" * 100)
    print("GUIDED PRACTICE OCR/VISION — real stored latency from recent captures (not a fresh test)")
    print("=" * 100)
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dev.db")
    if not os.path.exists(db_path):
        print(f"No dev.db found at {db_path} — skipping (this Pi may use Postgres instead).")
        return
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT capture_quality_status, recognition_confidence, validation_status, "
        "validation_reason_code, latency_ms_breakdown, created_at "
        "FROM practice_attempts WHERE status='complete' ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    if not rows:
        print("No completed practice_attempts rows yet — capture a few in Guided Practice first, then re-run this.")
        return

    gate_bc, gate_ef, gate_totals = [], [], []
    print(f"{'validation_status':<28}{'reason_code':<28}{'conf':>6}  gate_bc(vision)  gate_ef(validate)  total")
    print("-" * 100)
    for status, conf, vstatus, reason, latency_json, created in rows:
        lat = json.loads(latency_json) if latency_json else {}
        bc = lat.get("gate_bc_ms")
        ef = lat.get("gate_ef_ms")
        total = sum(v for v in lat.values() if isinstance(v, (int, float)))
        if bc:
            gate_bc.append(bc)
        if ef:
            gate_ef.append(ef)
        if total:
            gate_totals.append(total)
        conf_s = f"{conf:.2f}" if conf is not None else "-"
        print(f"{str(vstatus):<28}{str(reason or ''):<28}{conf_s:>6}  {str(bc):>13}ms  {str(ef):>15}ms  {round(total):>6}ms")

    def _avg(xs):
        return round(sum(xs) / len(xs)) if xs else None

    print("-" * 100)
    print(f"Vision extraction (Gate B/C) avg: {_avg(gate_bc)}ms over {len(gate_bc)} captures — this is the OpenAI GPT-4o vision call, always cloud (no local vision path exists in this app).")
    print(f"Solution validation (Gate E/F) avg: {_avg(gate_ef)}ms over {len(gate_ef)} captures — cloud-only by design (practice_local_llm_enabled=false) after a local-model accuracy issue found earlier.")
    print(f"Full pipeline avg: {_avg(gate_totals)}ms over {len(gate_totals)} captures.")
    print()


if __name__ == "__main__":
    print(f"Target: {BASE}\n")
    voice_results = measure_voice()
    measure_ask()
    measure_ocr_from_db()
    print("Done.")
