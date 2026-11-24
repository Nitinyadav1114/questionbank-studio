import os
import gc
import tempfile
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import Database
from backend.services.security import ensure_admin_user
import backend.main as main_module


@pytest.fixture
def client_with_temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name

    test_db = Database(temp_db_path)
    ensure_admin_user(test_db)
    original_db = main_module.db
    main_module.db = test_db

    client = TestClient(app)
    yield client, test_db

    main_module.db = original_db
    del test_db
    del client
    gc.collect()
    try:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)
    except PermissionError:
        pass


def test_create_and_list_exams(client_with_temp_db):
    client, _ = client_with_temp_db
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    # 1. Create digital exam
    payload = {
        "title": "Grade 10 Physics Midterm Examination",
        "subject": "Physics",
        "duration_minutes": 90,
        "deadline": tomorrow,
        "instructions": "Answer all questions. Show your work clearly.",
        "total_marks": 20.0,
        "questions": [
            {"question_text": "State Newton's Second Law of Motion.", "marks": 5.0, "question_order": 1},
            {"question_text": "Calculate the kinetic energy of a 2kg mass moving at 3m/s.", "marks": 5.0, "question_order": 2},
            {"question_text": "Explain the difference between mass and weight.", "marks": 10.0, "question_order": 3}
        ]
    }

    resp = client.post("/api/exams", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert "id" in data
    assert "exam_code" in data
    assert data["exam_code"].startswith("PHYS-") or data["exam_code"].startswith("PHY-")
    assert data["title"] == "Grade 10 Physics Midterm Examination"
    assert data["total_marks"] == 20.0
    assert data["duration_minutes"] == 90
    assert data["status"] == "active"
    assert "exam_url" in data
    assert "qr_svg" in data
    assert "<svg" in data["qr_svg"]
    assert len(data["questions"]) == 3

    # 2. List exams
    list_resp = client.get("/api/exams")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total"] >= 1
    found = [e for e in list_data["exams"] if e["id"] == data["id"]]
    assert len(found) == 1
    assert found[0]["questions_count"] == 3
    assert found[0]["submissions_count"] == 0
    assert found[0]["pending_count"] == 0


def test_create_exam_auto_total_marks(client_with_temp_db):
    client, _ = client_with_temp_db
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()

    payload = {
        "title": "Chemistry Quiz",
        "subject": "Chemistry",
        "duration_minutes": 30,
        "deadline": tomorrow,
        "questions": [
            {"question_text": "What is the pH of pure water?", "marks": 2.5},
            {"question_text": "Write the chemical formula for sulfuric acid.", "marks": 3.5}
        ]
    }
    resp = client.post("/api/exams", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    # Auto-calculated sum: 2.5 + 3.5 = 6.0
    assert data["total_marks"] == 6.0


def test_create_exam_invalid_deadline(client_with_temp_db):
    client, _ = client_with_temp_db
    payload = {
        "title": "Invalid Deadline Exam",
        "deadline": "not-a-valid-date",
        "questions": [{"question_text": "Sample question", "marks": 1.0}]
    }
    resp = client.post("/api/exams", json=payload)
    assert resp.status_code == 400
    assert "Invalid deadline" in resp.json()["detail"]


def test_public_exam_metadata_endpoint(client_with_temp_db):
    client, _ = client_with_temp_db
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    create_resp = client.post("/api/exams", json={
        "title": "English Literature Exam",
        "subject": "English",
        "deadline": tomorrow,
        "questions": [
            {"question_text": "Analyze the themes of Macbeth.", "marks": 15.0}
        ]
    })
    exam_code = create_resp.json()["exam_code"]

    # Public metadata lookup
    pub_resp = client.get(f"/api/exams/{exam_code}")
    assert pub_resp.status_code == 200
    pub_data = pub_resp.json()
    assert pub_data["exam_code"] == exam_code
    assert pub_data["title"] == "English Literature Exam"
    assert pub_data["questions_count"] == 1
    assert pub_data["questions"][0]["question_text"] == "Analyze the themes of Macbeth."
    # Ensure no internal/secret fields are leaked
    assert "created_by" not in pub_data

    # Non-existent exam code
    assert client.get("/api/exams/NON-EXISTENT-CODE").status_code == 404


def test_student_submission_and_result_flow(client_with_temp_db):
    client, _ = client_with_temp_db
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    create_resp = client.post("/api/exams", json={
        "title": "Mathematics Final",
        "subject": "Math",
        "deadline": tomorrow,
        "questions": [
            {"question_text": "Solve 2x + 5 = 15.", "marks": 5.0},
            {"question_text": "Integrate x^2 dx.", "marks": 5.0}
        ]
    })
    exam = create_resp.json()
    exam_code = exam["exam_code"]
    exam_id = exam["id"]
    q1_id = exam["questions"][0]["id"]
    q2_id = exam["questions"][1]["id"]

    # 1. Student submits typed answer for Q1 and mock canvas image for Q2
    sub_payload = {
        "student_name": "Alice Johnson",
        "roll_number": "2026-MATH-001",
        "section": "10-B",
        "time_taken_seconds": 1845,
        "answers": [
            {
                "question_id": q1_id,
                "typed_answer": "2x = 10, therefore x = 5.",
                "image_data": ""
            },
            {
                "question_id": q2_id,
                "typed_answer": "See attached handwritten sheet.",
                "image_data": "data:image/webp;base64,UklGRmYAAABXRUJQVlA4..."
            }
        ]
    }

    sub_resp = client.post(f"/api/exams/{exam_code}/submit", json=sub_payload)
    assert sub_resp.status_code == 200, sub_resp.text
    sub_data = sub_resp.json()
    assert sub_data["status"] == "submitted"
    assert sub_data["roll_number"] == "2026-MATH-001"
    sub_id = sub_data["submission_id"]

    # 2. Duplicate submission blocked for same roll number
    dup_resp = client.post(f"/api/exams/{exam_code}/submit", json=sub_payload)
    assert dup_resp.status_code == 400
    assert "already exists" in dup_resp.json()["detail"]

    # 3. Student checks result before grading (should be pending_evaluation)
    res_resp_1 = client.get(f"/api/exams/{exam_code}/result?roll_number=2026-MATH-001")
    assert res_resp_1.status_code == 200
    res_data_1 = res_resp_1.json()
    assert res_data_1["status"] == "pending_evaluation"
    assert res_data_1["student_name"] == "Alice Johnson"

    # 4. Teacher views submissions list
    teacher_subs_resp = client.get(f"/api/exams/{exam_id}/submissions")
    assert teacher_subs_resp.status_code == 200
    teacher_subs = teacher_subs_resp.json()["submissions"]
    assert len(teacher_subs) == 1
    assert teacher_subs[0]["student_name"] == "Alice Johnson"
    assert teacher_subs[0]["status"] == "submitted"

    # 5. Teacher views full submission detail
    detail_resp = client.get(f"/api/submissions/{sub_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert len(detail["answers"]) == 2
    assert detail["answers"][0]["typed_answer"] == "2x = 10, therefore x = 5."
    assert detail["answers"][1]["image_data"].startswith("data:image/")

    # 6. Teacher grades the submission
    grade_payload = {
        "grades": [
            {"question_id": q1_id, "marks_awarded": 5.0, "feedback": "Perfect step-by-step solution."},
            {"question_id": q2_id, "marks_awarded": 4.5, "feedback": "Don't forget the constant + C."}
        ],
        "overall_feedback": "Excellent performance on algebra and calculus."
    }
    grade_resp = client.post(f"/api/submissions/{sub_id}/grade", json=grade_payload)
    assert grade_resp.status_code == 200, grade_resp.text
    graded_info = grade_resp.json()["submission"]
    assert graded_info["status"] == "graded"
    assert graded_info["total_score"] == 9.5
    assert graded_info["percentage"] == 95.0

    # 7. Student checks result again (now published scorecard)
    res_resp_2 = client.get(f"/api/exams/{exam_code}/result?roll_number=2026-MATH-001")
    assert res_resp_2.status_code == 200
    res_data_2 = res_resp_2.json()
    assert res_data_2["status"] == "published"
    assert res_data_2["total_score"] == 9.5
    assert res_data_2["total_marks"] == 10.0
    assert res_data_2["percentage"] == 95.0
    assert res_data_2["feedback"] == "Excellent performance on algebra and calculus."
    assert len(res_data_2["questions"]) == 2
    assert res_data_2["questions"][0]["marks_awarded"] == 5.0
    assert res_data_2["questions"][1]["marks_awarded"] == 4.5


def test_deadline_enforcement(client_with_temp_db):
    client, _ = client_with_temp_db
    # Expired deadline: 1 hour in the past
    past_deadline = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    create_resp = client.post("/api/exams", json={
        "title": "Expired Biology Exam",
        "subject": "Biology",
        "deadline": past_deadline,
        "questions": [{"question_text": "Define photosynthesis.", "marks": 5.0}]
    })
    exam_code = create_resp.json()["exam_code"]

    sub_payload = {
        "student_name": "Bob Smith",
        "roll_number": "2026-BIO-099",
        "answers": [{"question_id": create_resp.json()["questions"][0]["id"], "typed_answer": "Sunlight conversion."}]
    }
    resp = client.post(f"/api/exams/{exam_code}/submit", json=sub_payload)
    assert resp.status_code == 400
    assert "deadline has passed" in resp.json()["detail"]


def test_exam_status_toggle(client_with_temp_db):
    client, _ = client_with_temp_db
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    create_resp = client.post("/api/exams", json={
        "title": "History Quiz",
        "deadline": tomorrow,
        "questions": [{"question_text": "Year of French Revolution?", "marks": 5.0}]
    })
    exam = create_resp.json()
    exam_id = exam["id"]
    exam_code = exam["exam_code"]

    # Toggle to closed
    t1 = client.patch(f"/api/exams/{exam_id}/toggle")
    assert t1.status_code == 200
    assert t1.json()["status"] == "closed"

    # Submission when closed should be rejected
    sub_payload = {
        "student_name": "Charlie",
        "roll_number": "2026-HIST-001",
        "answers": []
    }
    sub_resp = client.post(f"/api/exams/{exam_code}/submit", json=sub_payload)
    assert sub_resp.status_code == 400
    assert "not currently active" in sub_resp.json()["detail"]

    # Toggle back to active
    t2 = client.patch(f"/api/exams/{exam_id}/toggle")
    assert t2.status_code == 200
    assert t2.json()["status"] == "active"

    # Direct idempotent status endpoint test
    s_close = client.patch(f"/api/exams/{exam_id}/status", json={"status": "closed"})
    assert s_close.status_code == 200
    assert s_close.json()["status"] == "closed"

    s_open = client.patch(f"/api/exams/{exam_id}/status", json={"status": "active"})
    assert s_open.status_code == 200
    assert s_open.json()["status"] == "active"

    # Submission now permitted
    sub_ok = client.post(f"/api/exams/{exam_code}/submit", json=sub_payload)
    assert sub_ok.status_code == 200


def test_delete_exam_cascade(client_with_temp_db):
    client, test_db = client_with_temp_db
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    create_resp = client.post("/api/exams", json={
        "title": "Exam to Delete",
        "deadline": tomorrow,
        "questions": [{"question_text": "Sample Question", "marks": 5.0}]
    })
    exam = create_resp.json()
    exam_id = exam["id"]
    exam_code = exam["exam_code"]

    # Submit an answer
    client.post(f"/api/exams/{exam_code}/submit", json={
        "student_name": "Student A",
        "roll_number": "ROLL-DEL-1",
        "answers": [{"question_id": exam["questions"][0]["id"], "typed_answer": "Test"}]
    })

    # Delete exam
    del_resp = client.delete(f"/api/exams/{exam_id}")
    assert del_resp.status_code == 200

    # Verify exam no longer found
    assert client.get(f"/api/exams/{exam_code}").status_code == 404
    assert client.get(f"/api/exams/{exam_id}/submissions").status_code == 404

    # Verify cascading deletion in DB
    with test_db.get_connection() as conn:
        cursor = test_db._get_cursor(conn)
        cursor.execute("SELECT COUNT(*) FROM exam_questions WHERE exam_id = ?", (exam_id,))
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT COUNT(*) FROM exam_submissions WHERE exam_id = ?", (exam_id,))
        assert cursor.fetchone()[0] == 0


def test_qr_code_vector_svg_endpoint(client_with_temp_db):
    client, _ = client_with_temp_db
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    create_resp = client.post("/api/exams", json={
        "title": "QR Code Test Exam",
        "deadline": tomorrow,
        "questions": [{"question_text": "Sample", "marks": 1.0}]
    })
    exam_code = create_resp.json()["exam_code"]

    qr_resp = client.get(f"/api/exams/{exam_code}/qr")
    assert qr_resp.status_code == 200
    assert qr_resp.headers["content-type"].startswith("image/svg+xml")
    content = qr_resp.text
    assert "<svg" in content
    assert "</svg>" in content


def test_static_exam_room_serving(client_with_temp_db):
    client, _ = client_with_temp_db
    resp = client.get("/exam/ENG-2026-X9A")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "exam-room-root" in resp.text
    assert "Squire Way — Digital Exam Room" in resp.text


def test_dual_database_parameter_formatting():
    # Verify parameter marker formatting for SQLite vs PostgreSQL
    sqlite_db = Database("dummy.db")
    sqlite_db.is_postgres = False
    assert sqlite_db._format_query("SELECT * FROM exams WHERE exam_code = ? AND id = ?") == "SELECT * FROM exams WHERE exam_code = ? AND id = ?"

    postgres_db = Database("dummy.db")
    postgres_db.is_postgres = True
    assert postgres_db._format_query("SELECT * FROM exams WHERE exam_code = ? AND id = ?") == "SELECT * FROM exams WHERE exam_code = %s AND id = %s"
