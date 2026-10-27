"""
Pure scoring for the grading eval — no LLM, no network, fully unit-testable.

A result is {"case": <golden case dict>, "pred": <validate_step output dict>}.
Metrics are reported per slice (subject, grade band) and overall:
  status_ok          prediction is an acceptable status and not a forbidden one
  false_accusation   case is correct work but the grader called it a mistake
                     (the failure that hurts a student most)
  missed_error       case is a real mistake but the grader called it fine
  code_ok / code_n   among cases with an expected library code where the
                     grader said conceptual_misconception: did it pick it?
  abstain            grader said "ambiguous" (not a failure; asking is safe)
Small n per slice means wide uncertainty — treat these as a regression
signal and a map of weak spots, not a precision claim.
"""
from __future__ import annotations

from collections import defaultdict

CORRECT_STATUSES = {"solved", "valid_progress", "alternative_valid_method"}
MISTAKE_STATUSES = {"arithmetic_slip", "conceptual_misconception", "unsupported"}


def grade_band(grade: int) -> str:
    return "early" if grade <= 3 else "middle" if grade <= 7 else "senior"


def score_one(case: dict, pred: dict) -> dict:
    status = pred.get("validation_status")
    expected = set(case["expected_status"])
    forbidden = set(case.get("forbidden_status", []))
    expects_correct = bool(expected & CORRECT_STATUSES) and not (expected & MISTAKE_STATUSES)
    expects_mistake = bool(expected & MISTAKE_STATUSES) and not (expected & CORRECT_STATUSES)
    code_expected = case.get("expected_misconception")
    code_applicable = bool(code_expected) and status == "conceptual_misconception"
    return {
        "status_ok": status in expected and status not in forbidden,
        "false_accusation": expects_correct and status in MISTAKE_STATUSES,
        "missed_error": expects_mistake and status in CORRECT_STATUSES,
        "forbidden_hit": status in forbidden,
        "abstain": status == "ambiguous",
        "code_applicable": code_applicable,
        "code_ok": code_applicable and pred.get("misconception_code") == code_expected,
    }


def _summarise(rows: list[dict]) -> dict:
    n = len(rows)
    code_n = sum(r["code_applicable"] for r in rows)
    return {
        "n": n,
        "status_acc": sum(r["status_ok"] for r in rows) / n if n else 0.0,
        "false_accusations": sum(r["false_accusation"] for r in rows),
        "missed_errors": sum(r["missed_error"] for r in rows),
        "forbidden_hits": sum(r["forbidden_hit"] for r in rows),
        "abstain_rate": sum(r["abstain"] for r in rows) / n if n else 0.0,
        "code_n": code_n,
        "code_acc": (sum(r["code_ok"] for r in rows) / code_n) if code_n else None,
    }


def summarise(results: list[dict]) -> dict:
    scored = [(r["case"], score_one(r["case"], r["pred"])) for r in results]
    out = {"overall": _summarise([s for _, s in scored]), "by_subject": {}, "by_band": {}}
    groups_s, groups_b = defaultdict(list), defaultdict(list)
    for case, s in scored:
        groups_s[case["subject"]].append(s)
        groups_b[grade_band(case["grade"])].append(s)
    out["by_subject"] = {k: _summarise(v) for k, v in sorted(groups_s.items())}
    out["by_band"] = {k: _summarise(v) for k, v in sorted(groups_b.items())}
    return out
