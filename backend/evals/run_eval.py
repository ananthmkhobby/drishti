"""
Live grading eval: runs each golden case through the REAL validate_step
(Gate D + the subject/grade-calibrated LLM validation + library candidates)
and prints per-subject / per-grade-band results. Costs real OpenAI calls.

    cd backend && .venv/bin/python -m evals.run_eval            # all cases
    cd backend && .venv/bin/python -m evals.run_eval --show-fail

Uses the shipped library seed directly (no database needed).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib

from app.config import get_settings
from app.data.misconception_seed import MISCONCEPTION_SEED
from app.models.practice_question import PracticeQuestion
from app.ocr.practice_engine import _normalize_subject_key
from app.services import misconception_library as lib
from app.services.practice_service import run_gate_d, validate_step
from evals.scoring import score_one, summarise

CASES = pathlib.Path(__file__).with_name("golden_cases.json")


async def run_case(case: dict, settings) -> dict:
    steps = [{"text": t} for t in case["steps"]]
    question = PracticeQuestion(
        session_id=None, text=case["question"], subject=case["subject"], topic=case["topic"],
        answer_domain=case["answer_domain"], final_answer={"text": case["final_answer"]},
    )
    key = _normalize_subject_key(case["subject"])
    candidates = lib.rank_candidates(
        MISCONCEPTION_SEED, lib.library_subject_keys(key, case["subject"]), case["grade"],
        f"{case['topic']} {case['question']}",
    )
    pred = await validate_step(
        question, steps, run_gate_d(case["steps"], None),
        ollama_base_url=settings.ollama_base_url, ollama_model=settings.ollama_brain_model,
        openai_api_key=settings.openai_api_key or "", local_enabled=False,
        diagram_context=case.get("diagram_context"),
        grade_band=lib.grade_band(case["grade"]), library_misconceptions=candidates,
    )
    return {"case": case, "pred": pred}


def _fmt(name: str, s: dict) -> str:
    code = "n/a" if s["code_acc"] is None else f"{s['code_acc']:.0%} ({s['code_n']})"
    return (f"{name:<12} n={s['n']:<3} status={s['status_acc']:.0%}  false-accuse={s['false_accusations']}  "
            f"missed={s['missed_errors']}  forbidden={s['forbidden_hits']}  abstain={s['abstain_rate']:.0%}  code={code}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show-fail", action="store_true")
    args = ap.parse_args()
    settings = get_settings()
    data = json.loads(CASES.read_text())
    results = await asyncio.gather(*(run_case(c, settings) for c in data["cases"]))
    print(f"label source: {data['label_source']}\n")
    summary = summarise(results)
    print(_fmt("OVERALL", summary["overall"]))
    for k, v in summary["by_subject"].items():
        print(_fmt(k, v))
    for k, v in summary["by_band"].items():
        print(_fmt(f"band:{k}", v))
    if args.show_fail:
        print("\nFAILURES")
        for r in results:
            sc = score_one(r["case"], r["pred"])
            if not sc["status_ok"] or (sc["code_applicable"] and not sc["code_ok"]):
                print(f"- {r['case']['id']}: got {r['pred']['validation_status']} / {r['pred'].get('misconception_code')} "
                      f"/ {r['pred'].get('reason_code')}  (expected {r['case']['expected_status']} / {r['case'].get('expected_misconception')})")


if __name__ == "__main__":
    asyncio.run(main())
