"""
Tests for practice_engine.auto_orient and refine_bbox — added 2026-09-24 in
response to reports that tilted/rotated captures scanned poorly and that
the mistake-circle didn't land on the actual handwriting. Both are
best-effort corrections layered in front of the vision calls; these tests
lock in the geometry (rotation direction, bbox coordinate math) rather than
re-testing Tesseract/OpenCV themselves.
"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.ocr import practice_engine


def _dense_text_image() -> np.ndarray:
    """A synthetic page with enough real text for Tesseract's OSD to have
    something to judge orientation from — a single word/short line isn't
    enough (confirmed empirically: OSD raises "too few characters")."""
    pytest.importorskip("pytesseract")
    PIL_Image = pytest.importorskip("PIL.Image")
    from PIL import ImageDraw, ImageFont

    img = PIL_Image.new("RGB", (1000, 700), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 28)
    except Exception:
        font = ImageFont.load_default()
    lines = [
        "The quick brown fox jumps over the lazy dog many times today.",
        "Photosynthesis converts carbon dioxide and water into glucose using light.",
        "A rotated photograph should still be readable after correction is applied.",
        "This paragraph contains enough characters for Tesseract OSD to work well.",
        "Guided practice questions test comprehension of classroom board content.",
    ]
    y = 40
    for line in lines:
        draw.text((40, y), line, fill="black", font=font)
        y += 60
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def _tesseract_osd_available() -> bool:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _tesseract_osd_available(), reason="tesseract binary not installed in this environment")
class TestAutoOrient:
    def test_upright_image_is_left_unchanged(self):
        img = _dense_text_image()
        corrected = practice_engine.auto_orient(img)
        assert corrected is img  # no-op returns the SAME object, not a copy

    @pytest.mark.parametrize("rotation,label", [
        (cv2.ROTATE_90_CLOCKWISE, "90cw"),
        (cv2.ROTATE_180, "180"),
        (cv2.ROTATE_90_COUNTERCLOCKWISE, "90ccw"),
    ])
    def test_rotated_image_is_corrected_back_to_upright_shape(self, rotation, label):
        img = _dense_text_image()
        rotated = cv2.rotate(img, rotation)
        corrected = practice_engine.auto_orient(rotated)
        # The corrected image should be right-side-up again — same shape as
        # the original (width/height swap back for the 90-degree cases).
        assert corrected.shape == img.shape, f"rotation={label}"


def test_auto_orient_never_raises_without_tesseract(monkeypatch):
    """however Tesseract/pytesseract is unavailable or fails, auto_orient
    must fall back to the original image rather than blocking the pipeline
    over a best-effort correction."""
    import sys
    monkeypatch.setitem(sys.modules, "pytesseract", None)  # force ImportError on `import pytesseract`
    img = np.zeros((50, 50, 3), dtype=np.uint8)
    result = practice_engine.auto_orient(img)
    assert result is img


class TestRefineBbox:
    def test_snaps_an_offset_guess_to_the_actual_ink_extent(self):
        canvas = np.full((400, 800, 3), 255, dtype=np.uint8)
        cv2.rectangle(canvas, (300, 150), (450, 200), (0, 0, 0), -1)  # the real ink block

        true_bbox = [300 / 800 * 1000, 150 / 400 * 1000, 450 / 800 * 1000, 200 / 400 * 1000]
        # A plausible but imprecise LLM guess, offset ~20px in each direction.
        guess_bbox = [
            (300 - 20) / 800 * 1000, (150 - 15) / 400 * 1000,
            (450 - 10) / 800 * 1000, (200 - 5) / 400 * 1000,
        ]

        refined = practice_engine.refine_bbox(canvas, guess_bbox)

        for got, want in zip(refined, true_bbox):
            assert abs(got - want) < 1.0

    def test_falls_back_to_original_bbox_on_a_blank_window(self):
        # Nothing ink-like anywhere near the guess — must not invent a box.
        canvas = np.full((400, 800, 3), 255, dtype=np.uint8)
        guess_bbox = [350.0, 337.5, 550.0, 487.5]
        assert practice_engine.refine_bbox(canvas, guess_bbox) == guess_bbox

    def test_never_raises_on_a_degenerate_bbox(self):
        canvas = np.full((100, 100, 3), 255, dtype=np.uint8)
        # Zero-area box right at the image edge.
        assert practice_engine.refine_bbox(canvas, [0, 0, 0, 0]) == [0, 0, 0, 0]


class TestApplyMountCorrection:
    """
    practice_engine.apply_mount_correction — the deterministic counterpart
    to auto_orient, for a station explicitly marked as desk-mounted
    (PracticeStation.camera_mount == "desk"): a camera looking straight
    down at the page from above. First implemented as 90°+mirror
    (2026-09-24); corrected the same day after live testing on the actual
    setup showed that was wrong and a plain 180° rotation is what's
    actually needed.
    """

    def test_front_mount_is_a_pure_no_op(self):
        img = np.random.randint(0, 255, (100, 200, 3), dtype=np.uint8)
        result = practice_engine.apply_mount_correction(img, "front")
        assert result is img  # same object, not even a copy

    def test_unknown_mount_value_is_also_a_no_op(self):
        img = np.random.randint(0, 255, (100, 200, 3), dtype=np.uint8)
        assert practice_engine.apply_mount_correction(img, "") is img
        assert practice_engine.apply_mount_correction(img, "ceiling") is img

    def test_desk_mount_rotates_180_degrees_with_no_mirror(self):
        img = np.random.randint(0, 255, (100, 200, 3), dtype=np.uint8)

        result = practice_engine.apply_mount_correction(img, "desk")
        expected = cv2.rotate(img, cv2.ROTATE_180)

        assert result.shape[:2] == (100, 200)  # 180° preserves width/height, unlike a 90° turn
        assert np.array_equal(result, expected)
        # A rotation, not a mirror — rotating the RESULT another 180° must
        # recover the original exactly. A reflection could never do this.
        assert np.array_equal(cv2.rotate(result, cv2.ROTATE_180), img)
