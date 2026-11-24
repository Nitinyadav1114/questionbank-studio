import os
import gc
import tempfile
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient

from backend.main import app, MAX_REQUEST_BODY_BYTES
from backend.database import Database
from backend.services.security import ensure_admin_user, session_manager
import backend.main as main_module


@pytest.fixture
def payload_client():
    """Sets up an isolated database for payload & edge-case stress testing."""
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


def test_massive_text_payload_and_unicode_symbols(payload_client):
    """
    Submits a 15,000-character essay with complex mathematical equations,
    foreign scripts (Hindi, Japanese, Arabic), emojis, and markdown.
    Verifies lossless persistence, retrieval, and grading.
    """
    client, admin_headers, _ = payload_client
    deadline = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    # 1. Create exam
    create_res = client.post(
        "/api/exams",
        headers=admin_headers,
        json={
            "title": "Complex Unicode & Massive Essay Exam",
            "subject": "Literature & Science",
            "duration_minutes": 60,
            "deadline": deadline,
            "questions": [{"question_text": "Write an extensive thesis.", "marks": 20.0}]
        }
    )
    assert create_res.status_code == 200
    exam_data = create_res.json()
    exam_code = exam_data["exam_code"]
    q_id = exam_data["questions"][0]["id"]

    # 2. Construct 15,000 char essay with rich characters
    base_paragraph = (
        "Quantum superposition states that |Ψ⟩ = α|0⟩ + β|1⟩ where |α|² + |β|² = 1. "
        "हिंदी अनुवाद: यह क्वांटम भौतिकी का एक महत्वपूर्ण सिद्धांत है। "
        "日本語: 量子力学の基本原理。 "
        "العربية: مبدأ ميكانيكا الكم الأساسي. "
        "Special symbols: ∑ ∫ ∬ ∭ ∮ ∂ ∇ √ ∛ ∜ ∞ ∧ ∨ ∩ ∪ ≠ ≤ ≥ ≈ ≡. "
        "Emojis: 🚀 🔬 💡 📚 🧪 🌟 🎯. "
    )
    massive_essay = (base_paragraph * 60)[:15000]
    assert len(massive_essay) == 15000

    submit_payload = {
        "roll_number": "UNICODE-101",
        "student_name": "Dr. Erwin Schrödinger 🐱",
        "section": "Theoretical Physics A*",
        "time_taken_seconds": 1800,
        "answers": [
            {
                "question_id": q_id,
                "typed_answer": massive_essay,
                "image_data": ""
            }
        ]
    }

    sub_res = client.post(f"/api/exams/{exam_code}/submit", json=submit_payload)
    assert sub_res.status_code == 200, sub_res.text
    sub_id = sub_res.json()["submission_id"]

    # 3. Retrieve submission details and verify text fidelity
    detail_res = client.get(f"/api/submissions/{sub_id}", headers=admin_headers)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    saved_answer = detail["answers"][0]["typed_answer"]
    assert len(saved_answer) == 15000
    assert saved_answer == massive_essay
    assert "हिंदी अनुवाद" in saved_answer
    assert "🚀 🔬 💡" in saved_answer


def test_malicious_script_injection_and_sql_injection_defense(payload_client):
    """
    Submits XSS attack vectors and SQL injection strings across student name,
    roll number, section, and typed answer fields.
    Verifies that fields are properly parameterized and do not break the database or API.
    """
    client, admin_headers, _ = payload_client
    deadline = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    create_res = client.post(
        "/api/exams",
        headers=admin_headers,
        json={
            "title": "Injection Resistance Exam",
            "subject": "Cybersecurity",
            "duration_minutes": 30,
            "deadline": deadline,
            "questions": [{"question_text": "Explain SQL injection.", "marks": 5.0}]
        }
    )
    exam_data = create_res.json()
    exam_code = exam_data["exam_code"]
    q_id = exam_data["questions"][0]["id"]

    xss_name = "<script>alert('xss_attack');</script>"
    sql_roll = "'; DROP TABLE exam_submissions; --"
    xss_answer = '"><img src=x onerror="alert(document.cookie)"> UNION SELECT * FROM users;'

    sub_res = client.post(
        f"/api/exams/{exam_code}/submit",
        json={
            "roll_number": sql_roll,
            "student_name": xss_name,
            "section": "<style>body{display:none;}</style>",
            "time_taken_seconds": 100,
            "answers": [{"question_id": q_id, "typed_answer": xss_answer, "image_data": ""}]
        }
    )
    assert sub_res.status_code == 200, sub_res.text
    sub_id = sub_res.json()["submission_id"]

    # Verify the table still exists and query returns data safely
    detail_res = client.get(f"/api/submissions/{sub_id}", headers=admin_headers)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["student_name"] == xss_name
    assert detail["roll_number"] == sql_roll.upper()


def test_oversized_payload_rejection_http_413(payload_client):
    """
    Attempts to send a payload that exceeds the 12MB ceiling.
    Verifies that the server returns HTTP 413 (Payload Too Large) with a user-friendly message.
    """
    client, _, _ = payload_client

    # Simulate a request header claiming 13MB
    oversized_bytes = 13 * 1024 * 1024
    res = client.post(
        "/api/exams/TEST-CODE/submit",
        content="x",
        headers={"Content-Length": str(oversized_bytes), "Content-Type": "application/json"}
    )
    assert res.status_code == 413
    assert "Payload too large" in res.json()["detail"]


def test_invalid_submission_edge_cases(payload_client):
    """
    Tests edge cases:
    - Empty roll number
    - Empty student name
    - Inactive / closed exam
    - Non-existent exam code
    """
    client, admin_headers, _ = payload_client
    deadline = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    create_res = client.post(
        "/api/exams",
        headers=admin_headers,
        json={
            "title": "Validation Exam",
            "subject": "Testing",
            "duration_minutes": 30,
            "deadline": deadline,
            "questions": [{"question_text": "Q1", "marks": 5.0}]
        }
    )
    exam_data = create_res.json()
    exam_code = exam_data["exam_code"]
    q_id = exam_data["questions"][0]["id"]

    # 1. Non-existent exam code -> 404
    r1 = client.post("/api/exams/NON-EXISTENT/submit", json={"roll_number": "R1", "student_name": "Test", "answers": []})
    assert r1.status_code == 404

    # 2. Blank student name -> 400
    r2 = client.post(f"/api/exams/{exam_code}/submit", json={"roll_number": "R2", "student_name": "   ", "answers": []})
    assert r2.status_code == 400

    # 3. Blank roll number -> 422 or 400
    r3 = client.post(f"/api/exams/{exam_code}/submit", json={"roll_number": "", "student_name": "Valid Name", "answers": []})
    assert r3.status_code in (400, 422)

    # 4. Closed exam submission rejection -> 400
    toggle_res = client.patch(f"/api/exams/{exam_data['id']}/toggle", headers=admin_headers)
    assert toggle_res.status_code == 200
    assert toggle_res.json()["status"] == "closed"
    r4 = client.post(
        f"/api/exams/{exam_code}/submit",
        json={"roll_number": "R4", "student_name": "Student", "answers": [{"question_id": q_id, "typed_answer": "ans"}]}
    )
    assert r4.status_code == 400
    assert "not currently active" in r4.json()["detail"]
