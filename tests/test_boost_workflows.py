import gc
import io
import json
import os
import re
import shutil
import subprocess
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from docx import Document
from fastapi.testclient import TestClient

import backend.main as main_module
from backend.database import Database
from backend.main import app
from backend.services.curator import curate_question_library
from backend.services.dedup import normalize_question_text
from backend.services.parser import extract_structured_questions_from_file
from backend.services.security import auth_rate_limiter, ensure_admin_user, hash_password, session_manager


@pytest.fixture
def isolated_client(tmp_path):
    temp_db_path = str(tmp_path / "test_boost.db")
    test_db = Database(temp_db_path)
    ensure_admin_user(test_db)

    orig_db = main_module.db
    orig_pass = main_module.APP_PASSWORD
    try:
        main_module.db = test_db
        main_module.APP_PASSWORD = ""
        client = TestClient(app)
        yield client, test_db, tmp_path
    finally:
        main_module.db = orig_db
        main_module.APP_PASSWORD = orig_pass
        gc.collect()


@pytest.fixture
def rbac_client(tmp_path):
    temp_db_path = str(tmp_path / "test_rbac_boost.db")
    test_db = Database(temp_db_path)
    orig_db = main_module.db
    orig_pass = main_module.APP_PASSWORD

    try:
        main_module.db = test_db
        main_module.APP_PASSWORD = "squire2026"

        ensure_admin_user(test_db)
        t_hash, t_salt = hash_password("teacher_pw_123")
        test_db.create_user(
            username="teacher_boost",
            display_name="Teacher Boost",
            password_hash=t_hash,
            salt=t_salt,
            role="teacher",
        )

        auth_rate_limiter.reset_all()
        session_manager.reset_all()

        client = TestClient(app)
        admin_res = client.post("/api/auth/login", json={"username": "admin", "password": "squire2026"})
        assert admin_res.status_code == 200, admin_res.text
        teacher_res = client.post("/api/auth/login", json={"username": "teacher_boost", "password": "teacher_pw_123"})
        assert teacher_res.status_code == 200, teacher_res.text

        yield (
            client,
            test_db,
            tmp_path,
            {"Authorization": f"Bearer {admin_res.json()['token']}"},
            {"Authorization": f"Bearer {teacher_res.json()['token']}"},
        )
    finally:
        main_module.db = orig_db
        main_module.APP_PASSWORD = orig_pass
        auth_rate_limiter.reset_all()
        session_manager.reset_all()
        gc.collect()


def _make_docx_bytes(paragraphs):
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


def test_smart_sanitizer_and_parser_context():
    raw_docx = _make_docx_bytes([
        "Book: First Flight (Prose Section)",
        "Lesson: 1 (A Letter to God)",
        "1. Why did Lencho write a letter to God? Class: 10th (2025-26) Subject: English Compulsory Giriraj Yadav ‘JUGNU’ Mob No. 9829692049 Page 1 of 4",
        "2. How did M . Hamel react? OR Draw a character sketch of Franz? [5 marks]",
        "3. Describe Kisa Gotami’s grief. Class: 10th (2025-26) Subject: English Compulsory",
        "Lesson: 2 (Nelson Mandela: Long Walk to Freedom)",
        "4. Why were two National Anthems sung? OR",
    ])
    items, dropped = extract_structured_questions_from_file(
        "Class 10 English.docx",
        raw_docx,
        default_subject="",
        default_topic="",
        default_class="",
    )
    assert dropped >= 3  # Book + Lesson 1 + Lesson 2
    texts = [it["question_text"] for it in items]
    assert len(texts) == 5  # Q1, Q2a, Q2b (split OR), Q3, Q4 (OR stripped)
    assert "Giriraj Yadav" not in " ".join(texts)
    assert "Page 1 of 4" not in " ".join(texts)
    assert "Class: 10th" not in " ".join(texts)
    assert any("M. Hamel" in t for t in texts)
    assert any(t == "Why were two National Anthems sung?" for t in texts)
    assert any(it.get("default_marks") == 5.0 for it in items)
    assert items[0]["topic"] == "A Letter to God"
    assert items[-1]["topic"] == "Nelson Mandela: Long Walk to Freedom"
    assert items[0]["class_level"] == "Class 10"


def test_curation_dry_run_and_apply_with_backup(tmp_path):
    db_path = str(tmp_path / "curate_test.db")
    test_db = Database(db_path)

    # Seed dirty legacy rows using distinct raw normalized keys as older parsers did
    dirty_rows = [
        ("Book: First Flight (Prose Section)", "Class 10 Imp.docx"),
        ("Lesson: 1 (A Letter to God)", "Class 10 Imp.docx"),
        ("Draw a character-sketch of Valli? Class: 10th (2025-26) Subject: English Compulsory", "Class 10 Imp.docx"),
        ("What is the theme of ‘Dust of Snow’?", "Class 10 Imp.docx"),
        ("What is the theme of 'Dust of Snow'?", "Class 10 Imp 2.docx"),
        ("people, visit of the Home Minister and relief.", "Class 12 Imp.docx"),
    ]
    for idx, (text, src) in enumerate(dirty_rows):
        test_db.upsert_question(text, f"legacy_raw_{idx}_{text.lower()}", subject="General", topic="", source_filename=src)

    before_count = test_db.get_metadata()["total_unique"]
    assert before_count == 6

    dry_report = curate_question_library(test_db, dry_run=True, create_backup=False)
    assert dry_report["dry_run"] is True
    assert dry_report["dividers_removed"] >= 2
    assert test_db.get_metadata()["total_unique"] == before_count  # untouched

    backup_dir = str(tmp_path / "backups")
    apply_report = curate_question_library(test_db, dry_run=False, create_backup=True, backup_dir=backup_dir)
    assert apply_report["dry_run"] is False
    assert apply_report["backup_path"] is not None
    assert os.path.exists(apply_report["backup_path"])

    backup_data = json.loads(open(apply_report["backup_path"], encoding="utf-8").read())
    assert len(backup_data["questions"]) == 6

    qs = test_db.get_questions(limit=50)["items"]
    texts = [q["question_text"] for q in qs]
    assert "Book: First Flight (Prose Section)" not in texts
    assert "Lesson: 1 (A Letter to God)" not in texts
    assert any(t == "Draw a character-sketch of Valli?" for t in texts)
    # Quote duplicates merged into one with frequency == 2
    dust_qs = [q for q in qs if "Dust of Snow" in q["question_text"]]
    assert len(dust_qs) == 1
    assert dust_qs[0]["frequency"] == 2
    # Lowercase fragment flagged Needs Review
    frag = [q for q in qs if q["question_text"].startswith("people,")]
    assert len(frag) == 1
    assert frag[0]["needs_review"] is True


def test_upload_preview_and_confirm_flow(isolated_client):
    client, test_db, _ = isolated_client
    docx_bytes = _make_docx_bytes([
        "Lesson: 1 (A Letter to God)",
        "1. Why did Lencho say the raindrops were like new coins?",
        "2. Who read Lencho's letter?",
    ])

    prev = client.post(
        "/api/upload/preview",
        files={"files": ("Class 10.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={"subject": "English", "topic": "", "class_level": "Class 10"},
    )
    assert prev.status_code == 200, prev.text
    pdata = prev.json()
    assert pdata["total_extracted"] == 2
    assert pdata["dropped_dividers_count"] == 1
    # Nothing saved yet!
    assert client.get("/api/questions").json()["total"] == 0

    items = pdata["items"]
    items[0]["default_marks"] = 5.0
    items[0]["difficulty"] = "Medium"
    items[1]["include"] = False  # teacher unchecks item 2

    conf = client.post("/api/upload/confirm", json={"items": items})
    assert conf.status_code == 200, conf.text
    cdata = conf.json()
    assert cdata["total_new"] == 1

    lib = client.get("/api/questions").json()
    assert lib["total"] == 1
    assert lib["items"][0]["default_marks"] == 5.0
    assert lib["items"][0]["class_level"] == "Class 10"
    assert lib["items"][0]["topic"] == "A Letter to God"


def test_bulk_tag_merge_duplicates_and_autopick(isolated_client):
    client, test_db, _ = isolated_client

    t1 = "What is the central theme of The Ball Poem?"
    t2 = "What is the central them of The Ball Poem?"  # typo near-duplicate
    t3 = "Give a character sketch of Matilda Loisel in detail."
    t4 = "Why was Bholi reluctant to go to school?"

    q1_id, _ = test_db.upsert_question(
        t1, normalize_question_text(t1),
        subject="English", topic="The Ball Poem", source_filename="Test.docx",
        class_level="Class 10", question_type="Short Answer", difficulty="Medium", default_marks=2.0,
        needs_review=True, review_reason="Manual check",
    )
    q2_id, _ = test_db.upsert_question(
        t2, normalize_question_text(t2),
        subject="English", topic="The Ball Poem", source_filename="Test2.docx",
        class_level="Class 10", question_type="Short Answer", difficulty="Medium", default_marks=2.0,
    )
    q3_id, _ = test_db.upsert_question(
        t3, normalize_question_text(t3),
        subject="English", topic="The Necklace", source_filename="Test.docx",
        class_level="Class 10", question_type="Long Answer", difficulty="Hard", default_marks=5.0,
    )
    q4_id, _ = test_db.upsert_question(
        t4, normalize_question_text(t4),
        subject="English", topic="Bholi", source_filename="Test.docx",
        class_level="Class 10", question_type="Short Answer", difficulty="Easy", default_marks=2.0,
    )

    # Rich filter + sort check
    f_resp = client.get("/api/questions?class_level=Class+10&difficulty=Hard&sort_by=marks_desc")
    assert f_resp.status_code == 200
    assert f_resp.json()["total"] == 1
    assert f_resp.json()["items"][0]["id"] == q3_id

    nr_resp = client.get("/api/questions?needs_review=true")
    assert nr_resp.json()["total"] == 1

    # Bulk update clears needs_review & sets marks
    bu = client.post("/api/questions/bulk-update", json={
        "question_ids": [q1_id, q4_id],
        "needs_review": False,
        "review_reason": "",
        "default_marks": 3.0,
    })
    assert bu.status_code == 200
    assert bu.json()["updated_count"] == 2
    assert client.get("/api/questions?needs_review=true").json()["total"] == 0

    # Near duplicate detection finds q1 & q2
    dups = client.get("/api/questions/duplicates?threshold=0.80").json()
    assert dups["total_groups"] >= 1
    found_pair = any({q["id"] for q in g["questions"]} >= {q1_id, q2_id} for g in dups["groups"])
    assert found_pair

    # Merge q2 into q1
    m_resp = client.post("/api/questions/merge", json={"target_id": q1_id, "source_ids": [q2_id]})
    assert m_resp.status_code == 200
    assert m_resp.json()["question"]["frequency"] == 2

    # Edge cases: merge self or missing target
    bad_self = client.post("/api/questions/merge", json={"target_id": q1_id, "source_ids": [q1_id]})
    assert bad_self.status_code == 400
    bad_missing = client.post("/api/questions/merge", json={"target_id": 999999, "source_ids": [q1_id]})
    assert bad_missing.status_code == 404

    # Auto-Pick Paper Builder
    pick = client.post("/api/questions/auto-pick", json={
        "class_level": "Class 10",
        "subject": "English",
        "count": 3,
        "spread_topics": True,
        "prefer_most_repeated": True,
        "exclude_needs_review": True,
    })
    assert pick.status_code == 200
    pdata = pick.json()
    assert pdata["total_picked"] == 3
    assert pdata["total_marks"] > 0

    # Target-marks constrained Auto-Pick
    pick_marks = client.post("/api/questions/auto-pick", json={
        "class_level": "Class 10",
        "target_marks": 5.0,
        "exclude_needs_review": True,
    })
    assert pick_marks.status_code == 200
    assert pick_marks.json()["total_marks"] <= 5.0


def test_export_school_header_sections_and_marks(isolated_client):
    client, test_db, _ = isolated_client
    t1 = "Summarize A Letter to God."
    t2 = "Write an essay on Discipline."
    q1_id, _ = test_db.upsert_question(t1, normalize_question_text(t1), subject="English", topic="A Letter to God")
    q2_id, _ = test_db.upsert_question(t2, normalize_question_text(t2), subject="English", topic="Writing")

    payload = {
        "title": "Half Yearly Examination 2026",
        "format": "docx",
        "use_template": True,
        "show_marks": True,
        "paper_header": {
            "institute_name": "The Squire's Way",
            "exam_title": "Half Yearly Examination 2026",
            "class_subject": "Class 10 — English",
            "time_allowed": "3 Hours",
            "max_marks": "10",
            "instructions": "All questions are compulsory.",
            "show_header": True,
        },
        "items": [
            {"item_type": "section", "section_title": "Section A: Literature"},
            {"item_type": "question", "question_id": q1_id, "marks": 5.0},
            {"item_type": "section", "section_title": "Section B: Writing"},
            {"item_type": "question", "question_id": q2_id, "marks": 5.0},
        ],
    }

    docx_resp = client.post("/api/export", json=payload)
    assert docx_resp.status_code == 200
    doc = Document(io.BytesIO(docx_resp.content))
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "The Squire's Way" in full_text
    assert "Section A: Literature" in full_text
    assert "Section B: Writing" in full_text
    assert "[5]" in full_text

    # Verify PDF export with the exact same structured payload
    payload["format"] = "pdf"
    pdf_resp = client.post("/api/export", json=payload)
    assert pdf_resp.status_code == 200
    assert pdf_resp.content.startswith(b"%PDF")

    # Verify legacy question_ids payload still works
    legacy_resp = client.post("/api/export", json={
        "question_ids": [q1_id, q2_id],
        "title": "Legacy Quick Paper",
        "format": "docx",
        "use_template": False,
    })
    assert legacy_resp.status_code == 200


def test_exam_clone_deadline_stats_and_marksheet_csv(isolated_client):
    client, test_db, _ = isolated_client
    deadline = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()

    create_resp = client.post("/api/exams", json={
        "title": "Class 12 Prose Assessment",
        "subject": "English",
        "class_level": "Class 12",
        "institute_name": "The Squire's Way",
        "duration_minutes": 45,
        "deadline": deadline,
        "instructions": "Answer carefully.",
        "total_marks": 10.0,
        "questions": [
            {"question_text": "What was on the bulletin-board?", "marks": 5.0, "question_order": 1, "section_title": "Section A: Prose"},
            {"question_text": "What does Mukesh want to become?", "marks": 5.0, "question_order": 2, "section_title": "Section A: Prose"},
        ],
    })
    assert create_resp.status_code == 200, create_resp.text
    exam = create_resp.json()
    exam_id = exam["id"]
    exam_code = exam["exam_code"]

    # 1. Detail endpoint for Clone -> Cart
    detail = client.get(f"/api/exams/{exam_id}/detail")
    assert detail.status_code == 200
    d_json = detail.json()
    assert d_json["class_level"] == "Class 12"
    assert d_json["institute_name"] == "The Squire's Way"
    assert len(d_json["questions"]) == 2
    assert d_json["questions"][0]["section_title"] == "Section A: Prose"

    # 2. Close exam, then extend deadline & reopen
    client.patch(f"/api/exams/{exam_id}/toggle")
    new_dl = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    ext = client.patch(f"/api/exams/{exam_id}/deadline", json={
        "deadline": new_dl,
        "reopen_if_closed": True,
        "duration_minutes": 60,
    })
    assert ext.status_code == 200
    assert ext.json()["exam"]["status"] == "active"
    assert ext.json()["exam"]["duration_minutes"] == 60

    bad_ext = client.patch(f"/api/exams/{exam_id}/deadline", json={"deadline": "not-a-date"})
    assert bad_ext.status_code == 400

    # 3. Submit 2 student attempts (including CSV formula injection payload in name)
    sub1 = client.post(f"/api/exams/{exam_code}/submit", json={
        "roll_number": "101",
        "student_name": "Aarav Sharma",
        "section": "A",
        "time_taken_seconds": 600,
        "answers": [
            {"question_id": d_json["questions"][0]["id"], "typed_answer": "Order from Berlin"},
            {"question_id": d_json["questions"][1]["id"], "typed_answer": "Motor mechanic"},
        ],
    })
    assert sub1.status_code == 200
    sub1_id = sub1.json()["submission_id"]

    sub2 = client.post(f"/api/exams/{exam_code}/submit", json={
        "roll_number": "102",
        "student_name": "=CMD|' /C calc'!A0",
        "section": "A",
        "time_taken_seconds": 400,
        "answers": [{"question_id": d_json["questions"][0]["id"], "typed_answer": "Draft"}],
    })
    assert sub2.status_code == 200

    # Grade student 1
    grade_resp = client.post(f"/api/submissions/{sub1_id}/grade", json={
        "grades": [
            {"question_id": d_json["questions"][0]["id"], "marks_awarded": 4.5, "feedback": "Good"},
            {"question_id": d_json["questions"][1]["id"], "marks_awarded": 4.5, "feedback": "Clear"},
        ],
        "overall_feedback": "Well done",
        "is_published": True,
    })
    assert grade_resp.status_code == 200

    # 4. Submissions endpoint includes class stats
    subs_resp = client.get(f"/api/exams/{exam_id}/submissions").json()
    stats = subs_resp["stats"]
    assert stats["total_submissions"] == 2
    assert stats["graded_count"] == 1
    assert stats["pending_count"] == 1
    assert stats["average_score"] == 9.0
    assert stats["highest_score"] == 9.0
    assert stats["pass_rate"] == 100.0

    # 5. CSV Marksheet download + CSV formula injection defense + per-question score columns
    csv_resp = client.get(f"/api/exams/{exam_id}/marksheet.csv")
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    csv_text = csv_resp.text
    assert "Aarav Sharma" in csv_text
    assert "'=CMD|' /C calc'!A0" in csv_text
    assert "Q1 (/5)" in csv_text
    assert "Q2 (/5)" in csv_text
    assert ",4.5,4.5" in csv_text


def test_safe_collaboration_rbac(rbac_client):
    client, test_db, _, admin_headers, teacher_headers = rbac_client

    t1 = "What is fire and ice?"
    t2 = "What do 'fire' and 'ice' symbolize?"
    q1_id, _ = test_db.upsert_question(t1, normalize_question_text(t1), subject="English", topic="Fire and Ice", class_level="Class 10")
    q2_id, _ = test_db.upsert_question(t2, normalize_question_text(t2), subject="English", topic="Fire and Ice", class_level="Class 10")

    dl = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    exam_resp = client.post("/api/exams", headers=teacher_headers, json={
        "title": "RBAC Exam",
        "subject": "English",
        "duration_minutes": 30,
        "deadline": dl,
        "total_marks": 5.0,
        "questions": [{"question_text": "What is fire and ice?", "marks": 5.0, "question_order": 1}],
    })
    assert exam_resp.status_code == 200
    exam_id = exam_resp.json()["id"]

    # Teacher ALLOWED productivity routes
    assert client.post("/api/questions/bulk-update", headers=teacher_headers, json={"question_ids": [q1_id], "difficulty": "Easy"}).status_code == 200
    assert client.get("/api/questions/duplicates", headers=teacher_headers).status_code == 200
    assert client.post("/api/questions/auto-pick", headers=teacher_headers, json={"count": 1}).status_code == 200
    assert client.get(f"/api/exams/{exam_id}/detail", headers=teacher_headers).status_code == 200
    assert client.patch(f"/api/exams/{exam_id}/deadline", headers=teacher_headers, json={"deadline": dl, "reopen_if_closed": True}).status_code == 200
    assert client.get(f"/api/exams/{exam_id}/marksheet.csv", headers=teacher_headers).status_code == 200
    assert client.post("/api/questions/merge", headers=teacher_headers, json={"target_id": q1_id, "source_ids": [q2_id]}).status_code == 200

    # Teacher FORBIDDEN destructive & global curation routes
    assert client.delete(f"/api/questions/{q1_id}", headers=teacher_headers).status_code == 403
    assert client.post("/api/questions/bulk-delete", headers=teacher_headers, json={"question_ids": [q1_id]}).status_code == 403
    assert client.delete(f"/api/exams/{exam_id}", headers=teacher_headers).status_code == 403
    assert client.post("/api/admin/curate/preview", headers=teacher_headers).status_code == 403
    assert client.post("/api/admin/curate/run", headers=teacher_headers).status_code == 403

    # Admin ALLOWED on curation preview and destructive delete
    cur_prev = client.post("/api/admin/curate/preview", headers=admin_headers)
    assert cur_prev.status_code == 200
    assert cur_prev.json()["dry_run"] is True
    assert client.delete(f"/api/exams/{exam_id}", headers=admin_headers).status_code == 200


def test_boost_review_regressions(isolated_client):
    client, test_db, tmp_path = isolated_client

    # (a) /api/export with empty string max_marks (Cart blank max_marks bug)
    qid, _ = test_db.upsert_question(
        "What does the poet mean by 'keep still' in Keeping Quiet?",
        normalize_question_text("What does the poet mean by 'keep still' in Keeping Quiet?"),
        subject="English",
        topic="Keeping Quiet",
        class_level="Class 12",
    )
    for fmt in ("docx", "pdf"):
        resp = client.post("/api/export", json={
            "items": [{"item_type": "question", "question_id": qid, "marks": None}],
            "format": fmt,
            "paper_header": {
                "institute_name": "The Squire's Way",
                "exam_title": "Unit Test",
                "max_marks": "",
                "show_header": True,
            },
        })
        assert resp.status_code == 200, f"{fmt} export failed: {resp.text}"

    # (b) auto_pick_questions must not overshoot target_marks with a heavy leading candidate
    heavy_id, _ = test_db.upsert_question(
        "Write a detailed essay on environmental conservation and its role today.",
        normalize_question_text("Write a detailed essay on environmental conservation and its role today."),
        subject="English",
        topic="Writing & Composition",
        class_level="Class 12",
        default_marks=10.0,
    )
    # Increase frequency so heavy candidate ranks first
    test_db.upsert_question(
        "Write a detailed essay on environmental conservation and its role today.",
        normalize_question_text("Write a detailed essay on environmental conservation and its role today."),
        source_filename="paper2.docx",
    )
    light_id, _ = test_db.upsert_question(
        "Define symbolism in two sentences.",
        normalize_question_text("Define symbolism in two sentences."),
        subject="English",
        topic="Keeping Quiet",
        class_level="Class 12",
        default_marks=2.0,
    )
    pick_res = test_db.auto_pick_questions(target_marks=5.0, prefer_most_repeated=True)
    picked_ids = {q["id"] for q in pick_res["questions"]}
    assert pick_res["total_marks"] <= 5.0
    assert heavy_id not in picked_ids
    assert light_id in picked_ids

    # (c) Mid-string footer stripping + NCERT chapter class override + Writing topic isolation + OCR merge + curator idempotency
    q_footer_id, _ = test_db.upsert_question(
        "Who was M. Hamel in The Last Lesson? Class: 12th (2025-26) Subject: English compulsory Page 2",
        normalize_question_text("Who was M. Hamel in The Last Lesson? Class: 12th (2025-26) Subject: English compulsory Page 2"),
        class_level="Class 11",
        source_filename="class 11th paper 2026.docx",
    )
    # Adjacent context divider followed by a Writing prompt (must NOT inherit Keeping Quiet)
    test_db.upsert_question(
        "Lesson 3 Keeping Quiet",
        normalize_question_text("Lesson 3 Keeping Quiet"),
        class_level="Class 12",
        source_filename="12th_questions.docx",
    )
    w_id, _ = test_db.upsert_question(
        "You are Ananya, Head Girl. Draft a notice inviting students for the debate competition.",
        normalize_question_text("You are Ananya, Head Girl. Draft a notice inviting students for the debate competition."),
        subject="English",
        topic="Keeping Quiet",
        class_level="Class 12",
        source_filename="12th_questions.docx",
    )
    # OCR / quote duplicate pair that curator must merge cleanly
    test_db.upsert_question(
        "Did n't M.hamel scold 'Franz' on his last day?",
        "did n t m hamel scold franz on his last day",
        class_level="Class 12",
        source_filename="p1.docx",
    )
    test_db.upsert_question(
        "Didn't M.Hamel scold \"Franz\" on his last day?",
        normalize_question_text("Didn't M.Hamel scold \"Franz\" on his last day?"),
        class_level="Class 12",
        source_filename="p2.docx",
    )

    cur_apply = curate_question_library(test_db, dry_run=False, create_backup=False)
    assert cur_apply["dividers_removed"] >= 1
    assert cur_apply["duplicates_merged"] >= 1

    updated_footer_qs = test_db.get_questions_by_ids([q_footer_id])
    assert len(updated_footer_qs) == 1
    updated_footer_q = updated_footer_qs[0]
    assert "English compulsory" not in updated_footer_q["question_text"]
    assert updated_footer_q["class_level"] == "Class 12"
    assert updated_footer_q["topic"] == "The Last Lesson"

    updated_w_qs = test_db.get_questions_by_ids([w_id])
    assert len(updated_w_qs) == 1
    updated_w_q = updated_w_qs[0]
    assert updated_w_q["topic"] == "Writing & Composition"

    # Curator idempotency: second dry-run must report zero diffs
    cur_second = curate_question_library(test_db, dry_run=True, create_backup=False)
    assert cur_second["dividers_removed"] == 0
    assert cur_second["duplicates_merged"] == 0
    assert cur_second["questions_cleaned"] == 0
    assert cur_second["footers_stripped"] == 0
    assert cur_second["markers_stripped"] == 0
    assert cur_second["dual_or_split"] == 0


def test_find_potential_duplicates_cross_chapter_separation(isolated_client):
    client, test_db, _ = isolated_client

    # 1. Cross-chapter false positives (~81%-83% similarity) across different non-empty topics must NOT group
    valli_id, _ = test_db.upsert_question(
        "Draw a character-sketch of Valli?",
        normalize_question_text("Draw a character-sketch of Valli?"),
        subject="English",
        topic="Madam Rides the Bus",
        class_level="Class 10",
    )
    lencho_id, _ = test_db.upsert_question(
        "Draw a character-sketch of Lencho?",
        normalize_question_text("Draw a character-sketch of Lencho?"),
        subject="English",
        topic="A Letter to God",
        class_level="Class 10",
    )
    ausable_id, _ = test_db.upsert_question(
        "Draw a character sketch of Ausable.",
        normalize_question_text("Draw a character sketch of Ausable."),
        subject="English",
        topic="The Midnight Visitor",
        class_level="Class 10",
    )
    poem1_id, _ = test_db.upsert_question(
        'What is the message of the poem, "The Ball Poem"?',
        normalize_question_text('What is the message of the poem, "The Ball Poem"?'),
        subject="English",
        topic="The Ball Poem",
        class_level="Class 10",
    )
    poem2_id, _ = test_db.upsert_question(
        'What is the message of the poem, "The Trees"?',
        normalize_question_text('What is the message of the poem, "The Trees"?'),
        subject="English",
        topic="The Trees",
        class_level="Class 10",
    )

    # 2. Empty-topic anchor must not bridge two distinct non-empty topics into one cluster
    anchor_empty_id, _ = test_db.upsert_question(
        "Write a short note on the narrator and his friend.",
        normalize_question_text("Write a short note on the narrator and his friend."),
        subject="English",
        topic="",
        class_level="Class 10",
    )
    chap1_id, _ = test_db.upsert_question(
        "Write a short note on the author and his friend.",
        normalize_question_text("Write a short note on the author and his friend."),
        subject="English",
        topic="Chapter Alpha",
        class_level="Class 10",
    )
    chap2_id, _ = test_db.upsert_question(
        "Write a short note on the poet and his friend.",
        normalize_question_text("Write a short note on the poet and his friend."),
        subject="English",
        topic="Chapter Beta",
        class_level="Class 10",
    )

    # 3. Same-topic typo near-duplicate (~90.4%) with different topic casing/spacing MUST group
    same_a, _ = test_db.upsert_question(
        "Why did Lencho write a letter to God?",
        normalize_question_text("Why did Lencho write a letter to God?"),
        subject="English",
        topic="A Letter to God",
        class_level="Class 10",
    )
    same_b, _ = test_db.upsert_question(
        "Why did Lencho wrote a letter to God?",
        normalize_question_text("Why did Lencho wrote a letter to God?"),
        subject=" english ",
        topic=" a letter to god ",
        class_level="class 10",
    )

    # 4. Near-verbatim (>= 0.95) across different topics MUST still group
    near_a, _ = test_db.upsert_question(
        "Describe the dramatic irony used at the climax of the story.",
        normalize_question_text("Describe the dramatic irony used at the climax of the story."),
        subject="English",
        topic="The Necklace",
        class_level="Class 10",
    )
    near_b, _ = test_db.upsert_question(
        "Describe the dramatic irony used at the climax of story.",
        normalize_question_text("Describe the dramatic irony used at the climax of story."),
        subject="English",
        topic="Footprints Without Feet",
        class_level="Class 10",
    )

    # 5. Cross-subject separation (< 0.95)
    phys_id, _ = test_db.upsert_question(
        "Define potential energy and its SI unit.",
        normalize_question_text("Define potential energy and its SI unit."),
        subject="Physics",
        topic="",
        class_level="Class 10",
    )
    chem_id, _ = test_db.upsert_question(
        "Define ionization energy and its SI unit.",
        normalize_question_text("Define ionization energy and its SI unit."),
        subject="Chemistry",
        topic="",
        class_level="Class 10",
    )

    groups = test_db.find_potential_duplicates(threshold=0.80, limit_groups=50)
    api_groups = client.get("/api/questions/duplicates?threshold=0.80&limit_groups=50").json()["groups"]
    assert len(groups) == len(api_groups)

    id_sets = [{q["id"] for q in g["questions"]} for g in groups]

    # Cross-chapter character-sketches and poem messages are NOT grouped
    for s in id_sets:
        assert not ({valli_id, lencho_id} <= s)
        assert not ({valli_id, ausable_id} <= s)
        assert not ({lencho_id, ausable_id} <= s)
        assert not ({poem1_id, poem2_id} <= s)
        assert not ({chap1_id, chap2_id} <= s)
        assert not ({phys_id, chem_id} <= s)

    # Same-topic near-duplicate IS grouped
    assert any({same_a, same_b} <= s for s in id_sets)
    # Near-verbatim (>= 0.95) cross-topic IS grouped at 0.80, but NOT at stricter threshold=0.99
    assert any({near_a, near_b} <= s for s in id_sets)
    strict_groups = test_db.find_potential_duplicates(threshold=0.99, limit_groups=50)
    strict_sets = [{q["id"] for q in g["questions"]} for g in strict_groups]
    assert not any({near_a, near_b} <= s for s in strict_sets)
    # Empty-topic anchor can match at most one non-empty topic cluster, never both
    assert not any({anchor_empty_id, chap1_id, chap2_id} <= s for s in id_sets)


def test_postgres_create_submission_timestamp_parity_and_section_fields(tmp_path):
    from backend.database import _iso_ts

    naive_dt = datetime(2026, 11, 25, 10, 30, 0)
    assert _iso_ts(naive_dt) == "2026-11-25T10:30:00+00:00"
    assert _iso_ts("2026-11-25 10:30:00") == "2026-11-25T10:30:00+00:00"

    db_path = str(tmp_path / "pg_parity.db")
    test_db = Database(db_path)

    # Verify Postgres create_submission branch uses _iso_ts(row[1]) instead of str(row[1])
    class FakePgCursor:
        def __init__(self):
            self._next_fetchone = None

        def execute(self, query, params=None):
            if "SELECT id FROM exam_submissions" in query:
                self._next_fetchone = None
            elif "INSERT INTO exam_submissions" in query:
                self._next_fetchone = (77, naive_dt)
            else:
                self._next_fetchone = None

        def fetchone(self):
            return self._next_fetchone

    class FakePgConn:
        def commit(self):
            pass

        def rollback(self):
            pass

    @contextmanager
    def fake_pg_conn():
        yield FakePgConn()

    orig_is_pg = test_db.is_postgres
    orig_get_conn = test_db.get_connection
    orig_get_cur = test_db._get_cursor
    try:
        test_db.is_postgres = True
        test_db.get_connection = fake_pg_conn
        test_db._get_cursor = lambda conn: FakePgCursor()

        pg_res = test_db.create_submission(
            exam_id=1,
            student_name="PG Student",
            roll_number="pg-001",
            section="A",
            time_taken_seconds=120,
            answers=[{"question_id": 10, "typed_answer": "Ans", "image_data": ""}],
        )
        assert pg_res["submission_id"] == 77
        assert pg_res["submitted_at"] == "2026-11-25T10:30:00+00:00"
    finally:
        test_db.is_postgres = orig_is_pg
        test_db.get_connection = orig_get_conn
        test_db._get_cursor = orig_get_cur

    # Verify section_title, class_level, institute_name flow into public exam, submission detail, and result
    exam = test_db.create_exam(
        title="The Squire's Way Midterm",
        subject="English",
        class_level="Class 10",
        institute_name="The Squire's Way Academy",
        duration_minutes=45,
        deadline=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        questions=[
            {"question_text": "Q1 text", "marks": 5.0, "question_order": 1, "section_title": "Section A: Reading"},
        ],
    )
    q_id = exam["questions"][0]["id"]
    sub = test_db.create_submission(
        exam_id=exam["id"],
        student_name="Test Student",
        roll_number="ROLL-SEC-1",
        answers=[{"question_id": q_id, "typed_answer": "My answer"}],
    )
    detail = test_db.get_submission_detail(sub["submission_id"])
    assert detail["answers"][0]["section_title"] == "Section A: Reading"

    test_db.grade_submission(
        submission_id=sub["submission_id"],
        grades=[{"question_id": q_id, "marks_awarded": 4.0, "feedback": "Good"}],
    )
    result = test_db.get_submission_by_exam_and_roll(exam["id"], "ROLL-SEC-1")
    assert result["questions"][0]["section_title"] == "Section A: Reading"


def test_frontend_delegation_state_sync_and_hygiene():
    root = os.path.dirname(os.path.dirname(__file__))
    gitignore = open(os.path.join(root, ".gitignore"), encoding="utf-8").read()
    assert "backups/" in gitignore

    index_html = open(os.path.join(root, "static", "index.html"), encoding="utf-8").read()
    exam_html = open(os.path.join(root, "static", "exam.html"), encoding="utf-8").read()
    app_js = open(os.path.join(root, "static", "app.js"), encoding="utf-8").read()
    exam_js = open(os.path.join(root, "static", "exam.js"), encoding="utf-8").read()

    assert "/static/app.js?v=3.7.3" in index_html
    assert "/static/style.css?v=3.7.3" in index_html
    assert "/static/exam.js?v=3.7.3" in exam_html
    assert "/static/style.css?v=3.7.3" in exam_html
    assert 'id="entry-institute-name"' in exam_html

    # No string-interpolated inline onclick handlers remain
    forbidden_patterns = [
        r'onclick="openExamQrModal\(',
        r'onclick="copyExamLink\(',
        r'onclick="handleResetUserPasswordPrompt\(',
        r'onclick="handleDeleteUser\(',
        r'onclick="appendQuestionFeedback\(',
        r'onclick="openPhotoZoomModal\(',
        r'onclick="openStudentPhotoZoom\(',
    ]
    for pat in forbidden_patterns:
        assert not re.search(pat, app_js), f"Found unsafe inline onclick matching {pat} in app.js"
        assert not re.search(pat, exam_js), f"Found unsafe inline onclick matching {pat} in exam.js"

    # openExamSetupModal must not keep stale instructions via `if (!instructionsInput.value.trim())`
    assert "if (!instructionsInput.value.trim())" not in app_js

    # Run real Node behavioral checks for delegated handlers & state sync if node is available
    node_bin = shutil.which("node")
    assert node_bin, "Node.js is required to verify JS syntax and DOM behaviors"

    js_probe = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

function makeClassList(initial = []) {
    const set = new Set(initial);
    return {
        add: (...cls) => cls.forEach(c => set.add(c)),
        remove: (...cls) => cls.forEach(c => set.delete(c)),
        toggle: (c, force) => {
            if (force === undefined) {
                if (set.has(c)) { set.delete(c); return false; }
                set.add(c); return true;
            }
            if (force) set.add(c); else set.delete(c);
            return Boolean(force);
        },
        contains: (c) => set.has(c),
        toString: () => Array.from(set).join(' ')
    };
}

function makeEl(id = '') {
    const listeners = {};
    const el = {
        id,
        value: '',
        textContent: '',
        innerHTML: '',
        checked: false,
        disabled: false,
        type: 'text',
        style: {},
        dataset: {},
        className: '',
        classList: makeClassList(['hidden']),
        children: [],
        attributes: {},
        addEventListener: (ev, fn) => { (listeners[ev] ||= []).push(fn); },
        dispatchEvent: (evObj) => { (listeners[evObj.type] || []).forEach(fn => fn(evObj)); },
        querySelector: () => ({ addEventListener: () => {} }),
        querySelectorAll: () => [],
        appendChild: (c) => { el.children.push(c); },
        setAttribute: (k, v) => { el.attributes[k] = String(v); },
        getAttribute: (k) => el.attributes[k] ?? null,
        closest: () => null,
        focus: () => {},
        reset: () => {},
        click: () => {},
        remove: () => {}
    };
    return el;
}

const byId = new Map();
const getEl = (id) => {
    if (!byId.has(id)) byId.set(id, makeEl(id));
    return byId.get(id);
};

// Pre-create key elements for app.js
['exams-table-container', 'user-mgmt-table-body', 'grading-questions-container',
 'questions-container', 'exam-setup-modal', 'setup-exam-title', 'setup-exam-institute',
 'setup-exam-class', 'setup-exam-subject', 'setup-exam-duration', 'setup-exam-deadline',
 'setup-exam-instructions', 'marks-mode-custom', 'marks-mode-equal', 'equal-marks-container',
 'custom-marks-container', 'setup-total-marks-label', 'setup-equal-marks-val',
 'paper-title-input', 'cart-header-institute', 'cart-header-class-subject', 'cart-header-time',
 'cart-header-max-marks', 'cart-header-instructions', 'cart-badge', 'open-cart-btn',
 'cart-items-container', 'cart-count-subtitle', 'cart-total-marks', 'export-docx-btn',
 'export-pdf-btn', 'pagination-info', 'prev-page-btn', 'next-page-btn', 'page-indicator',
 'bulk-action-bar', 'bulk-selected-count', 'select-all-page-cb', 'bulk-add-cart-btn',
 'bulk-delete-btn', 'bulk-merge-btn', 'stat-total', 'exam-qr-modal', 'dash-qr-title',
 'dash-qr-code', 'dash-qr-container', 'btn-download-dash-qr'].forEach(getEl);

const storage = {};
const docListeners = {};
let copiedText = '';
const sandbox = {
    console, setTimeout, clearTimeout, setInterval, clearInterval,
    URLSearchParams, Map, Set, Array, Object, Number, String, Boolean, JSON, Math, Date, parseInt, parseFloat, isNaN, encodeURIComponent, decodeURIComponent,
    localStorage: {
        getItem: (k) => storage[k] ?? null,
        setItem: (k, v) => { storage[k] = String(v); },
        removeItem: (k) => { delete storage[k]; }
    },
    sessionStorage: {
        getItem: () => null,
        setItem: () => {},
        removeItem: () => {}
    },
    navigator: { clipboard: { writeText: async (t) => { copiedText = t; } } },
    document: {
        readyState: 'complete',
        documentElement: { classList: makeClassList() },
        body: makeEl('body'),
        getElementById: getEl,
        querySelector: () => null,
        querySelectorAll: () => [],
        createElement: (tag) => makeEl(tag),
        addEventListener: (ev, fn) => { (docListeners[ev] ||= []).push(fn); }
    },
    location: { origin: 'https://example.test', hash: '#bank' },
    addEventListener: () => {},
    matchMedia: () => ({ matches: false, addEventListener: () => {} }),
    fetch: async (u) => {
        if (String(u).includes('/api/auth/status')) {
            return { ok: true, json: async () => ({ protected: true, authenticated: false }) };
        }
        return { ok: true, json: async () => ({}) };
    },
    confirm: () => true,
    prompt: () => null
};
sandbox.window = sandbox;
sandbox.window.document = sandbox.document;
sandbox.globalThis = sandbox;

vm.createContext(sandbox);
const appCode = fs.readFileSync(process.argv[1], 'utf8');
vm.runInContext(appCode, sandbox);
// Fire DOMContentLoaded so setupEventListeners registers userMgmtTableBody handler
(docListeners['DOMContentLoaded'] || []).forEach(fn => fn());

// 4. Test student exam.js compatibility with institute_name, class_level, section_title & safe photo zoom
const examById = new Map();
const getExamEl = (id) => {
    if (!examById.has(id)) examById.set(id, makeEl(id));
    return examById.get(id);
};
const examDocListeners = {};
const examSandbox = {
    console, setTimeout, clearTimeout, setInterval, clearInterval,
    URLSearchParams, Map, Set, Array, Object, Number, String, Boolean, JSON, Math, Date, parseInt, parseFloat, isNaN, encodeURIComponent, decodeURIComponent,
    localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
    navigator: { onLine: true },
    document: {
        readyState: 'complete',
        getElementById: getExamEl,
        querySelector: () => null,
        querySelectorAll: () => [],
        createElement: (tag) => makeEl(tag),
        addEventListener: (ev, fn) => { (examDocListeners[ev] ||= []).push(fn); }
    },
    location: { pathname: '/exam/ENG-2026-Q9Z' },
    prompt: () => 'R1',
    addEventListener: () => {},
    fetch: async (u) => {
        if (String(u).includes('/result?')) {
            return {
                ok: true,
                json: async () => ({
                    status: 'published',
                    student_name: 'Alice',
                    roll_number: 'R1',
                    total_score: 5,
                    total_marks: 10,
                    percentage: 50,
                    questions: [{
                        question_order: 1,
                        section_title: 'Section A: Reading',
                        question_text: 'Q1?',
                        marks: 5,
                        marks_awarded: 5,
                        image_data: 'data:image/webp;base64,SCORECARD123'
                    }]
                })
            };
        }
        return {
            ok: true,
            json: async () => ({
                id: 1,
                exam_code: 'ENG-2026-Q9Z',
                title: "The Squire's Way Exam",
                subject: 'English',
                class_level: 'Class 10',
                institute_name: "The Squire's Way Academy",
                duration_minutes: 60,
                deadline: new Date(Date.now() + 86400000).toISOString(),
                total_marks: 10,
                instructions: 'Read well.',
                questions_count: 2,
                server_now_utc: new Date().toISOString(),
                questions: [
                    { id: 1, question_order: 1, question_text: 'Q1?', marks: 5, section_title: 'Section A: Reading' },
                    { id: 2, question_order: 2, question_text: 'Q2?', marks: 5, section_title: 'Section B: Writing' }
                ]
            })
        };
    }
};
examSandbox.window = examSandbox;
examSandbox.window.document = examSandbox.document;
vm.createContext(examSandbox);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), examSandbox);

(async () => {
    // 1. Test renderExamsList with apostrophe + quotes + backslash in title
    const trickyTitle = "The Squire's Way \\ \"Midterm\"";
    vm.runInContext(`
        examsState.currentExams = [{
            id: 101,
            exam_code: "ENG-2026-Q9Z",
            title: ${JSON.stringify(trickyTitle)},
            class_level: "Class 10",
            subject: "English",
            duration_minutes: 60,
            deadline: new Date(Date.now() + 86400000).toISOString(),
            questions_count: 2,
            total_marks: 10,
            submissions_count: 0,
            pending_count: 0,
            status: "active"
        }];
        renderExamsList(examsState.currentExams);
    `, sandbox);
    const examsHtml = getEl('exams-table-container').innerHTML;
    assert(!examsHtml.includes('onclick="'), 'renderExamsList must not emit inline onclick');
    assert(examsHtml.includes('data-exam-action="show-qr"'), 'renderExamsList must emit data-exam-action="show-qr"');
    assert(examsHtml.includes('data-exam-action="copy-link"'), 'renderExamsList must emit data-exam-action="copy-link"');

    // Trigger delegated QR & copy-link click handlers on exams-table-container
    const qrBtn = {
        dataset: { examAction: 'show-qr', examId: '101', examCode: 'ENG-2026-Q9Z', examTitle: trickyTitle }
    };
    getEl('exams-table-container').dispatchEvent({
        type: 'click',
        target: { closest: (sel) => sel.includes('data-exam-action') ? qrBtn : null }
    });
    assert.strictEqual(getEl('dash-qr-title').textContent, trickyTitle);
    assert.strictEqual(getEl('dash-qr-code').textContent, 'ENG-2026-Q9Z');

    const copyBtn = {
        dataset: { examAction: 'copy-link', examId: '101', examUrl: 'https://example.test/exam/ENG-2026-Q9Z' }
    };
    getEl('exams-table-container').dispatchEvent({
        type: 'click',
        target: { closest: (sel) => sel.includes('data-exam-action') ? copyBtn : null }
    });
    assert.strictEqual(copiedText, 'https://example.test/exam/ENG-2026-Q9Z');

    // 1b. Test renderGradingQuestions emits safe data-* handlers and delegated zoom/feedback works
    vm.runInContext(`
        examsState.activeSubmissionDetail = {
            id: 9,
            answers: [{
                question_id: 77,
                question_order: 1,
                question_text: "Explain poem.",
                section_title: "Section A: Poetry",
                max_marks: 5,
                marks_awarded: null,
                typed_answer: "Answer",
                image_data: "data:image/png;base64,abc'def",
                feedback: ""
            }]
        };
        renderGradingQuestions(examsState.activeSubmissionDetail.answers);
    `, sandbox);
    const gradingHtml = getEl('grading-questions-container').innerHTML;
    assert(!gradingHtml.includes('onclick="'), 'renderGradingQuestions must not emit inline onclick');
    assert(gradingHtml.includes('data-grade-action="zoom-photo"'));
    assert(gradingHtml.includes('data-grade-action="feedback-chip"'));
    assert(gradingHtml.includes('Section A: Poetry'));

    const zoomBtn = { dataset: { gradeAction: 'zoom-photo', qId: '77', photoTitle: 'Question 1' }, closest: () => null };
    getEl('grading-questions-container').dispatchEvent({
        type: 'click',
        target: { closest: (sel) => sel.includes('data-grade-action') ? zoomBtn : null }
    });
    assert.strictEqual(getEl('photo-zoom-img').src, "data:image/png;base64,abc'def");

    const fbInp = makeEl('fb-inp');
    const marksInp = makeEl('marks-inp');
    const fakeCard = { querySelector: (s) => s === '.grade-feedback-input' ? fbInp : (s === '.grade-marks-input' ? marksInp : null) };
    const chipBtn = { dataset: { gradeAction: 'feedback-chip', chip: "Well explained" }, closest: () => fakeCard };
    getEl('grading-questions-container').dispatchEvent({
        type: 'click',
        target: { closest: (sel) => sel.includes('data-grade-action') ? chipBtn : null }
    });
    assert.strictEqual(fbInp.value, 'Well explained');

    // 1c. Test loadUsersList emits data-user-action without inline onclick, parses SQLite timestamps, and handles apostrophe/backslash username
    let capturedResetArgs = null;
    vm.runInContext(`
        state.currentUser = { id: 1, role: 'admin', username: 'admin' };
        apiFetch = async (u) => u === '/api/admin/users' ? ({
            ok: true,
            json: async () => ([{ id: 2, username: "o'brien\\\\t", display_name: "O'Brien", role: 'teacher', created_at: '2026-11-25 14:23:10' }])
        }) : ({ ok: true, json: async () => ({}) });
    `, sandbox);
    sandbox.handleResetUserPasswordPrompt = (uid, uname) => { capturedResetArgs = [uid, uname]; };
    await vm.runInContext(`loadUsersList()`, sandbox);
    const usersHtml = getEl('user-mgmt-table-body').innerHTML;
    assert(!usersHtml.includes('onclick="'), 'loadUsersList must not emit inline onclick');
    assert(usersHtml.includes('data-user-action="reset-password"'));
    assert(usersHtml.includes('>2026-11-25<'), 'SQLite space-separated created_at must format to YYYY-MM-DD');
    const resetBtn = { dataset: { userAction: 'reset-password', userId: '2', username: "o'brien\\t" } };
    getEl('user-mgmt-table-body').dispatchEvent({
        type: 'click',
        target: { closest: (sel) => sel.includes('data-user-action') ? resetBtn : null }
    });
    assert.deepStrictEqual(capturedResetArgs, [2, "o'brien\\t"]);

    // 2. Test openExamSetupModal resets stale instructions cleanly
    vm.runInContext(`
        state.cart = [{ item_type: 'question', id: 5, question_text: 'Sample Q?', class_level: 'Class 10', subject: 'English', marks: 5 }];
        document.getElementById('setup-exam-instructions').value = 'STALE INSTRUCTIONS FROM OLD EXAM';
        state.paperHeader.instructions = '';
        openExamSetupModal();
    `, sandbox);
    const resetInstr = getEl('setup-exam-instructions').value;
    assert(!resetInstr.includes('STALE INSTRUCTIONS'), 'openExamSetupModal must overwrite stale instructions');
    assert(resetInstr.includes('Answer all questions'), 'openExamSetupModal must reset to default instructions when paperHeader.instructions is blank');

    vm.runInContext(`
        state.paperHeader.instructions = 'Custom Cart Instructions Only';
        openExamSetupModal();
    `, sandbox);
    assert.strictEqual(getEl('setup-exam-instructions').value, 'Custom Cart Instructions Only');

    // 3. Test cloneExamToCart re-renders currently loaded questions cards & preserves filtered state.totalQuestions
    vm.runInContext(`
        document.getElementById('stat-total').textContent = '870';
        state.currentQuestions = [
            { id: 10, question_text: 'Old Q', frequency: 1, sources: [] },
            { id: 20, question_text: 'Cloned Q', frequency: 1, sources: [] }
        ];
        state.totalQuestions = 2;
        state.cart = [{ item_type: 'question', id: 10, question_text: 'Old Q', marks: 5 }];
        state.expandedCartItems.add(0);
        renderQuestions({ items: state.currentQuestions, total: 2 });
        toggleCartQuestion(20);
    `, sandbox);
    assert(getEl('pagination-info').textContent.includes('of 2 questions'), 'toggleCartQuestion must preserve filtered totalQuestions instead of statTotal');

    vm.runInContext(`
        apiFetch = async () => ({
            ok: true,
            json: async () => ({
                id: 55,
                title: "The Squire's Cloned Exam",
                subject: "English",
                class_level: "Class 10",
                institute_name: "The Squire's Way",
                duration_minutes: 45,
                instructions: "New instructions",
                questions: [{ question_id: 20, question_text: "Cloned Q", marks: 4, section_title: "Section A" }]
            })
        });
        confirm = () => true;
    `, sandbox);
    assert(getEl('questions-container').innerHTML.includes('toggleCartQuestion(10)'), 'initial render check');
    await vm.runInContext(`cloneExamToCart(55)`, sandbox);
    assert.strictEqual(vm.runInContext(`state.expandedCartItems.size`, sandbox), 0, 'cloneExamToCart must clear expandedCartItems');
    assert(getEl('pagination-info').textContent.includes('of 2 questions'), 'cloneExamToCart must preserve filtered totalQuestions');
    const qHtml = getEl('questions-container').innerHTML;
    const idx20 = qHtml.indexOf('toggleCartQuestion(20)');
    const btn20End = qHtml.indexOf('</button>', idx20);
    assert(qHtml.slice(idx20, btn20End).includes('In Cart'), 'Cloned question #20 card must flip to In Cart');
    const idx10 = qHtml.indexOf('toggleCartQuestion(10)');
    const btn10End = qHtml.indexOf('</button>', idx10);
    assert(qHtml.slice(idx10, btn10End).includes('Add to Cart'), 'Replaced question #10 card must revert to Add to Cart');

    // 4. Verify exam.js entry screen, section rendering, photo retake value clearing, and scorecard zoom delegation
    await new Promise(r => setTimeout(r, 20));
    assert.strictEqual(getExamEl('entry-institute-name').textContent, "The Squire's Way Academy");
    assert.strictEqual(getExamEl('entry-exam-subject').textContent, 'Class 10 • English');
    getExamEl('student-name-input').value = 'Alice';
    getExamEl('student-roll-input').value = 'R1';
    getExamEl('student-entry-form').onsubmit({ preventDefault: () => {} });
    const examQsHtml = getExamEl('exam-questions-container').innerHTML;
    assert(examQsHtml.includes('Section A: Reading'));
    assert(examQsHtml.includes('Section B: Writing'));
    assert(!examQsHtml.includes('openStudentPhotoZoom('));

    const fileInput1 = getExamEl('q-file-1');
    fileInput1.value = 'C:\\\\fakepath\\\\photo.jpg';
    const pickTarget = { dataset: { examAction: 'pick-photo', qId: '1' } };
    getExamEl('exam-questions-container').dispatchEvent({
        type: 'click',
        target: { closest: (sel) => sel.includes('data-exam-action') ? pickTarget : null }
    });
    assert.strictEqual(fileInput1.value, '', 'pick-photo must clear input.value so same-file retake fires change');

    fileInput1.value = 'C:\\\\fakepath\\\\photo.jpg';
    examSandbox.removeAnswerPhoto(1);
    assert.strictEqual(fileInput1.value, '', 'removeAnswerPhoto must clear input.value');

    // Scorecard lookup + zoom delegation with data-scorecard-action
    getExamEl('btn-lookup-result-entry').onclick();
    await new Promise(r => setTimeout(r, 20));
    const scHtml = getExamEl('scorecard-questions-breakdown').innerHTML;
    assert(!scHtml.includes('openStudentPhotoZoom('));
    assert(scHtml.includes('data-scorecard-action="zoom-photo"'));
    const scZoomTarget = { dataset: { scorecardAction: 'zoom-photo', qIdx: '0' } };
    getExamEl('scorecard-questions-breakdown').dispatchEvent({
        type: 'click',
        target: { closest: (sel) => sel.includes('data-scorecard-action') ? scZoomTarget : null }
    });
    assert.strictEqual(getExamEl('student-photo-zoom-img').src, 'data:image/webp;base64,SCORECARD123');

    console.log('NODE_HTML_JSON:' + JSON.stringify({ examsHtml, gradingHtml, usersHtml, examQsHtml, scHtml }));
    console.log('NODE_BEHAVIOR_OK');
    process.exit(0);
})().catch(err => {
    console.error(err);
    process.exit(1);
});
"""
    app_js_path = os.path.join(root, "static", "app.js")
    exam_js_path = os.path.join(root, "static", "exam.js")
    proc = subprocess.run([node_bin, "-e", js_probe, app_js_path, exam_js_path], capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, f"Node probe failed:\nSTDOUT:{proc.stdout}\nSTDERR:{proc.stderr}"
    assert "NODE_BEHAVIOR_OK" in proc.stdout

    # Parse actual emitted HTML fragments using lxml.html to verify attribute escaping & round-trip decoding
    from lxml import html as lxml_html
    json_line = [ln for ln in proc.stdout.splitlines() if ln.startswith("NODE_HTML_JSON:")][0]
    emitted = json.loads(json_line.split("NODE_HTML_JSON:", 1)[1])

    exams_tree = lxml_html.fragment_fromstring(emitted["examsHtml"], create_parent="div")
    qr_btns = [el for el in exams_tree.iter("button") if el.attrib.get("data-exam-action") == "show-qr"]
    assert len(qr_btns) == 1
    assert qr_btns[0].attrib["data-exam-title"] == 'The Squire\'s Way \\ "Midterm"'
    assert qr_btns[0].attrib["data-exam-code"] == "ENG-2026-Q9Z"

    users_tree = lxml_html.fragment_fromstring(emitted["usersHtml"], create_parent="tbody")
    reset_btns = [el for el in users_tree.iter("button") if el.attrib.get("data-user-action") == "reset-password"]
    assert len(reset_btns) == 1
    assert reset_btns[0].attrib["data-username"] == "o'brien\\t"

    grade_tree = lxml_html.fragment_fromstring(emitted["gradingHtml"], create_parent="div")
    grade_zoom_btns = [el for el in grade_tree.iter("button") if el.attrib.get("data-grade-action") == "zoom-photo"]
    assert len(grade_zoom_btns) == 1
    assert grade_zoom_btns[0].attrib["data-q-id"] == "77"

    sc_tree = lxml_html.fragment_fromstring(emitted["scHtml"], create_parent="div")
    sc_zoom_btns = [el for el in sc_tree.iter("button") if el.attrib.get("data-scorecard-action") == "zoom-photo"]
    assert len(sc_zoom_btns) == 1
    assert sc_zoom_btns[0].attrib["data-q-idx"] == "0"

