import os
import gc
import tempfile
import time
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import Database
from backend.services.security import ensure_admin_user, session_manager
import backend.main as main_module


@pytest.fixture
def stress_client():
    """Sets up an isolated database for concurrency stress testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name

    test_db = Database(temp_db_path)
    ensure_admin_user(test_db)
    original_db = main_module.db
    main_module.db = test_db

    client = TestClient(app)
    token = session_manager.create_session({"id": 1, "username": "admin", "display_name": "Administrator", "role": "admin"})
    admin_headers = {"Authorization": f"Bearer {token}"}

    yield client, admin_headers, test_db

    main_module.db = original_db
    del test_db
    del client
    gc.collect()
    try:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)
    except PermissionError:
        pass


def test_concurrent_student_submissions_50_users(stress_client):
    """
    Simulates 50 students submitting exams concurrently.
    Verifies that all 50 submissions succeed without database locking or connection starvation.
    """
    client, admin_headers, _ = stress_client
    deadline = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    # 1. Create a test exam with 3 questions
    create_res = client.post(
        "/api/exams",
        headers=admin_headers,
        json={
            "title": "Concurrency Stress Test Exam",
            "subject": "Mathematics",
            "duration_minutes": 60,
            "deadline": deadline,
            "questions": [
                {"question_text": "What is 2 + 2?", "marks": 2.0},
                {"question_text": "Differentiate x^2 with respect to x.", "marks": 3.0},
                {"question_text": "Integrate 2x dx from 0 to 5.", "marks": 5.0}
            ]
        }
    )
    assert create_res.status_code == 200, create_res.text
    exam_data = create_res.json()
    exam_code = exam_data["exam_code"]
    questions = exam_data["questions"]

    # 2. Concurrently submit 50 unique students
    num_students = 50

    def submit_student(idx):
        roll_no = f"STRESS-{idx:03d}"
        payload = {
            "roll_number": roll_no,
            "student_name": f"Stress Student {idx}",
            "section": f"Section {chr(65 + (idx % 4))}",
            "time_taken_seconds": 120 + (idx * 2),
            "answers": [
                {"question_id": questions[0]["id"], "typed_answer": f"Answer 4 from student {idx}", "image_data": ""},
                {"question_id": questions[1]["id"], "typed_answer": f"2x from student {idx}", "image_data": ""},
                {"question_id": questions[2]["id"], "typed_answer": f"25 from student {idx}", "image_data": ""}
            ]
        }
        start = time.perf_counter()
        resp = client.post(f"/api/exams/{exam_code}/submit", json=payload)
        duration = time.perf_counter() - start
        return idx, resp.status_code, resp.json() if resp.status_code == 200 else resp.text, duration

    start_all = time.perf_counter()
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(submit_student, i) for i in range(1, num_students + 1)]
        for f in as_completed(futures):
            results.append(f.result())
    total_time = time.perf_counter() - start_all

    # 3. Analyze results
    success_count = sum(1 for r in results if r[1] == 200)
    status_codes = [r[1] for r in results]
    avg_duration = sum(r[3] for r in results) / len(results)

    print(f"\n[Stress Test] 50 Concurrent Submissions completed in {total_time:.2f}s (avg latency: {avg_duration*1000:.1f}ms per request)")
    assert success_count == num_students, f"Expected {num_students} successful submissions, got {success_count}. Status codes: {status_codes}"

    # 4. Verify all 50 are recorded in exam submissions list
    subs_res = client.get(f"/api/exams/{exam_data['id']}/submissions", headers=admin_headers)
    assert subs_res.status_code == 200
    assert subs_res.json()["total"] == 50


def test_concurrent_duplicate_roll_number_race_condition(stress_client):
    """
    Simulates rapid simultaneous duplicate submissions with the exact same roll number.
    Only exactly one submission must succeed; the rest must fail with HTTP 400 (duplicate entry).
    """
    client, admin_headers, _ = stress_client
    deadline = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    create_res = client.post(
        "/api/exams",
        headers=admin_headers,
        json={
            "title": "Race Condition Test Exam",
            "subject": "Physics",
            "duration_minutes": 30,
            "deadline": deadline,
            "questions": [{"question_text": "Speed of sound?", "marks": 5.0}]
        }
    )
    assert create_res.status_code == 200
    exam_data = create_res.json()
    exam_code = exam_data["exam_code"]
    q_id = exam_data["questions"][0]["id"]

    same_roll = "RACE-COND-999"

    def submit_duplicate(attempt_id):
        payload = {
            "roll_number": same_roll,
            "student_name": f"Clone {attempt_id}",
            "time_taken_seconds": 60,
            "answers": [{"question_id": q_id, "typed_answer": f"Clone {attempt_id} answer", "image_data": ""}]
        }
        resp = client.post(f"/api/exams/{exam_code}/submit", json=payload)
        return resp.status_code

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(submit_duplicate, i) for i in range(5)]
        codes = [f.result() for f in as_completed(futures)]

    # Exactly one must succeed (200), and exactly four must be rejected (400)
    assert codes.count(200) == 1, f"Expected exactly 1 success, got: {codes}"
    assert codes.count(400) == 4, f"Expected 4 duplicate rejections, got: {codes}"


def test_concurrent_reads_and_writes_under_load(stress_client):
    """
    Verifies that reading questions and exam statuses while student submissions are in-flight
    does not cause SQLite 'database is locked' errors or starvation.
    """
    client, admin_headers, _ = stress_client
    deadline = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    create_res = client.post(
        "/api/exams",
        headers=admin_headers,
        json={
            "title": "Read-Write Stress Exam",
            "subject": "Biology",
            "duration_minutes": 45,
            "deadline": deadline,
            "questions": [{"question_text": "Function of mitochondria?", "marks": 5.0}]
        }
    )
    exam_data = create_res.json()
    exam_code = exam_data["exam_code"]
    q_id = exam_data["questions"][0]["id"]

    def read_op():
        return client.get("/api/questions?limit=20").status_code

    def write_op(idx):
        payload = {
            "roll_number": f"RW-LOAD-{idx}",
            "student_name": f"RW Student {idx}",
            "time_taken_seconds": 45,
            "answers": [{"question_id": q_id, "typed_answer": "Energy powerhouse", "image_data": ""}]
        }
        return client.post(f"/api/exams/{exam_code}/submit", json=payload).status_code

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for i in range(15):
            futures.append(executor.submit(write_op, i))
            futures.append(executor.submit(read_op))
        statuses = [f.result() for f in as_completed(futures)]

    # All read and write operations should return 200 without lock errors
    assert all(s == 200 for s in statuses), f"Some requests failed during RW load: {statuses}"
