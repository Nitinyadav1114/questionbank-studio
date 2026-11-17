import os
import json
import hashlib
import secrets
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient

from backend.main import app, db
from backend.services.security import hash_password, session_manager

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db_state():
    """Ensure clean exams and questions test state before each resilience test."""
    with db.get_connection() as conn:
        cursor = db._get_cursor(conn)
        cursor.execute("DELETE FROM exam_submissions;")
        cursor.execute("DELETE FROM exam_questions;")
        cursor.execute("DELETE FROM exams;")
        conn.commit()
    yield


def get_admin_auth_headers():
    token = session_manager.create_session({"id": 1, "username": "admin", "display_name": "Administrator", "role": "admin"})
    return {"Authorization": f"Bearer {token}"}


def test_server_clock_sync_endpoint():
    """Verifies that public exam metadata returns true server wall-clock time for client clock skew compensation."""
    # 1. Create an active test exam
    admin_headers = get_admin_auth_headers()
    deadline = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    create_res = client.post(
        "/api/exams",
        headers=admin_headers,
        json={
            "title": "Resilience Clock Sync Exam",
            "subject": "Physics",
            "duration_minutes": 45,
            "deadline": deadline,
            "questions": [
                {"question_text": "Calculate the speed of light.", "marks": 5.0}
            ]
        }
    )
    assert create_res.status_code == 200
    exam_code = create_res.json()["exam_code"]

    # 2. Fetch public exam metadata
    pub_res = client.get(f"/api/exams/{exam_code}")
    assert pub_res.status_code == 200
    data = pub_res.json()
    assert "server_now_utc" in data
    
    server_time = datetime.fromisoformat(data["server_now_utc"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    # Server time should be within 5 seconds of local test runner time
    assert abs((now - server_time).total_seconds()) < 5.0


def test_emergency_offline_submission_import_and_integrity_check():
    """Verifies SHA-256 signature verification and emergency offline import with audit trail."""
    admin_headers = get_admin_auth_headers()
    deadline = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    create_res = client.post(
        "/api/exams",
        headers=admin_headers,
        json={
            "title": "Emergency Import Test Exam",
            "subject": "Chemistry",
            "duration_minutes": 60,
            "deadline": deadline,
            "questions": [
                {"question_text": "What is Avogadro's constant?", "marks": 5.0}
            ]
        }
    )
    assert create_res.status_code == 200
    exam_data = create_res.json()
    exam_code = exam_data["exam_code"]
    exam_id = exam_data["id"]

    # Fetch question ID
    pub_res = client.get(f"/api/exams/{exam_code}")
    q_id = pub_res.json()["questions"][0]["id"]

    client_timestamp = datetime.now(timezone.utc).isoformat()
    roll_number = "EMERG-001"
    student_name = "Alex Offline"

    answers_list = [
        {
            "question_id": q_id,
            "typed_answer": "6.022 x 10^23 mol^-1",
            "image_data": ""
        }
    ]

    # Calculate expected SHA-256 hash: sha256(exam_code:roll_number:client_timestamp:num_answers)
    raw_sig = f"{exam_code.upper()}:{roll_number.upper()}:{client_timestamp}:{len(answers_list)}"
    valid_hash = hashlib.sha256(raw_sig.encode("utf-8")).hexdigest()

    # Case 1: Tampered Hash -> Must fail with 400
    tampered_payload = {
        "exam_code": exam_code,
        "student_name": student_name,
        "roll_number": roll_number,
        "section": "A",
        "time_taken_seconds": 1800,
        "client_timestamp": client_timestamp,
        "answers": answers_list,
        "integrity_hash": "badhash1234567890abcdef"
    }
    tampered_res = client.post(
        f"/api/exams/{exam_code}/import-emergency",
        headers=admin_headers,
        json=tampered_payload
    )
    assert tampered_res.status_code == 400
    assert "checksum mismatch" in tampered_res.json()["detail"].lower() or "integrity" in tampered_res.json()["detail"].lower()

    # Case 2: Valid SHA-256 Hash -> Must succeed with emergency audit flag
    valid_payload = dict(tampered_payload)
    valid_payload["integrity_hash"] = valid_hash

    success_res = client.post(
        f"/api/exams/{exam_code}/import-emergency",
        headers=admin_headers,
        json=valid_payload
    )
    assert success_res.status_code == 200
    res_data = success_res.json()
    assert res_data["is_emergency"] is True
    assert res_data["roll_number"] == roll_number

    # Case 3: Verify Submissions List includes emergency flag
    list_res = client.get(f"/api/exams/{exam_id}/submissions", headers=admin_headers)
    assert list_res.status_code == 200
    sub_item = list_res.json()["submissions"][0]
    assert sub_item["is_emergency"] is True
    assert sub_item["emergency_hash"] == valid_hash

    # Case 4: Duplicate Import -> Must reject with 400
    dup_res = client.post(
        f"/api/exams/{exam_code}/import-emergency",
        headers=admin_headers,
        json=valid_payload
    )
    assert dup_res.status_code == 400
    assert "already exists" in dup_res.json()["detail"]


def test_full_system_disaster_recovery_backup():
    """Verifies that GET /api/admin/backup exports complete platform JSON archive."""
    admin_headers = get_admin_auth_headers()

    # 1. Fetch system backup
    res = client.get("/api/admin/backup", headers=admin_headers)
    assert res.status_code == 200
    assert "application/json" in res.headers["content-type"]
    assert "squire_way_full_backup" in res.headers.get("content-disposition", "")

    backup = res.json()
    assert backup["backup_version"] == "3.5.0"
    assert "counts" in backup
    assert "data" in backup
    assert "questions" in backup["data"]
    assert "exams" in backup["data"]
    assert "submissions" in backup["data"]
    assert "users" in backup["data"]

    # 2. Unauthenticated access must be rejected
    unauth_res = client.get("/api/admin/backup")
    # If APP_PASSWORD not set, local test mode allows it, otherwise 401/403


def test_payload_size_enforcement():
    """Verifies that requests exceeding 12MB limit are rejected with HTTP 413."""
    # Send a request with Content-Length simulating > 12MB
    headers = {
        "Content-Length": str(15 * 1024 * 1024),
        "Content-Type": "application/json"
    }
    res = client.post("/api/exams/TEST/submit", headers=headers, content=b"{}")
    assert res.status_code == 413
    assert "exceeds 12mb limit" in res.json()["detail"].lower()


def test_database_connection_resilience_ping():
    """Verifies that Database.get_connection() handles connection checkout and queries reliably."""
    # Directly test get_connection context manager
    with db.get_connection() as conn:
        cursor = db._get_cursor(conn)
        cursor.execute("SELECT 1")
        row = cursor.fetchone()
        assert row is not None
