import io
import os
import pytest
from fastapi.testclient import TestClient
from docx import Document

from backend.main import app
import backend.main as main_module
from backend.services.security import auth_rate_limiter, validate_file_magic_bytes, MAX_FILE_SIZE_BYTES

@pytest.fixture(autouse=True)
def reset_rate_limiter():
    auth_rate_limiter.reset_all()
    yield
    auth_rate_limiter.reset_all()

@pytest.fixture
def client():
    return TestClient(app)

def test_security_headers(client):
    """Verifies that all responses include OWASP security headers."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "Content-Security-Policy" in resp.headers

def test_rate_limiting_lockout(client):
    """Verifies that 5 failed passcode attempts trigger HTTP 429 lockout."""
    orig_pass = main_module.APP_PASSWORD
    try:
        main_module.APP_PASSWORD = "test_secure_password"

        # 4 failed attempts should return 401
        for i in range(4):
            r = client.post("/api/auth/verify", json={"password": f"wrong_{i}"})
            assert r.status_code == 401, f"Attempt {i+1} should be 401"

        # 5th failed attempt should trigger 429 lockout
        r5 = client.post("/api/auth/verify", json={"password": "wrong_5"})
        assert r5.status_code == 429
        assert "Retry-After" in r5.headers
        assert int(r5.headers["Retry-After"]) > 0

        # Subsequent attempt during lockout period must be blocked with 429 immediately
        r_locked = client.post("/api/auth/verify", json={"password": "test_secure_password"})
        assert r_locked.status_code == 429

    finally:
        main_module.APP_PASSWORD = orig_pass

def test_magic_byte_file_validation(client):
    """Verifies that disguised or corrupted files are rejected by magic byte checking."""
    # Spoofed docx: plain text named .docx
    fake_docx = b"This is just plain text, not a zip or docx archive."
    res1 = client.post(
        "/api/upload",
        files=[("files", ("exam.docx", fake_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))]
    )
    assert res1.status_code == 400
    assert "not have a valid Word (.docx) file signature" in res1.json()["detail"]

    # Spoofed pdf: plain text named .pdf
    fake_pdf = b"This is not a pdf file at all."
    res2 = client.post(
        "/api/upload",
        files=[("files", ("exam.pdf", fake_pdf, "application/pdf"))]
    )
    assert res2.status_code == 400
    assert "not have a valid PDF (.pdf) file signature" in res2.json()["detail"]

    # Valid magic bytes pass validation
    valid_docx_magic = b"PK\x03\x04" + b"\x00" * 20
    is_valid, _ = validate_file_magic_bytes("test.docx", valid_docx_magic)
    assert is_valid is True

    valid_pdf_magic = b"%PDF-1.4\n%test content"
    is_valid_pdf, _ = validate_file_magic_bytes("test.pdf", valid_pdf_magic)
    assert is_valid_pdf is True

def test_payload_length_limits(client):
    """Verifies that questions exceeding 50,000 characters are rejected with 422."""
    giant_text = "A" * 50001
    resp = client.post("/api/questions", json={"question_text": giant_text})
    assert resp.status_code == 422  # Pydantic validation error for max_length
