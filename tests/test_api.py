import io
import os
import gc
import json
import tempfile
import pytest
from fastapi.testclient import TestClient
from docx import Document

from backend.main import app
from backend.database import Database
import backend.main as main_module

@pytest.fixture
def client_with_temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name

    test_db = Database(temp_db_path)
    original_db = main_module.db
    main_module.db = test_db

    client = TestClient(app)
    yield client

    # Cleanup
    main_module.db = original_db
    del test_db
    del client
    gc.collect()
    try:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)
    except PermissionError:
        pass

def create_sample_docx_bytes(question_texts):
    doc = Document()
    for idx, text in enumerate(question_texts, start=1):
        doc.add_paragraph(f"{idx}. {text}")
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()

def test_full_api_flow(client_with_temp_db):
    client = client_with_temp_db

    # 1. Upload first docx file with 3 questions
    file1_bytes = create_sample_docx_bytes([
        "What is the capital of France?",
        "Explain the process of cellular respiration in mitochondria.",
        "Calculate the derivative of f(x) = 3x^2 + 5x - 7."
    ])

    resp1 = client.post(
        "/api/upload",
        files=[("files", ("test_file_1.docx", file1_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))],
        data={"subject": "General", "topic": "Mixed"}
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["total_files"] == 1
    assert data1["total_extracted"] == 3
    assert data1["total_new"] == 3
    assert data1["total_merged"] == 0

    # 2. Upload second docx with 2 repeated questions and 1 brand new question
    file2_bytes = create_sample_docx_bytes([
        "What is the capital of France?",  # Exact duplicate
        "Explain the process of cellular respiration in mitochondria.",  # Exact duplicate
        "Who formulated the general theory of relativity?"  # Brand new
    ])

    resp2 = client.post(
        "/api/upload",
        files=[("files", ("test_file_2.docx", file2_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))],
        data={"subject": "Physics", "topic": "Relativity"}
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["total_extracted"] == 3
    assert data2["total_new"] == 1
    assert data2["total_merged"] == 2

    # 3. Query questions list
    q_resp = client.get("/api/questions")
    assert q_resp.status_code == 200
    q_data = q_resp.json()
    assert q_data["total"] == 4  # Total unique questions

    # Check that frequency of repeated questions is 2 and has both sources
    repeated_q = next(q for q in q_data["items"] if "capital of France" in q["question_text"])
    assert repeated_q["frequency"] == 2
    assert "test_file_1.docx" in repeated_q["sources"]
    assert "test_file_2.docx" in repeated_q["sources"]

    # 4. Check metadata stats
    meta_resp = client.get("/api/metadata")
    assert meta_resp.status_code == 200
    meta = meta_resp.json()
    assert meta["total_unique"] == 4
    assert meta["total_occurrences"] == 6
    assert meta["merged_duplicates"] == 2
    assert "test_file_1.docx" in meta["sources"]
    assert "test_file_2.docx" in meta["sources"]

    # 5. Export Word document
    all_ids = [q["id"] for q in q_data["items"]]
    export_resp = client.post(
        "/api/export",
        json={"question_ids": all_ids, "title": "Science Final Exam", "format": "docx", "use_template": False}
    )
    assert export_resp.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in export_resp.headers["content-type"]
    assert len(export_resp.content) > 0

    # 6. Export PDF document
    export_pdf_resp = client.post(
        "/api/export",
        json={"question_ids": all_ids, "title": "Science Final Exam", "format": "pdf", "use_template": False}
    )
    assert export_pdf_resp.status_code == 200
    assert "application/pdf" in export_pdf_resp.headers["content-type"]
    assert len(export_pdf_resp.content) > 0

    # 7. Update a question
    first_id = all_ids[0]
    update_resp = client.put(
        f"/api/questions/{first_id}",
        json={"question_text": "Updated question text for testing."}
    )
    assert update_resp.status_code == 200

    # 8. Add manual question
    manual_resp = client.post(
        "/api/questions",
        json={
            "question_text": "What is the unit of electric resistance?",
            "subject": "Physics",
            "topic": "Electricity",
            "source": "Teacher Notes"
        }
    )
    assert manual_resp.status_code == 200
    manual_data = manual_resp.json()
    assert manual_data["is_merged"] is False

    # Add duplicate of manual question
    manual_dup_resp = client.post(
        "/api/questions",
        json={
            "question_text": "What is the unit of electric resistance?",
            "subject": "Physics",
            "topic": "Electricity",
            "source": "Textbook"
        }
    )
    assert manual_dup_resp.status_code == 200
    assert manual_dup_resp.json()["is_merged"] is True

    # 9. Backup API
    backup_resp = client.get("/api/backup")
    assert backup_resp.status_code == 200
    backup_json = backup_resp.json()
    assert backup_json["app"] == "QuestionBank Studio"
    assert len(backup_json["questions"]) >= 5

    # 10. Restore API
    restore_file_content = json.dumps(backup_json).encode("utf-8")
    restore_resp = client.post(
        "/api/restore",
        files=[("file", ("backup.json", restore_file_content, "application/json"))]
    )
    assert restore_resp.status_code == 200
    restore_data = restore_resp.json()
    assert "stats" in restore_data
    assert restore_data["stats"]["total"] >= 5

    # 11. Bulk delete questions
    current_items = client.get("/api/questions").json()["items"]
    ids_to_delete = [item["id"] for item in current_items[:2]]
    initial_count = len(current_items)

    bulk_del_resp = client.post(
        "/api/questions/bulk-delete",
        json={"question_ids": ids_to_delete}
    )
    assert bulk_del_resp.status_code == 200
    assert bulk_del_resp.json()["deleted_count"] == len(ids_to_delete)

    # Verify count decreased by deleted amount
    post_bulk_items = client.get("/api/questions").json()["items"]
    assert len(post_bulk_items) == initial_count - len(ids_to_delete)

def test_passcode_auth(client_with_temp_db):
    client = client_with_temp_db

    # Enable password temporarily
    original_pass = main_module.APP_PASSWORD
    try:
        main_module.APP_PASSWORD = "secret_password_123"

        # Check auth status when not logged in
        status_resp = client.get("/api/auth/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["protected"] is True
        assert status_resp.json()["authenticated"] is False

        # Attempt to upload or delete without password -> 401
        unauth_resp = client.post("/api/questions", json={"question_text": "Unauthorized test question?"})
        assert unauth_resp.status_code == 401

        # Attempt login with wrong password -> 401
        wrong_resp = client.post("/api/auth/verify", json={"password": "wrong"})
        assert wrong_resp.status_code == 401

        # Login with correct password -> 200
        correct_resp = client.post("/api/auth/verify", json={"password": "secret_password_123"})
        assert correct_resp.status_code == 200
        assert correct_resp.json()["success"] is True

        # Now request with header works
        auth_header_resp = client.post(
            "/api/questions",
            headers={"x-app-password": "secret_password_123"},
            json={"question_text": "Authorized test question?"}
        )
        assert auth_header_resp.status_code == 200

    finally:
        main_module.APP_PASSWORD = original_pass
