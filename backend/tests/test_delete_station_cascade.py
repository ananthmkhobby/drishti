import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from app.models.practice_question import PracticeQuestion
from app.models.practice_station import PracticeStation
from app.models.practice_attempt import PracticeAttempt
from app.models.practice_tutor_message import PracticeTutorMessage
from tests.conftest import TEACHER_ID, CLASSROOM_ID


@pytest.mark.asyncio
async def test_delete_station_cascades_attempts_and_blobs(client: AsyncClient, db: AsyncSession):
    session = Session(
        teacher_id=uuid.UUID(TEACHER_ID),
        classroom_id=uuid.UUID(CLASSROOM_ID),
        subject="Physics",
        grade="Grade 9",
        board_type="chalkboard",
        capture_mode="time_based",
        capture_interval_sec=30,
        status="active",
    )
    db.add(session)
    await db.flush()

    question = PracticeQuestion(session_id=session.id, text="2 + 2 = ?")
    db.add(question)
    await db.flush()

    station = PracticeStation(
        session_id=session.id, label="Desk 1", capture_interval_sec=10, status="idle",
    )
    db.add(station)
    await db.flush()

    # Fake stored files, standing in for what storage_service would have written.
    image_path = "/tmp/aci-test-uploads/test_attempt_image.jpg"
    audio_path = "/tmp/aci-test-uploads/test_attempt_audio.webm"
    Path(image_path).parent.mkdir(parents=True, exist_ok=True)
    Path(image_path).write_bytes(b"fake-image")
    Path(audio_path).write_bytes(b"fake-audio")

    attempt = PracticeAttempt(
        question_id=question.id,
        session_id=session.id,
        station_id=station.id,
        input_type="image",
        image_path=image_path,
        audio_path=audio_path,
        status="complete",
    )
    db.add(attempt)

    # A tutor-conversation turn's image — same "blob on disk, row in DB"
    # shape as an attempt's image, so it needs the same cascade-cleanup
    # coverage (added alongside PracticeTutorMessage itself).
    tutor_image_path = "/tmp/aci-test-uploads/test_tutor_image.jpg"
    Path(tutor_image_path).write_bytes(b"fake-tutor-image")
    tutor_msg = PracticeTutorMessage(
        station_id=station.id, question_id=question.id, role="student",
        text="I don't get this step", image_path=tutor_image_path, had_image=True,
    )
    db.add(tutor_msg)
    await db.commit()

    attempt_id = attempt.id
    tutor_msg_id = tutor_msg.id
    station_id = station.id

    assert Path(image_path).exists()
    assert Path(audio_path).exists()
    assert Path(tutor_image_path).exists()

    r = await client.delete(f"/v1/practice-stations/{station_id}")
    assert r.status_code == 204

    assert await db.get(PracticeAttempt, attempt_id) is None
    assert await db.get(PracticeTutorMessage, tutor_msg_id) is None
    assert await db.get(PracticeStation, station_id) is None
    assert not Path(image_path).exists()
    assert not Path(audio_path).exists()
    assert not Path(tutor_image_path).exists()

    # Idempotent: deleting again is a no-op, not a 404/500.
    r2 = await client.delete(f"/v1/practice-stations/{station_id}")
    assert r2.status_code == 204
