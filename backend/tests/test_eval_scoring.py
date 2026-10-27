from evals.scoring import score_one, summarise

CASE_MISTAKE = {"id": "a", "subject": "Mathematics", "grade": 5, "expected_status": ["conceptual_misconception"],
                "expected_misconception": "M-DEC-01", "forbidden_status": []}
CASE_OK = {"id": "b", "subject": "Mathematics", "grade": 2, "expected_status": ["solved", "valid_progress"],
           "expected_misconception": None, "forbidden_status": []}


def test_false_accusation_and_miss_are_distinct():
    assert score_one(CASE_OK, {"validation_status": "arithmetic_slip"})["false_accusation"]
    assert score_one(CASE_MISTAKE, {"validation_status": "solved"})["missed_error"]
    assert not score_one(CASE_OK, {"validation_status": "solved"})["false_accusation"]


def test_code_accuracy_only_counts_when_grader_called_a_misconception():
    hit = score_one(CASE_MISTAKE, {"validation_status": "conceptual_misconception", "misconception_code": "M-DEC-01"})
    assert hit["code_applicable"] and hit["code_ok"]
    wrong = score_one(CASE_MISTAKE, {"validation_status": "conceptual_misconception", "misconception_code": "M-FRAC-01"})
    assert wrong["code_applicable"] and not wrong["code_ok"]
    assert not score_one(CASE_MISTAKE, {"validation_status": "arithmetic_slip"})["code_applicable"]


def test_forbidden_status_fails_even_if_otherwise_acceptable():
    case = {**CASE_OK, "expected_status": ["solved", "conceptual_misconception"], "forbidden_status": ["conceptual_misconception"]}
    assert not score_one(case, {"validation_status": "conceptual_misconception"})["status_ok"]


def test_summarise_groups_by_subject_and_band():
    out = summarise([
        {"case": CASE_MISTAKE, "pred": {"validation_status": "conceptual_misconception", "misconception_code": "M-DEC-01"}},
        {"case": CASE_OK, "pred": {"validation_status": "arithmetic_slip"}},
    ])
    assert out["overall"]["n"] == 2 and out["overall"]["false_accusations"] == 1
    assert set(out["by_band"]) == {"early", "middle"} and set(out["by_subject"]) == {"Mathematics"}
