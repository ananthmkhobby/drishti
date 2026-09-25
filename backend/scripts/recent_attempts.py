#!/usr/bin/env python3
"""
Prints the most recent Guided Practice attempts with full diagnostic detail
(what the vision model actually read, what it decided, and why) — for
debugging accuracy reports without wrestling with SSH quoting.

Usage (on the Pi):
  cd ~/aci/backend && .venv/bin/python scripts/recent_attempts.py [N]
  (N = how many to show, default 8)
"""
import sqlite3
import sys

n = int(sys.argv[1]) if len(sys.argv) > 1 else 8

conn = sqlite3.connect("dev.db")
rows = conn.execute(
    "SELECT attempt_no, recognized_steps, validation_status, validation_reason_code, "
    "student_state, hint_level, hint_text, recognition_confidence, gate_d_result, created_at "
    "FROM practice_attempts ORDER BY created_at DESC LIMIT ?",
    (n,),
).fetchall()

if not rows:
    print("No attempts found.")

for r in rows:
    attempt_no, recognized_steps, validation_status, reason, state, hint_level, hint_text, conf, gate_d, created = r
    print(f"--- attempt #{attempt_no} ({created}) ---")
    print(f"  recognized_steps: {recognized_steps}")
    print(f"  recognition_confidence: {conf}")
    print(f"  gate_d_result: {gate_d}")
    print(f"  validation_status: {validation_status}  |  reason: {reason}")
    print(f"  student_state: {state}  |  hint_level: {hint_level}")
    print(f"  hint_text: {hint_text}")
    print()
