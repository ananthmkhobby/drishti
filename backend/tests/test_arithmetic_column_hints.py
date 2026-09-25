"""
Tests for column-level arithmetic pinpointing — added 2026-09-24 so a
carry/borrow error can be circled at the actual digit instead of the
whole line. Two independent pieces:
  - practice_engine.check_arithmetic_step / check_bare_expression_equality:
    deterministic (sympy + digit comparison, no LLM) column_hint detection
    for the simplest, most literal "a op b = c" shapes.
  - practice_engine.locate_arithmetic_column: turns a semantic column name
    ("ones"/"tens"/...) into an actual pixel bbox via digit segmentation,
    given a real photo — this is the part that must NOT ask an LLM for
    per-digit coordinates (vision models are weak at exactly that).
  - practice_service._parse_column_hint: validates an LLM-proposed
    column_hint against the known row/column vocabulary before trusting it.
"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.ocr import practice_engine
from app.services import practice_service


class TestDeterministicColumnHint:
    def test_addition_carry_error_pinpoints_the_ones_column(self):
        # 47 + 38 = 85, but written as 75 — the ones digit (5) is right,
        # tens digit (7) is wrong — so this specific example actually
        # diverges at TENS, not ones. Use a case that diverges at ones.
        result = practice_engine.check_arithmetic_step("47+38=84")
        assert result["verdict"] == "arithmetic_error"
        assert result["column_hint"] == {"row": "answer", "column": "ones"}

    def test_addition_error_further_left_pinpoints_tens(self):
        # Correct is 85; written 95 — ones digit (5) matches, tens (9 vs 8) doesn't.
        result = practice_engine.check_arithmetic_step("47+38=95")
        assert result["verdict"] == "arithmetic_error"
        assert result["column_hint"] == {"row": "answer", "column": "tens"}

    def test_subtraction_borrow_error(self):
        # 52 - 38 = 14; written as 24 — ones digit (4) matches, tens wrong.
        result = practice_engine.check_arithmetic_step("52-38=24")
        assert result["verdict"] == "arithmetic_error"
        assert result["column_hint"] == {"row": "answer", "column": "tens"}

    def test_correct_answer_has_no_column_hint_at_all(self):
        result = practice_engine.check_arithmetic_step("47+38=85")
        assert result["verdict"] == "arithmetically_valid"
        assert "column_hint" not in result

    def test_non_simple_expression_gets_no_column_hint(self):
        # A closed equation, but not the plain "a op b = c" shape the
        # regex targets — should still detect the error, just without the
        # extra column precision.
        result = practice_engine.check_arithmetic_step("2*3+4=11")
        assert result["verdict"] == "arithmetic_error"
        assert "column_hint" not in result

    def test_bare_expression_equality_also_gets_column_hint(self):
        # "47+38" on one line, "84" (wrong) on the next — the split-across-
        # two-lines pattern, same underlying digit-comparison logic.
        result = practice_engine.check_bare_expression_equality("47+38", "84")
        assert result["verdict"] == "arithmetic_error"
        assert result["column_hint"] == {"row": "answer", "column": "ones"}

    def test_run_gate_d_carries_column_hint_through(self):
        # The full Gate D dispatcher (run_gate_d) must preserve column_hint
        # exactly like it already preserves step_index.
        result = practice_service.run_gate_d(["47+38=84"], None)
        assert result["verdict"] == "arithmetic_error"
        assert result["column_hint"] == {"row": "answer", "column": "ones"}
        assert result["step_index"] == 0


class TestLocateArithmeticColumn:
    def _digit_line_image(self, text: str, width=600, height=150) -> np.ndarray:
        """A synthetic line of well-separated 'digits' (rectangles standing
        in for handwritten strokes) so column segmentation has something
        real and unambiguous to work with, without depending on an actual
        font rendering a specific digit shape."""
        img = np.full((height, width, 3), 255, dtype=np.uint8)
        n = len(text)
        slot_w = width // (n + 1)
        for i in range(n):
            cx = slot_w * (i + 1)
            cv2.rectangle(img, (cx - 15, 40), (cx + 15, 110), (0, 0, 0), -1)
        return img

    def test_locates_the_rightmost_digit_as_ones(self):
        img = self._digit_line_image("47")  # two digit-blocks: tens, ones
        step_bbox = [0.0, 0.0, 1000.0, 1000.0]
        result = practice_engine.locate_arithmetic_column(img, step_bbox, "ones")
        assert result is not None
        # The "ones" block is the rightmost — its center should be in the
        # right half of the image.
        cx = (result[0] + result[2]) / 2
        assert cx > 500

    def test_locates_tens_to_the_left_of_ones(self):
        img = self._digit_line_image("47")
        step_bbox = [0.0, 0.0, 1000.0, 1000.0]
        ones = practice_engine.locate_arithmetic_column(img, step_bbox, "ones")
        tens = practice_engine.locate_arithmetic_column(img, step_bbox, "tens")
        assert ones is not None and tens is not None
        assert tens[0] < ones[0]  # tens column starts further left than ones

    def test_column_beyond_what_was_detected_returns_none(self):
        img = self._digit_line_image("7")  # one digit only
        step_bbox = [0.0, 0.0, 1000.0, 1000.0]
        assert practice_engine.locate_arithmetic_column(img, step_bbox, "tens") is None

    def test_decimal_columns_are_not_handled_yet(self):
        img = self._digit_line_image("47")
        step_bbox = [0.0, 0.0, 1000.0, 1000.0]
        assert practice_engine.locate_arithmetic_column(img, step_bbox, "tenths") is None

    def test_blank_region_returns_none(self):
        img = np.full((150, 600, 3), 255, dtype=np.uint8)
        step_bbox = [0.0, 0.0, 1000.0, 1000.0]
        assert practice_engine.locate_arithmetic_column(img, step_bbox, "ones") is None

    def test_never_raises_on_a_degenerate_bbox(self):
        img = self._digit_line_image("47")
        assert practice_engine.locate_arithmetic_column(img, [0, 0, 0, 0], "ones") is None


class TestParseColumnHint:
    def test_accepts_a_valid_row_and_column(self):
        assert practice_service._parse_column_hint({"row": "answer", "column": "tens"}) == {
            "row": "answer", "column": "tens",
        }

    def test_rejects_an_unknown_row(self):
        assert practice_service._parse_column_hint({"row": "diagonal", "column": "tens"}) is None

    def test_rejects_an_unknown_column(self):
        assert practice_service._parse_column_hint({"row": "answer", "column": "millions"}) is None

    def test_rejects_a_non_dict(self):
        assert practice_service._parse_column_hint("tens") is None
        assert practice_service._parse_column_hint(None) is None
