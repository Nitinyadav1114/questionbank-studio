import os
import tempfile
import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
from backend.main import app
from backend.database import Database
from backend.services.security import (
    SessionManager,
    session_manager,
    auth_rate_limiter,
    ensure_admin_user,
)


@pytest.fixture
def env_client():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name

    test_db = Database(temp_db_path)
    original_db = main_module.db
    main_module.db = test_db
    ensure_admin_user(test_db)

    orig_pass = main_module.APP_PASSWORD
    main_module.APP_PASSWORD = "squire2026"
    auth_rate_limiter.reset_all()
    session_manager.reset_all()

    client = TestClient(app)
    yield client, test_db

    main_module.db = original_db
    main_module.APP_PASSWORD = orig_pass
    auth_rate_limiter.reset_all()
    session_manager.reset_all()
    try:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)
    except Exception:
        pass


def test_persistent_sessions_survive_restart(env_client):
    client, test_db = env_client
    login_resp = client.post("/api/auth/login", json={"username": "admin", "password": "squire2026"})
    assert login_resp.status_code == 200
    token = login_resp.json()["token"]

    # Simulate a server restart by clearing only the in-memory dict (DB retains user_sessions)
    session_manager.sessions.clear()

    me_resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["user"]["username"] == "admin"

    # Also verify a brand new SessionManager instance bound to test_db validates the token
    fresh_sm = SessionManager()
    fresh_sm.bind_database(test_db)
    sess = fresh_sm.get_session(token)
    assert sess is not None
    assert sess["username"] == "admin"


def test_account_lifecycle_edit_suspend_reset_force_logout(env_client):
    client, test_db = env_client
    admin_token = client.post("/api/auth/login", json={"username": "admin", "password": "squire2026"}).json()["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    admin_id = client.get("/api/auth/me", headers=admin_headers).json()["user"]["user_id"]

    # Create teacher account
    create_resp = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "username": "ms_ananya",
            "display_name": "Ananya Verma",
            "password": "pass_initial",
            "role": "teacher",
        },
    )
    assert create_resp.status_code == 200
    tid = create_resp.json()["id"]

    # Teacher signs in twice to verify active session counting
    t_login1 = client.post("/api/auth/login", json={"username": "ms_ananya", "password": "pass_initial"})
    assert t_login1.status_code == 200
    t_token1 = t_login1.json()["token"]
    t_token2 = client.post("/api/auth/login", json={"username": "ms_ananya", "password": "pass_initial"}).json()["token"]

    users_list = client.get("/api/admin/users", headers=admin_headers).json()
    ananya_row = [u for u in users_list if u["id"] == tid][0]
    assert ananya_row["active_sessions"] >= 2
    assert ananya_row["last_active_at"] is not None

    # Edit display name & promote to admin -> role change must revoke existing sessions
    upd_resp = client.patch(
        f"/api/admin/users/{tid}",
        headers=admin_headers,
        json={"display_name": "Ananya Verma (Lead)", "role": "admin"},
    )
    assert upd_resp.status_code == 200
    assert upd_resp.json()["display_name"] == "Ananya Verma (Lead)"
    assert upd_resp.json()["role"] == "admin"
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {t_token1}"}).status_code == 401

    # Demote back to teacher
    assert client.patch(f"/api/admin/users/{tid}", headers=admin_headers, json={"role": "teacher"}).status_code == 200

    # Admin self-protection: cannot demote self or suspend self
    assert client.patch(f"/api/admin/users/{admin_id}", headers=admin_headers, json={"role": "teacher"}).status_code == 400
    assert client.patch(f"/api/admin/users/{admin_id}/status", headers=admin_headers, json={"is_active": False}).status_code == 400

    # Re-login as teacher, then suspend -> active token immediately rejected & new login returns 403
    t_token3 = client.post("/api/auth/login", json={"username": "ms_ananya", "password": "pass_initial"}).json()["token"]
    susp_resp = client.patch(
        f"/api/admin/users/{tid}/status",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert susp_resp.status_code == 200
    assert susp_resp.json()["is_active"] is False
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {t_token3}"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "ms_ananya", "password": "pass_initial"}).status_code == 403

    # Reactivate -> login works again, then force sign-out revokes sessions
    assert client.patch(f"/api/admin/users/{tid}/status", headers=admin_headers, json={"is_active": True}).status_code == 200
    t_token4 = client.post("/api/auth/login", json={"username": "ms_ananya", "password": "pass_initial"}).json()["token"]
    fl_resp = client.post(f"/api/admin/users/{tid}/force-logout", headers=admin_headers)
    assert fl_resp.status_code == 200
    assert fl_resp.json()["revoked_sessions"] >= 1
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {t_token4}"}).status_code == 401

    # Reset password revokes existing sessions too
    t_token5 = client.post("/api/auth/login", json={"username": "ms_ananya", "password": "pass_initial"}).json()["token"]
    assert client.post(f"/api/admin/users/{tid}/reset-password", headers=admin_headers, json={"new_password": "new_pass_99"}).status_code == 200
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {t_token5}"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "ms_ananya", "password": "new_pass_99"}).status_code == 200


def test_audit_log_attribution_diffs_restore_and_rbac(env_client):
    client, test_db = env_client
    admin_token = client.post("/api/auth/login", json={"username": "admin", "password": "squire2026"}).json()["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Create Teacher & log in as Teacher
    t_create = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={"username": "prof_rahul", "display_name": "Prof. Rahul", "password": "rahul_pass", "role": "teacher"},
    ).json()
    teacher_token = client.post("/api/auth/login", json={"username": "prof_rahul", "password": "rahul_pass"}).json()["token"]
    teacher_headers = {"Authorization": f"Bearer {teacher_token}"}

    # Teacher creates a needs_review question
    add_res = client.post(
        "/api/questions",
        headers=teacher_headers,
        json={
            "question_text": "Explain photoelectric effect.",
            "subject": "Physics",
            "topic": "Dual Nature",
            "class_level": "Class 12",
            "needs_review": True,
            "review_reason": "Verify marks",
        },
    )
    assert add_res.status_code == 200
    qid = add_res.json()["id"]

    # Teacher edits and approves the question
    edit_res = client.put(
        f"/api/questions/{qid}",
        headers=teacher_headers,
        json={
            "question_text": "Explain Einstein's photoelectric equation.",
            "default_marks": 3,
            "needs_review": False,
        },
    )
    assert edit_res.status_code == 200

    # Question carries attribution
    q_data = client.post("/api/questions/by-ids", headers=teacher_headers, json={"question_ids": [qid]}).json()[0]
    assert "prof_rahul" in q_data["updated_by_name"]
    assert "prof_rahul" in q_data["approved_by_name"]

    # Teacher cannot view audit logs or export CSV -> 403
    assert client.get("/api/admin/audit-logs", headers=teacher_headers).status_code == 403
    assert client.get("/api/admin/audit-logs/export", headers=teacher_headers).status_code == 403

    # Admin deletes question
    del_res = client.delete(f"/api/questions/{qid}", headers=admin_headers)
    assert del_res.status_code == 200
    assert client.post("/api/questions/by-ids", headers=admin_headers, json={"question_ids": [qid]}).json() == []

    # Admin checks Audit Logs: sees question.approve diff + question.delete snapshot
    logs_resp = client.get("/api/admin/audit-logs?category=question", headers=admin_headers)
    assert logs_resp.status_code == 200
    items = logs_resp.json()["items"]
    actions = [i["action"] for i in items]
    assert "question.delete" in actions
    assert "question.approve" in actions
    assert "question.create" in actions

    approve_log = [i for i in items if i["action"] == "question.approve"][0]
    assert approve_log["actor_username"] == "prof_rahul"
    assert approve_log["diff"]["before"]["needs_review"] is True
    assert approve_log["diff"]["after"]["needs_review"] is False

    del_log = [i for i in items if i["action"] == "question.delete"][0]
    assert del_log["has_snapshot"] is True
    assert del_log["restored"] is False

    # Admin 1-Click Restores the deleted question
    rest_resp = client.post(f"/api/admin/audit-logs/{del_log['id']}/restore", headers=admin_headers)
    assert rest_resp.status_code == 200
    assert rest_resp.json()["restored_count"] == 1
    restored_q = rest_resp.json()["questions"][0]
    assert restored_q["question_text"] == "Explain Einstein's photoelectric equation."
    assert restored_q["default_marks"] == 3.0

    # Verify audit log entry now marked restored and CSV exports cleanly
    logs_after = client.get("/api/admin/audit-logs?action=question.delete", headers=admin_headers).json()["items"]
    assert logs_after[0]["restored"] is True

    csv_resp = client.get("/api/admin/audit-logs/export", headers=admin_headers)
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    assert "prof_rahul" in csv_resp.text
