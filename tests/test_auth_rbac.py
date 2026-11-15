import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from backend.main import app, db
import backend.main as main_module
from backend.database import Database
from backend.services.security import (
    hash_password,
    verify_password,
    session_manager,
    auth_rate_limiter,
    ensure_admin_user
)

@pytest.fixture
def auth_client():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name

    test_db = Database(temp_db_path)
    original_db = main_module.db
    main_module.db = test_db

    # Ensure admin user is seeded
    ensure_admin_user(test_db)

    # Enable master password mode so auth is enforced
    orig_pass = main_module.APP_PASSWORD
    main_module.APP_PASSWORD = "squire2026"

    # Reset rate limiters and session manager
    auth_rate_limiter.reset_all()
    session_manager.reset_all()

    client = TestClient(app)
    yield client, test_db

    # Cleanup
    main_module.db = original_db
    main_module.APP_PASSWORD = orig_pass
    auth_rate_limiter.reset_all()
    session_manager.reset_all()
    try:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)
    except Exception:
        pass


def test_password_hashing():
    pwd = "MySecretPassword123!"
    p_hash, salt = hash_password(pwd)
    assert len(p_hash) == 64
    assert len(salt) == 32
    assert verify_password(pwd, p_hash, salt) is True
    assert verify_password("WrongPassword", p_hash, salt) is False


def test_session_manager():
    sm = session_manager
    sm.reset_all()
    user = {"id": 1, "username": "admin", "display_name": "Admin", "role": "admin"}
    token = sm.create_session(user)
    assert token is not None

    session = sm.get_session(token)
    assert session is not None
    assert session["username"] == "admin"

    # Destroy session
    assert sm.destroy_session(token) is True
    assert sm.get_session(token) is None


def test_auth_login_flow(auth_client):
    client, test_db = auth_client

    # 1. Invalid username
    r1 = client.post("/api/auth/login", json={"username": "nonexistent", "password": "any"})
    assert r1.status_code == 401

    # 2. Invalid password for admin
    r2 = client.post("/api/auth/login", json={"username": "admin", "password": "wrongpassword"})
    assert r2.status_code == 401

    # 3. Valid login
    r3 = client.post("/api/auth/login", json={"username": "admin", "password": "squire2026"})
    assert r3.status_code == 200
    data = r3.json()
    assert "token" in data
    assert data["user"]["username"] == "admin"
    assert data["user"]["role"] == "admin"
    admin_token = data["token"]

    # 4. Access /api/auth/me with Bearer token
    me_resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["user"]["username"] == "admin"

    # 5. Logout
    out_resp = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {admin_token}"})
    assert out_resp.status_code == 200

    # 6. Accessing again fails
    me_after = client.get("/api/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert me_after.status_code == 401


def test_rbac_admin_vs_teacher(auth_client):
    client, test_db = auth_client

    # Admin logs in
    admin_login = client.post("/api/auth/login", json={"username": "admin", "password": "squire2026"}).json()
    admin_token = admin_login["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Admin creates a Teacher account
    create_teacher_resp = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "username": "teacher_jane",
            "display_name": "Jane Teacher",
            "password": "teacherpass123",
            "role": "teacher"
        }
    )
    assert create_teacher_resp.status_code == 200
    teacher_id = create_teacher_resp.json()["id"]

    # Teacher logs in
    teacher_login = client.post(
        "/api/auth/login",
        json={"username": "teacher_jane", "password": "teacherpass123"}
    ).json()
    teacher_token = teacher_login["token"]
    teacher_headers = {"Authorization": f"Bearer {teacher_token}"}

    # 1. Teacher can add a question
    add_resp = client.post(
        "/api/questions",
        headers=teacher_headers,
        json={"question_text": "What is the speed of light in vacuum?", "subject": "Physics"}
    )
    assert add_resp.status_code == 200
    q_id = add_resp.json()["id"]

    # 2. Teacher CANNOT delete question -> 403 Forbidden
    del_resp = client.delete(f"/api/questions/{q_id}", headers=teacher_headers)
    assert del_resp.status_code == 403
    assert "Forbidden" in del_resp.json()["detail"]

    # 3. Teacher CANNOT bulk-delete -> 403 Forbidden
    bulk_del_resp = client.post(
        "/api/questions/bulk-delete",
        headers=teacher_headers,
        json={"question_ids": [q_id]}
    )
    assert bulk_del_resp.status_code == 403

    # 4. Teacher CANNOT access Admin User Management -> 403 Forbidden
    user_list_resp = client.get("/api/admin/users", headers=teacher_headers)
    assert user_list_resp.status_code == 403

    # 5. Teacher CANNOT access Database Backup -> 403 Forbidden
    backup_resp = client.get("/api/backup", headers=teacher_headers)
    assert backup_resp.status_code == 403

    # 6. Admin CAN delete the question -> 200 OK
    admin_del = client.delete(f"/api/questions/{q_id}", headers=admin_headers)
    assert admin_del.status_code == 200


def test_user_management_and_password_change(auth_client):
    client, test_db = auth_client

    # Admin logs in
    admin_login = client.post("/api/auth/login", json={"username": "admin", "password": "squire2026"}).json()
    admin_headers = {"Authorization": f"Bearer {admin_login['token']}"}

    # List users
    users_resp = client.get("/api/admin/users", headers=admin_headers)
    assert users_resp.status_code == 200
    assert len(users_resp.json()) >= 1

    # Admin creates another user
    u_resp = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "username": "mr_smith",
            "display_name": "John Smith",
            "password": "initial_password",
            "role": "teacher"
        }
    )
    assert u_resp.status_code == 200
    smith_id = u_resp.json()["id"]

    # User logs in and changes own password
    smith_login = client.post("/api/auth/login", json={"username": "mr_smith", "password": "initial_password"}).json()
    smith_headers = {"Authorization": f"Bearer {smith_login['token']}"}

    change_resp = client.post(
        "/api/auth/change-password",
        headers=smith_headers,
        json={"old_password": "initial_password", "new_password": "brand_new_secret"}
    )
    assert change_resp.status_code == 200

    # Old password no longer works
    assert client.post("/api/auth/login", json={"username": "mr_smith", "password": "initial_password"}).status_code == 401

    # New password works
    assert client.post("/api/auth/login", json={"username": "mr_smith", "password": "brand_new_secret"}).status_code == 200

    # Admin resets password for mr_smith
    reset_resp = client.post(
        f"/api/admin/users/{smith_id}/reset-password",
        headers=admin_headers,
        json={"new_password": "reset_by_admin_123"}
    )
    assert reset_resp.status_code == 200
    assert client.post("/api/auth/login", json={"username": "mr_smith", "password": "reset_by_admin_123"}).status_code == 200

    # Admin tries to delete self -> 400 Bad Request
    self_del = client.delete(f"/api/admin/users/{admin_login['user']['id']}", headers=admin_headers)
    assert self_del.status_code == 400

    # Admin deletes mr_smith -> 200 OK
    del_smith = client.delete(f"/api/admin/users/{smith_id}", headers=admin_headers)
    assert del_smith.status_code == 200
