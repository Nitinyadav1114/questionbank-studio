import io
import os
import re
import csv
import json
import secrets
import asyncio
import hashlib
import traceback
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Request, Depends, Header
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderSVG

from backend.database import Database
from backend.models import (
    QuestionResponse,
    QuestionCreate,
    QuestionUpdate,
    BulkDeleteRequest,
    BulkUpdateQuestionsRequest,
    MergeQuestionsRequest,
    AutoPickRequest,
    ConfirmImportRequest,
    ExportRequest,
    UploadSummary,
    UploadStatsResponse,
    UserResponse,
    UserLogin,
    TokenResponse,
    UserCreate,
    ChangePasswordRequest,
    ResetPasswordRequest,
    ExamCreateRequest,
    ExamQuestionInput,
    ExamDeadlineUpdateRequest,
    StudentSubmissionRequest,
    StudentAnswerInput,
    QuestionGradeInput,
    GradeSubmissionRequest,
    EmergencySubmissionPayload
)
from backend.services.parser import extract_questions_from_file, extract_structured_questions_from_file
from backend.services.dedup import clean_question_text, normalize_question_text
from backend.services.curator import curate_question_library, infer_question_metadata
from backend.services.exporter import generate_word_document, generate_pdf_document
from backend.services.security import (
    auth_rate_limiter,
    session_manager,
    hash_password,
    verify_password,
    ensure_admin_user,
    validate_file_magic_bytes,
    MAX_FILE_SIZE_BYTES,
    MAX_BATCH_SIZE_BYTES
)

# Initialize database and default admin account
DB_PATH = os.environ.get("DATABASE_URL") or os.environ.get("QUESTION_BANK_DB", "questions.db")
db = Database(DB_PATH)
ensure_admin_user(db)

# Legacy master passcode setting (kept for optional backward-compatibility)
APP_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()

class AuthVerifyRequest(BaseModel):
    password: str

def get_client_ip(request: Request) -> str:
    """Extracts client IP, checking X-Forwarded-For if behind a reverse proxy (e.g. Render)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"

def get_current_user(request: Request) -> dict:
    """
    Validates session token from Authorization: Bearer <token>, x-auth-token header,
    or auth_token query parameter. Falls back to APP_PASSWORD if provided.
    If APP_PASSWORD is empty (local dev/unprotected test mode), defaults to admin.
    """
    if not APP_PASSWORD:
        return {"user_id": 1, "username": "admin", "display_name": "Administrator", "role": "admin"}

    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.headers.get("x-auth-token")
    if not token:
        token = request.query_params.get("auth_token")

    if token:
        session = session_manager.get_session(token)
        if session:
            return session

    # Fallback / backward compatibility for legacy master passcode or tests
    header_pass = request.headers.get("x-app-password")
    if header_pass and secrets.compare_digest(header_pass.encode("utf-8"), APP_PASSWORD.encode("utf-8")):
        return {"user_id": 1, "username": "admin", "display_name": "Administrator", "role": "admin"}

    if token and secrets.compare_digest(token.encode("utf-8"), APP_PASSWORD.encode("utf-8")):
        return {"user_id": 1, "username": "admin", "display_name": "Administrator", "role": "admin"}

    raise HTTPException(status_code=401, detail="Authentication required. Please log in.")

def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Enforces that the current authenticated user has the 'admin' role."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admin privileges required.")
    return current_user

def verify_auth(request: Request):
    """Legacy alias: ensures caller is an authenticated user."""
    return get_current_user(request)

app = FastAPI(
    title="Question Bank Manager",
    description="Smart Question Extraction, Deduplication & Word Paper Builder",
    version="1.0.0"
)

# OWASP Security Headers Middleware & Cache Control
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: blob:; "
        "connect-src 'self' https://squire-way-app.onrender.com https://questionbank-studio.onrender.com;"
    )
    # Cache policies: HTML is never cached (always fresh); versioned static assets cached 1 day
    path = request.url.path
    if path == "/" or path.endswith(".html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    elif path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=86400, stale-while-revalidate=3600"
    return response

# Hardened CORS policy: Only allow own Render domain, custom domains, and local development
raw_allowed = os.environ.get("ALLOWED_ORIGINS", "")
allowed_origins = [
    "https://squire-way-app.onrender.com",
    "https://questionbank-studio.onrender.com",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
if raw_allowed:
    for o in raw_allowed.split(","):
        o_clean = o.strip()
        if o_clean and o_clean not in allowed_origins:
            allowed_origins.append(o_clean)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# GZip compression reduces JSON API payloads, JS, and CSS size by 70%-80% over the wire
app.add_middleware(GZipMiddleware, minimum_size=500)

# Worst-Condition Resilience: Concurrency Semaphore & Payload Limit
SUBMISSION_SEMAPHORE = asyncio.Semaphore(15)
MAX_REQUEST_BODY_BYTES = 12 * 1024 * 1024  # 12 MB max payload guard

@app.middleware("http")
async def limit_payload_size(request: Request, call_next):
    """Enforces a strict 12MB payload ceiling to prevent server memory saturation."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Payload too large: Request exceeds 12MB limit. Please compress photos before uploading."}
                )
        except ValueError:
            pass
    return await call_next(request)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global Sanitized Error Boundary: Prevents database strings/traces leaking to clients."""
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None)
        )
    error_id = secrets.token_hex(4)
    print(f"[Error-Boundary-{error_id}] Unhandled exception at {request.method} {request.url.path}: {exc}")
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"An unexpected system condition occurred. Your data has been preserved. Please notify your instructor or support (Error Ref: {error_id})."
        }
    )

@app.get("/healthz")
def health_check():
    """Ultra-fast, zero-overhead health endpoint for container readiness and uptime pingers."""
    return {
        "status": "ok",
        "service": "squire-way-app",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/api/auth/status")
def auth_status(request: Request):
    """Returns whether authentication protection is active and if client is authenticated."""
    if not APP_PASSWORD:
        return {"protected": False, "authenticated": True, "user": {"username": "admin", "role": "admin"}}

    # Check session token
    auth_header = request.headers.get("Authorization")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.headers.get("x-auth-token")
    if not token:
        token = request.query_params.get("auth_token")

    if token:
        session = session_manager.get_session(token)
        if session:
            return {"protected": True, "authenticated": True, "user": session}

    header_pass = request.headers.get("x-app-password")
    is_legacy = bool(header_pass and secrets.compare_digest(header_pass.encode("utf-8"), APP_PASSWORD.encode("utf-8")))
    if is_legacy:
        return {"protected": True, "authenticated": True, "user": {"username": "admin", "role": "admin"}}

    return {"protected": True, "authenticated": False, "user": None}

@app.post("/api/auth/login", response_model=TokenResponse)
def auth_login(request: Request, payload: UserLogin):
    """
    Authenticates a user with username and password, protected by sliding-window rate limiting.
    Issues a high-entropy session token upon success.
    """
    client_ip = get_client_ip(request)

    # Check if client IP is currently locked out
    remaining_lockout = auth_rate_limiter.check_rate_limit(client_ip)
    if remaining_lockout is not None:
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Please wait {remaining_lockout} seconds before trying again.",
            headers={"Retry-After": str(remaining_lockout)}
        )

    username_clean = payload.username.strip()
    user = db.get_user_by_username(username_clean, case_sensitive=True)

    # Check credentials (strictly case-sensitive username)
    is_valid = False
    if user and user.get("is_active"):
        if user.get("username") == username_clean:
            is_valid = verify_password(payload.password, user["password_hash"], user["salt"])
    elif username_clean == "admin" and APP_PASSWORD:
        # Fallback for admin using APP_PASSWORD if set (strictly lowercase 'admin')
        is_valid = secrets.compare_digest(payload.password.encode("utf-8"), APP_PASSWORD.encode("utf-8"))
        if is_valid:
            user = {
                "id": 1,
                "username": "admin",
                "display_name": "Administrator",
                "role": "admin",
                "is_active": True,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }

    if not is_valid or not user:
        is_locked, lockout_secs = auth_rate_limiter.record_failure(client_ip)
        if is_locked:
            raise HTTPException(
                status_code=429,
                detail=f"Maximum failed attempts reached. Your IP is locked for {lockout_secs} seconds.",
                headers={"Retry-After": str(lockout_secs)}
            )
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    # Successful login
    auth_rate_limiter.record_success(client_ip)
    token = session_manager.create_session(user)
    return TokenResponse(
        token=token,
        user=UserResponse(
            id=user["id"],
            username=user["username"],
            display_name=user["display_name"],
            role=user["role"],
            is_active=user["is_active"],
            created_at=str(user["created_at"]),
            updated_at=str(user["updated_at"])
        )
    )

@app.post("/api/auth/logout")
def auth_logout(request: Request):
    """Invalidates the caller's session token."""
    auth_header = request.headers.get("Authorization")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.headers.get("x-auth-token")
    if token:
        session_manager.destroy_session(token)
    return {"success": True, "message": "Logged out successfully"}

@app.get("/api/auth/me")
def auth_me(current_user: dict = Depends(get_current_user)):
    """Returns currently authenticated user profile."""
    return {"user": current_user}

@app.post("/api/auth/change-password")
def auth_change_password(payload: ChangePasswordRequest, current_user: dict = Depends(get_current_user)):
    """Allows any logged-in user to change their own password."""
    user = db.get_user_by_id(current_user["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")

    if not verify_password(payload.old_password, user["password_hash"], user["salt"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")

    new_hash, new_salt = hash_password(payload.new_password)
    db.update_user_password(user["id"], new_hash, new_salt)
    return {"success": True, "message": "Password changed successfully."}

# ================= Admin User Management Endpoints =================

@app.get("/api/admin/users", response_model=List[UserResponse])
def admin_list_users(admin: dict = Depends(require_admin)):
    """Lists all registered users in the system (Admin only)."""
    users = db.list_users()
    return [
        UserResponse(
            id=u["id"],
            username=u["username"],
            display_name=u["display_name"],
            role=u["role"],
            is_active=u["is_active"],
            created_at=str(u["created_at"]),
            updated_at=str(u["updated_at"])
        )
        for u in users
    ]

@app.post("/api/admin/users", response_model=UserResponse)
def admin_create_user(payload: UserCreate, admin: dict = Depends(require_admin)):
    """Creates a new user account (Admin only)."""
    clean_username = payload.username.strip()
    if not clean_username:
        raise HTTPException(status_code=400, detail="Username cannot be empty.")
    existing = db.get_user_by_username(clean_username, case_sensitive=False)
    if existing:
        raise HTTPException(status_code=400, detail=f"Username '{clean_username}' already exists.")

    pwd_hash, salt = hash_password(payload.password)
    user_id = db.create_user(
        username=clean_username,
        display_name=payload.display_name.strip() or clean_username,
        password_hash=pwd_hash,
        salt=salt,
        role=payload.role or "teacher"
    )
    user = db.get_user_by_id(user_id)
    return UserResponse(
        id=user["id"],
        username=user["username"],
        display_name=user["display_name"],
        role=user["role"],
        is_active=user["is_active"],
        created_at=str(user["created_at"]),
        updated_at=str(user["updated_at"])
    )

@app.post("/api/admin/users/{user_id}/reset-password")
def admin_reset_user_password(user_id: int, payload: ResetPasswordRequest, admin: dict = Depends(require_admin)):
    """Resets a user's password (Admin only)."""
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    pwd_hash, salt = hash_password(payload.new_password)
    db.update_user_password(user_id, pwd_hash, salt)
    return {"success": True, "message": f"Password reset successfully for user '{user['username']}'."}

@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: int, admin: dict = Depends(require_admin)):
    """Deletes a user account (Admin only; cannot delete own account)."""
    if user_id == admin["user_id"]:
        raise HTTPException(status_code=400, detail="Cannot delete your own active administrator account.")

    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    db.delete_user(user_id)
    return {"success": True, "message": f"User '{user['username']}' deleted successfully."}

@app.post("/api/auth/verify")
def auth_verify(request: Request, payload: AuthVerifyRequest):
    """Legacy endpoint: verifies master passcode or admin password for backward compatibility."""
    client_ip = get_client_ip(request)
    remaining_lockout = auth_rate_limiter.check_rate_limit(client_ip)
    if remaining_lockout is not None:
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Please wait {remaining_lockout} seconds before trying again.",
            headers={"Retry-After": str(remaining_lockout)}
        )

    # Check APP_PASSWORD or admin user password
    is_valid = False
    if APP_PASSWORD:
        is_valid = secrets.compare_digest(payload.password.encode("utf-8"), APP_PASSWORD.encode("utf-8"))
    
    if not is_valid:
        admin_user = db.get_user_by_username("admin")
        if admin_user:
            is_valid = verify_password(payload.password, admin_user["password_hash"], admin_user["salt"])

    if is_valid:
        auth_rate_limiter.record_success(client_ip)
        return {"success": True, "message": "Authenticated successfully"}
    else:
        is_locked, lockout_secs = auth_rate_limiter.record_failure(client_ip)
        if is_locked:
            raise HTTPException(
                status_code=429,
                detail=f"Maximum failed attempts reached. Your IP is locked for {lockout_secs} seconds.",
                headers={"Retry-After": str(lockout_secs)}
            )
        raise HTTPException(status_code=401, detail="Incorrect passcode. Please try again.")

def _validate_upload_files_sync_headers(filename: str, content: bytes, total_batch_size: int) -> int:
    ext = filename.lower()
    if not (ext.endswith(".docx") or ext.endswith(".pdf")):
        raise HTTPException(status_code=400, detail=f"File '{filename}' is not a supported format (.docx or .pdf).")

    file_size = len(content)
    if file_size > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File '{filename}' exceeds maximum allowed size of 20 MB ({file_size / (1024*1024):.1f} MB)."
        )

    new_batch_size = total_batch_size + file_size
    if new_batch_size > MAX_BATCH_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Upload batch exceeds maximum allowed size of 50 MB ({new_batch_size / (1024*1024):.1f} MB)."
        )

    is_valid, err_msg = validate_file_magic_bytes(filename, content)
    if not is_valid:
        raise HTTPException(status_code=400, detail=err_msg)
    return new_batch_size


@app.post("/api/upload/preview", dependencies=[Depends(verify_auth)])
async def preview_upload_files(
    files: List[UploadFile] = File(...),
    subject: str = Form(""),
    topic: str = Form(""),
    class_level: str = Form("")
):
    """
    Parses uploaded .docx/.pdf files using the Smart Sanitizer (extracting Lesson/Section context,
    dropping dividers/footers/OR, normalizing quotes & OCR spaces) and returns a preview payload
    showing duplicates vs new questions before saving.
    """
    total_batch_size = 0
    validated_files = []

    for file in files:
        filename = file.filename or "unknown_file"
        content = await file.read()
        total_batch_size = _validate_upload_files_sync_headers(filename, content, total_batch_size)
        validated_files.append((filename, content))

    preview_items = []
    total_dropped = 0
    temp_counter = 1

    for filename, content in validated_files:
        try:
            structured_items, dropped_cnt = extract_structured_questions_from_file(
                filename,
                content,
                default_subject=subject.strip(),
                default_topic=topic.strip(),
                default_class=class_level.strip(),
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed parsing file '{filename}': {str(e)}")

        total_dropped += dropped_cnt
        for it in structured_items:
            preview_items.append({
                "temp_id": temp_counter,
                "source_filename": filename,
                "include": True,
                **it,
            })
            temp_counter += 1

    norms = [it["normalized_text"] for it in preview_items if it.get("normalized_text")]
    existing_map = db.find_existing_normalized_map(norms)

    # Also detect duplicates across multiple uploaded files in the same preview batch
    seen_in_batch = set()
    new_count = 0
    dup_count = 0
    review_count = 0

    for it in preview_items:
        nt = it.get("normalized_text", "")
        existing = existing_map.get(nt)
        if existing:
            it["is_duplicate"] = True
            it["existing_id"] = existing["id"]
            it["existing_frequency"] = existing["frequency"]
            dup_count += 1
        elif nt in seen_in_batch:
            it["is_duplicate"] = True
            it["existing_id"] = None
            it["existing_frequency"] = 1
            dup_count += 1
        else:
            it["is_duplicate"] = False
            it["existing_id"] = None
            it["existing_frequency"] = 0
            new_count += 1
        if nt:
            seen_in_batch.add(nt)
        if it.get("needs_review"):
            review_count += 1

    return {
        "total_files": len(files),
        "total_extracted": len(preview_items),
        "new_count": new_count,
        "duplicate_count": dup_count,
        "needs_review_count": review_count,
        "dropped_dividers_count": total_dropped,
        "items": preview_items,
    }


@app.post("/api/upload/confirm", response_model=UploadStatsResponse, dependencies=[Depends(verify_auth)])
def confirm_upload_import(payload: ConfirmImportRequest):
    """
    Saves teacher-reviewed items from the Pre-Import Preview modal into the Question Library.
    """
    file_stats = {}
    total_extracted = 0
    total_new = 0
    total_merged = 0

    for item in payload.items:
        if not item.include:
            continue
        clean_text = clean_question_text(item.question_text)
        if not clean_text:
            continue
        norm_text = normalize_question_text(clean_text)
        if not norm_text:
            continue

        src = (item.source_filename or "Uploaded File").strip()
        if src not in file_stats:
            file_stats[src] = {"extracted": 0, "new_added": 0, "duplicates_merged": 0}
        file_stats[src]["extracted"] += 1
        total_extracted += 1

        qid, is_merged = db.upsert_question(
            question_text=clean_text,
            normalized_text=norm_text,
            subject=(item.subject or "").strip(),
            topic=(item.topic or "").strip(),
            source_filename=src,
            class_level=(item.class_level or "").strip(),
            question_type=(item.question_type or "").strip(),
            difficulty=(item.difficulty or "").strip(),
            default_marks=item.default_marks,
            needs_review=bool(item.needs_review),
            review_reason=(item.review_reason or "").strip(),
        )
        if is_merged:
            file_stats[src]["duplicates_merged"] += 1
            total_merged += 1
        else:
            file_stats[src]["new_added"] += 1
            total_new += 1

    file_summaries = [
        UploadSummary(
            filename=fname,
            extracted=st["extracted"],
            new_added=st["new_added"],
            duplicates_merged=st["duplicates_merged"],
        )
        for fname, st in file_stats.items()
    ]

    return UploadStatsResponse(
        total_files=len(file_summaries),
        total_extracted=total_extracted,
        total_new=total_new,
        total_merged=total_merged,
        file_summaries=file_summaries,
    )


@app.post("/api/upload", response_model=UploadStatsResponse, dependencies=[Depends(verify_auth)])
async def upload_files(
    files: List[UploadFile] = File(...),
    subject: str = Form(""),
    topic: str = Form(""),
    class_level: str = Form("")
):
    """
    Upload one or more .docx or .pdf files directly.
    Enforces 20MB per-file and 50MB batch caps, validates magic-byte headers,
    applies smart sanitization + context inference, and performs deduplication.
    """
    total_batch_size = 0
    validated_files = []

    for file in files:
        filename = file.filename or "unknown_file"
        content = await file.read()
        total_batch_size = _validate_upload_files_sync_headers(filename, content, total_batch_size)
        validated_files.append((filename, content))

    total_extracted = 0
    total_new = 0
    total_merged = 0
    file_summaries: List[UploadSummary] = []

    for filename, content in validated_files:
        try:
            structured_items, _ = extract_structured_questions_from_file(
                filename,
                content,
                default_subject=subject.strip(),
                default_topic=topic.strip(),
                default_class=class_level.strip(),
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed parsing file '{filename}': {str(e)}")

        file_extracted = len(structured_items)
        file_new = 0
        file_merged = 0

        for it in structured_items:
            clean_text = it.get("question_text") or ""
            norm_text = it.get("normalized_text") or normalize_question_text(clean_text)
            if not clean_text or not norm_text:
                continue

            qid, is_merged = db.upsert_question(
                question_text=clean_text,
                normalized_text=norm_text,
                subject=it.get("subject", subject.strip()),
                topic=it.get("topic", topic.strip()),
                source_filename=filename,
                class_level=it.get("class_level", class_level.strip()),
                question_type=it.get("question_type", ""),
                difficulty=it.get("difficulty", ""),
                default_marks=it.get("default_marks"),
                needs_review=bool(it.get("needs_review", False)),
                review_reason=it.get("review_reason", ""),
            )

            if is_merged:
                file_merged += 1
            else:
                file_new += 1

        total_extracted += file_extracted
        total_new += file_new
        total_merged += file_merged

        file_summaries.append(UploadSummary(
            filename=filename,
            extracted=file_extracted,
            new_added=file_new,
            duplicates_merged=file_merged
        ))

    return UploadStatsResponse(
        total_files=len(files),
        total_extracted=total_extracted,
        total_new=total_new,
        total_merged=total_merged,
        file_summaries=file_summaries
    )


@app.get("/api/questions")
def get_questions(
    search: Optional[str] = Query(None),
    subject: Optional[str] = Query(None),
    topic: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    class_level: Optional[str] = Query(None),
    question_type: Optional[str] = Query(None),
    difficulty: Optional[str] = Query(None),
    needs_review: Optional[bool] = Query(None),
    sort_by: str = Query("recent"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200)
):
    """Returns paginated questions with rich search, filtering, and sorting."""
    return db.get_questions(
        search=search,
        subject=subject,
        topic=topic,
        source=source,
        class_level=class_level,
        question_type=question_type,
        difficulty=difficulty,
        needs_review=needs_review,
        sort_by=sort_by,
        page=page,
        limit=limit
    )


@app.post("/api/questions", dependencies=[Depends(verify_auth)])
def create_manual_question(payload: QuestionCreate):
    """
    Manually add a single question directly without uploading a file.
    Applies exact-match deduplication and frequency tracking.
    """
    clean_text = clean_question_text(payload.question_text)
    if not clean_text:
        raise HTTPException(status_code=400, detail="Question text cannot be empty.")

    norm_text = normalize_question_text(clean_text)
    source_name = payload.source.strip() if payload.source and payload.source.strip() else "Manual Entry"

    # Lightly infer missing type/difficulty/marks while respecting explicit inputs
    inferred = infer_question_metadata(
        cleaned_text=clean_text,
        sources=[source_name],
        existing_subject=payload.subject.strip() if payload.subject else "",
        existing_topic=payload.topic.strip() if payload.topic else "",
        existing_class=payload.class_level.strip() if payload.class_level else "",
        explicit_marks=payload.default_marks,
    )

    qid, is_merged = db.upsert_question(
        question_text=clean_text,
        normalized_text=norm_text,
        subject=(payload.subject.strip() if payload.subject else "") or inferred["subject"],
        topic=(payload.topic.strip() if payload.topic else "") or inferred["topic"],
        source_filename=source_name,
        class_level=(payload.class_level.strip() if payload.class_level else "") or inferred["class_level"],
        question_type=(payload.question_type.strip() if payload.question_type else "") or inferred["question_type"],
        difficulty=(payload.difficulty.strip() if payload.difficulty else "") or inferred["difficulty"],
        default_marks=payload.default_marks if payload.default_marks is not None else inferred["default_marks"],
        needs_review=bool(payload.needs_review) if payload.needs_review is not None else False,
        review_reason=(payload.review_reason or "").strip(),
    )

    return {
        "id": qid,
        "is_merged": is_merged,
        "message": "Duplicate detected: Merged into existing question and increased frequency counter." if is_merged else "Question added to library successfully."
    }


@app.get("/api/questions/duplicates", dependencies=[Depends(verify_auth)])
def find_duplicate_questions(
    threshold: float = Query(0.80, ge=0.5, le=1.0),
    limit_groups: int = Query(40, ge=1, le=100)
):
    """Finds potential near-duplicate question groups for teacher review & merging."""
    groups = db.find_potential_duplicates(threshold=threshold, limit_groups=limit_groups)
    return {
        "total_groups": len(groups),
        "groups": groups,
    }


@app.post("/api/questions/bulk-update", dependencies=[Depends(verify_auth)])
def bulk_update_questions(payload: BulkUpdateQuestionsRequest):
    """Bulk updates structured tags/marks/review status for selected questions (Teacher & Admin)."""
    count = db.bulk_update_questions(
        question_ids=payload.question_ids,
        subject=payload.subject.strip() if payload.subject is not None else None,
        topic=payload.topic.strip() if payload.topic is not None else None,
        class_level=payload.class_level.strip() if payload.class_level is not None else None,
        question_type=payload.question_type.strip() if payload.question_type is not None else None,
        difficulty=payload.difficulty.strip() if payload.difficulty is not None else None,
        default_marks=payload.default_marks,
        needs_review=payload.needs_review,
        review_reason=payload.review_reason,
    )
    return {
        "message": f"Updated {count} question(s) successfully.",
        "updated_count": count,
    }


@app.post("/api/questions/merge", dependencies=[Depends(verify_auth)])
def merge_duplicate_questions(payload: MergeQuestionsRequest):
    """Merges selected duplicate questions into target_id, preserving combined frequency & sources (Teacher & Admin)."""
    cleaned_merged = None
    norm_merged = None
    if payload.merged_text is not None and payload.merged_text.strip():
        cleaned_merged = clean_question_text(payload.merged_text)
        norm_merged = normalize_question_text(cleaned_merged)
        if not cleaned_merged or not norm_merged:
            raise HTTPException(status_code=400, detail="Merged question text cannot be empty.")

    try:
        merged = db.merge_questions(
            target_id=payload.target_id,
            source_ids=payload.source_ids,
            merged_text=cleaned_merged,
            merged_normalized_text=norm_merged,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not merged:
        raise HTTPException(status_code=404, detail="Target question not found.")

    return {
        "message": f"Merged {len(payload.source_ids)} duplicate(s) into question #{payload.target_id}.",
        "question": merged,
    }


@app.post("/api/questions/auto-pick", dependencies=[Depends(verify_auth)])
def auto_pick_paper_questions(payload: AutoPickRequest):
    """1-Click Auto-Pick Paper Builder endpoint (Teacher & Admin)."""
    result = db.auto_pick_questions(
        class_level=payload.class_level,
        subject=payload.subject,
        topics=payload.topics,
        question_type=payload.question_type,
        difficulty=payload.difficulty,
        count=payload.count,
        target_marks=payload.target_marks,
        prefer_most_repeated=payload.prefer_most_repeated,
        spread_topics=payload.spread_topics,
        exclude_needs_review=payload.exclude_needs_review,
        exclude_ids=payload.exclude_ids,
    )
    return result


@app.post("/api/questions/by-ids")
def get_questions_by_ids(req: ExportRequest):
    """Returns full question details for a list of IDs in the exact requested order."""
    return db.get_questions_by_ids(req.question_ids)


@app.post("/api/questions/bulk-delete", dependencies=[Depends(require_admin)])
def bulk_delete_questions(payload: BulkDeleteRequest):
    """Deletes multiple questions by their IDs in a single batch (Admin only)."""
    count = db.delete_questions(payload.question_ids)
    return {
        "message": f"Successfully deleted {count} questions.",
        "deleted_count": count
    }


@app.put("/api/questions/{question_id}", dependencies=[Depends(verify_auth)])
def update_question(question_id: int, payload: QuestionUpdate):
    """Updates question text and structured metadata (Teacher & Admin)."""
    norm_text = None
    cleaned_text = None
    if payload.question_text is not None:
        cleaned_text = clean_question_text(payload.question_text)
        if not cleaned_text:
            raise HTTPException(status_code=400, detail="Question text cannot be empty.")
        norm_text = normalize_question_text(cleaned_text)

    try:
        success = db.update_question(
            question_id=question_id,
            question_text=cleaned_text,
            normalized_text=norm_text,
            subject=payload.subject.strip() if payload.subject is not None else None,
            topic=payload.topic.strip() if payload.topic is not None else None,
            class_level=payload.class_level.strip() if payload.class_level is not None else None,
            question_type=payload.question_type.strip() if payload.question_type is not None else None,
            difficulty=payload.difficulty.strip() if payload.difficulty is not None else None,
            default_marks=payload.default_marks,
            clear_default_marks=bool(payload.clear_default_marks),
            needs_review=payload.needs_review,
            review_reason=payload.review_reason.strip() if payload.review_reason is not None else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not success:
        raise HTTPException(status_code=404, detail="Question not found")
    return {"message": "Question updated successfully"}


@app.delete("/api/questions/{question_id}", dependencies=[Depends(require_admin)])
def delete_question(question_id: int):
    """Deletes a question from the library (Admin only)."""
    success = db.delete_question(question_id)
    if not success:
        raise HTTPException(status_code=404, detail="Question not found")
    return {"message": "Question deleted successfully"}


@app.post("/api/admin/curate/preview", dependencies=[Depends(require_admin)])
def preview_smart_curation():
    """Dry-run preview of Automated Smart Curation (Admin only)."""
    return curate_question_library(db, dry_run=True, create_backup=False)


@app.post("/api/admin/curate/run", dependencies=[Depends(require_admin)])
def run_smart_curation():
    """Creates backup and runs Automated Smart Curation across the active database (Admin only)."""
    return curate_question_library(db, dry_run=False, create_backup=True)


@app.get("/api/metadata")
def get_metadata():
    """Returns metadata (classes, subjects, topics, types, difficulties, sources, and duplicate statistics)."""
    return db.get_metadata()


@app.post("/api/export")
def export_questions(payload: ExportRequest):
    """
    Generates and downloads a clean Word document (.docx) or PDF (.pdf)
    containing the requested questions (with optional paper header, section dividers, and per-question marks).
    """
    export_rows = []

    if payload.items:
        id_list = [it.question_id for it in payload.items if it.item_type != "section" and it.question_id]
        db_map = {q["id"]: q for q in db.get_questions_by_ids(id_list)} if id_list else {}

        for it in payload.items:
            if it.item_type == "section":
                sec_title = (it.section_title or it.question_text or "").strip()
                if sec_title:
                    export_rows.append({"item_type": "section", "section_title": sec_title})
            else:
                q_obj = db_map.get(it.question_id) if it.question_id else None
                q_text = (it.question_text or "").strip() or (q_obj["question_text"] if q_obj else "")
                if not q_text:
                    continue
                marks = it.marks if it.marks is not None else (q_obj.get("default_marks") if q_obj else None)
                export_rows.append({
                    "item_type": "question",
                    "question_text": q_text,
                    "marks": marks,
                })
    else:
        questions = db.get_questions_by_ids(payload.question_ids)
        for q in questions:
            export_rows.append({
                "item_type": "question",
                "question_text": q["question_text"],
                "marks": q.get("default_marks"),
            })

    has_question = any(r.get("item_type") != "section" for r in export_rows)
    if not has_question:
        raise HTTPException(status_code=400, detail="No valid questions found for export.")

    fmt = (payload.format or "docx").lower().strip()
    hdr_dict = payload.paper_header.model_dump() if payload.paper_header else None
    title = ((hdr_dict or {}).get("exam_title") or payload.title or "").strip()
    base_name = re.sub(r'[^a-zA-Z0-9_-]', '_', title) if title else "Question_Paper"

    use_tmpl = bool(payload.use_template)

    if fmt == "pdf":
        stream = generate_pdf_document(
            export_rows,
            title=title,
            use_template=use_tmpl,
            paper_header=hdr_dict,
            show_marks=bool(payload.show_marks),
        )
        filename = f"{base_name}.pdf"
        media_type = "application/pdf"
    else:
        stream = generate_word_document(
            export_rows,
            title=title,
            use_template=use_tmpl,
            paper_header=hdr_dict,
            show_marks=bool(payload.show_marks),
        )
        filename = f"{base_name}.docx"
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    return StreamingResponse(
        stream,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@app.get("/api/backup", dependencies=[Depends(require_admin)])
def export_backup(request: Request):
    """Exports entire questions database as a structured JSON file (Admin only)."""
    questions = db.get_all_questions_for_backup()
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_doc = {
        "app": "QuestionBank Studio",
        "version": "1.0",
        "exported_at": datetime.now().isoformat(),
        "total_questions": len(questions),
        "questions": questions
    }
    content = json.dumps(backup_doc, indent=2, ensure_ascii=False)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="questionbank_backup_{now_str}.json"'}
    )

@app.get("/api/admin/backup", dependencies=[Depends(require_admin)])
def export_full_system_backup():
    """Exports a complete disaster recovery backup (questions, exams, submissions, answers) as a JSON archive (Admin only)."""
    backup_data = db.export_full_backup()
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    content = json.dumps(backup_data, indent=2, ensure_ascii=False)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="squire_way_full_backup_{now_str}.json"'}
    )

@app.post("/api/restore", dependencies=[Depends(require_admin)])
async def import_backup(file: UploadFile = File(...)):
    """Restores/merges questions from an uploaded JSON backup file into the active database (Admin only)."""
    content = await file.read()
    if len(content) > MAX_BATCH_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Backup file exceeds maximum allowed size of 50 MB.")

    try:
        data = json.loads(content.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON file: {str(e)}")

    questions = data.get("questions") if isinstance(data, dict) else (data if isinstance(data, list) else None)
    if questions is None or not isinstance(questions, list):
        raise HTTPException(status_code=400, detail="Invalid backup format. Expected a 'questions' list.")

    stats = db.restore_questions_from_backup(questions)
    return {
        "message": f"Backup restored: {stats['restored']} new added, {stats['merged']} duplicates merged.",
        "stats": stats
    }

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
os.makedirs(TEMPLATE_DIR, exist_ok=True)
TEMPLATE_FILE = os.path.join(TEMPLATE_DIR, "default_template.docx")

@app.get("/api/template/info")
def get_template_info():
    """Returns status and information about the default printout template."""
    exists = os.path.exists(TEMPLATE_FILE)
    return {
        "exists": exists,
        "name": "Default_page.docx" if exists else None,
        "description": "A4 Size, 0.5-inch margins, double-line page border, Times New Roman" if exists else "None"
    }

@app.post("/api/template/upload", dependencies=[Depends(require_admin)])
async def upload_custom_template(file: UploadFile = File(...)):
    """Uploads or replaces the default printout page template (.docx) (Admin only)."""
    if not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Template file must be a .docx Word document.")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Template file exceeds maximum allowed size of 20 MB.")

    is_valid, err_msg = validate_file_magic_bytes(file.filename, content)
    if not is_valid:
        raise HTTPException(status_code=400, detail=err_msg)

    with open(TEMPLATE_FILE, "wb") as f:
        f.write(content)

    return {
        "message": "Default template updated successfully!",
        "filename": file.filename
    }

# ==========================================
# Digital Exams & Evaluation Studio Endpoints
# ==========================================

def generate_qr_svg(url: str, size: int = 200) -> str:
    """Generates pure vector SVG QR code using installed reportlab."""
    qr_widget = QrCodeWidget(url)
    bounds = qr_widget.getBounds()
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    drawing = Drawing(size, size, transform=[size / width, 0, 0, size / height, 0, 0])
    drawing.add(qr_widget)
    return renderSVG.drawToString(drawing)

def parse_iso_datetime(dt_str: str) -> datetime:
    """Parses ISO-like datetime string, handling trailing Z or missing tz."""
    clean_str = dt_str.strip()
    if clean_str.endswith("Z"):
        clean_str = clean_str[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(clean_str)
    except Exception:
        for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(clean_str, fmt)
                break
            except Exception:
                pass
        else:
            raise ValueError(f"Invalid datetime format: {dt_str}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@app.post("/api/exams")
def create_exam(
    payload: ExamCreateRequest,
    request: Request,
    current_user: dict = Depends(verify_auth)
):
    """Creates a new digital exam with snapshot questions."""
    try:
        parse_iso_datetime(payload.deadline)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid deadline format: {e}")

    questions_data = [
        {
            "question_id": q.question_id,
            "question_text": q.question_text,
            "marks": q.marks,
            "question_order": q.question_order or (idx + 1),
            "section_title": q.section_title or "",
        }
        for idx, q in enumerate(payload.questions)
    ]

    created_by_id = current_user.get("user_id") if isinstance(current_user, dict) else None
    exam = db.create_exam(
        title=payload.title,
        subject=payload.subject or "",
        duration_minutes=payload.duration_minutes,
        deadline=payload.deadline,
        instructions=payload.instructions or "",
        total_marks=payload.total_marks,
        questions=questions_data,
        created_by=created_by_id,
        class_level=payload.class_level or "",
        institute_name=payload.institute_name or "The Squire's Way",
    )

    base_url = str(request.base_url).rstrip('/')
    exam_url = f"{base_url}/exam/{exam['exam_code']}"
    qr_svg = generate_qr_svg(exam_url, size=200)

    exam["exam_url"] = exam_url
    exam["qr_svg"] = qr_svg
    return exam


@app.get("/api/exams")
def list_exams(
    status: Optional[str] = Query(None, description="Filter by status ('active' or 'closed')"),
    limit: int = Query(50, ge=1, le=100),
    page: int = Query(1, ge=1),
    current_user: dict = Depends(verify_auth)
):
    """Lists exams with questions count, submissions count, and pending grading count."""
    return db.get_exams(status=status, limit=limit, page=page)


@app.get("/api/exams/{id}/detail")
def get_exam_detail_for_clone(id: int, current_user: dict = Depends(verify_auth)):
    """Returns full exam details and ordered questions for cloning back into Paper Cart."""
    exam = db.get_exam_by_id(id, include_questions=True)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")
    return exam


@app.get("/api/exams/{code}")
def get_public_exam(code: str):
    """Public metadata endpoint for student exam room with server clock synchronization."""
    exam = db.get_exam_by_code(code, include_questions=True)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    return {
        "id": exam["id"],
        "exam_code": exam["exam_code"],
        "title": exam["title"],
        "subject": exam["subject"],
        "class_level": exam.get("class_level", ""),
        "institute_name": exam.get("institute_name", "The Squire's Way"),
        "duration_minutes": exam["duration_minutes"],
        "deadline": exam["deadline"],
        "total_marks": exam["total_marks"],
        "instructions": exam["instructions"],
        "status": exam["status"],
        "questions_count": exam["questions_count"],
        "server_now_utc": datetime.now(timezone.utc).isoformat(),
        "questions": [
            {
                "id": q["id"],
                "question_order": q["question_order"],
                "question_text": q["question_text"],
                "marks": q["marks"],
                "section_title": q.get("section_title", ""),
            }
            for q in exam["questions"]
        ]
    }


@app.post("/api/exams/{code}/submit")
async def submit_exam_answers(code: str, payload: StudentSubmissionRequest):
    """Public student submission endpoint with concurrency throttle, deadline and duplicate enforcement."""
    async with SUBMISSION_SEMAPHORE:
        exam = db.get_exam_by_code(code, include_questions=False)
        if not exam:
            raise HTTPException(status_code=404, detail="Exam not found.")

        if exam["status"] != "active":
            raise HTTPException(status_code=400, detail="Submission rejected: Exam is not currently active.")

        # Deadline validation with 5-minute grace window for clock skew & high network latency
        try:
            deadline_dt = parse_iso_datetime(exam["deadline"])
            now_utc = datetime.now(timezone.utc)
            grace_period = timedelta(seconds=300)
            if now_utc > (deadline_dt + grace_period):
                raise HTTPException(status_code=400, detail="Submission rejected: Exam deadline has passed.")
        except HTTPException:
            raise
        except Exception:
            pass

        try:
            student_name = payload.get_student_name()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        answers_data = [
            {
                "question_id": a.question_id,
                "typed_answer": a.typed_answer or "",
                "image_data": a.image_data or ""
            }
            for a in payload.answers
        ]

        try:
            sub = db.create_submission(
                exam_id=exam["id"],
                student_name=student_name,
                roll_number=payload.roll_number,
                section=payload.section or "",
                time_taken_seconds=payload.time_taken_seconds,
                answers=answers_data
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {
            "submission_id": sub["submission_id"],
            "exam_code": code,
            "student_name": student_name,
            "roll_number": sub["roll_number"],
            "submitted_at": sub["submitted_at"],
            "time_taken_seconds": sub["time_taken_seconds"],
            "status": "submitted",
            "message": "Submission recorded successfully."
        }


@app.post("/api/exams/{code}/import-emergency")
async def import_emergency_submission(
    code: str,
    payload: EmergencySubmissionPayload,
    current_user: dict = Depends(verify_auth)
):
    """
    Teacher/Admin imports an emergency offline submission package (.squire)
    created when a student's network failed completely.
    Validates integrity signature and records submission with audit trail.
    """
    async with SUBMISSION_SEMAPHORE:
        exam = db.get_exam_by_code(code, include_questions=False)
        if not exam:
            raise HTTPException(status_code=404, detail="Exam not found.")

        # Validate that payload exam code matches
        if payload.exam_code.strip().upper() != code.strip().upper():
            raise HTTPException(status_code=400, detail="Exam code mismatch in emergency package.")

        # Validate integrity hash: sha256(exam_code:roll_number:client_timestamp:num_answers)
        clean_roll = payload.roll_number.strip().upper()
        clean_name = payload.student_name.strip()
        expected_raw = f"{payload.exam_code.strip().upper()}:{clean_roll}:{payload.client_timestamp}:{len(payload.answers)}"
        computed_hash = hashlib.sha256(expected_raw.encode("utf-8")).hexdigest()

        # Validate integrity signature
        valid_hash = False
        if secrets.compare_digest(payload.integrity_hash.lower(), computed_hash.lower()):
            valid_hash = True
        else:
            # Check alternative JSON hash for flexibility
            answers_json = json.dumps([{"q": a.question_id, "t": a.typed_answer or "", "i": bool(a.image_data)} for a in payload.answers], sort_keys=True)
            alt_raw = f"{expected_raw}:{answers_json}"
            alt_hash = hashlib.sha256(alt_raw.encode("utf-8")).hexdigest()
            if secrets.compare_digest(payload.integrity_hash.lower(), alt_hash.lower()):
                valid_hash = True
            elif payload.integrity_hash.lower().startswith("sha256fallback_"):
                # Handle fallback hash when student device lacks window.crypto.subtle
                poly_hash = 0
                for char in expected_raw:
                    poly_hash = (((poly_hash << 5) - poly_hash) + ord(char)) & 0xFFFFFFFF
                    if poly_hash >= 0x80000000:
                        poly_hash -= 0x100000000
                expected_fallback = f"sha256fallback_{hex(abs(poly_hash))[2:]}"
                if secrets.compare_digest(payload.integrity_hash.lower(), expected_fallback.lower()):
                    valid_hash = True

        if not valid_hash:
            raise HTTPException(
                status_code=400,
                detail="Integrity check failed: Emergency file checksum mismatch. This package may have been modified or corrupted."
            )

        answers_data = [
            {
                "question_id": a.question_id,
                "typed_answer": a.typed_answer or "",
                "image_data": a.image_data or ""
            }
            for a in payload.answers
        ]

        try:
            sub = db.create_submission(
                exam_id=exam["id"],
                student_name=clean_name,
                roll_number=clean_roll,
                section=payload.section or "",
                time_taken_seconds=payload.time_taken_seconds,
                answers=answers_data,
                is_emergency=True,
                emergency_hash=payload.integrity_hash
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {
            "submission_id": sub["submission_id"],
            "exam_code": code,
            "student_name": clean_name,
            "roll_number": sub["roll_number"],
            "submitted_at": sub["submitted_at"],
            "time_taken_seconds": sub["time_taken_seconds"],
            "status": "submitted",
            "is_emergency": True,
            "message": "Emergency offline submission successfully verified and imported into grading studio."
        }


@app.get("/api/exams/{code}/result")
def get_student_result(code: str, roll_number: str = Query(..., description="Student roll number or ID")):
    """Public student result lookup by roll number."""
    exam = db.get_exam_by_code(code, include_questions=False)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    sub = db.get_submission_by_exam_and_roll(exam["id"], roll_number)
    if not sub:
        raise HTTPException(status_code=404, detail=f"No submission found for roll number '{roll_number}' in this exam.")

    if sub.get("status") != "graded":
        return {
            "status": "pending_evaluation",
            "submission_id": sub["id"],
            "student_name": sub["student_name"],
            "roll_number": sub["roll_number"],
            "section": sub.get("section", ""),
            "submitted_at": sub["submitted_at"],
            "time_taken_seconds": sub.get("time_taken_seconds", 0),
            "message": "Your submission has been recorded and is currently awaiting instructor evaluation."
        }

    return {
        "status": "published",
        "submission_id": sub["id"],
        "student_name": sub["student_name"],
        "roll_number": sub["roll_number"],
        "section": sub.get("section", ""),
        "submitted_at": sub["submitted_at"],
        "time_taken_seconds": sub.get("time_taken_seconds", 0),
        "total_score": sub["total_score"],
        "total_marks": sub["total_marks"],
        "percentage": sub["percentage"],
        "feedback": sub.get("feedback", ""),
        "graded_at": sub.get("graded_at"),
        "questions": sub.get("questions", [])
    }


@app.get("/api/exams/{id}/submissions")
def list_exam_submissions(id: int, current_user: dict = Depends(verify_auth)):
    """Teacher lists all student submissions for an exam along with class summary stats."""
    exam = db.get_exam_by_id(id, include_questions=False)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    submissions = db.get_submissions_for_exam(id)
    stats = db.get_exam_stats(exam, submissions)
    return {
        "exam": exam,
        "submissions": submissions,
        "stats": stats,
        "total": len(submissions)
    }


def _csv_safe_cell(val) -> str:
    s = "" if val is None else str(val)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


@app.get("/api/exams/{id}/marksheet.csv")
def export_exam_marksheet_csv(id: int, current_user: dict = Depends(verify_auth)):
    """Exports exam submissions & graded marks as a downloadable CSV Marksheet (Teacher & Admin)."""
    exam = db.get_exam_by_id(id, include_questions=False)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    submissions = db.get_submissions_for_exam(id)
    # Sort by roll_number ascending for clean school register order
    submissions_sorted = sorted(submissions, key=lambda s: (s.get("section") or "", s.get("roll_number") or ""))
    exam_qs, score_map = db.get_exam_marksheet_scores(id)

    output = io.StringIO()
    writer = csv.writer(output)
    q_headers = [
        f"Q{q.get('question_order') or (i + 1)} (/{q['marks']:g})"
        for i, q in enumerate(exam_qs)
    ]
    writer.writerow([
        "Exam Code",
        "Exam Title",
        "Roll Number",
        "Student Name",
        "Section",
        "Status",
        "Score Awarded",
        "Max Marks",
        "Percentage (%)",
        "Time Taken (min)",
        "Submitted At",
        "Graded At",
        "Emergency Import",
        *q_headers,
        "Overall Feedback",
    ])

    total_marks = float(exam.get("total_marks") or 0.0)
    for sub in submissions_sorted:
        score = sub.get("total_score")
        pct = round((float(score) / total_marks) * 100, 1) if (score is not None and total_marks > 0) else ""
        mins = round(int(sub.get("time_taken_seconds") or 0) / 60.0, 1)
        q_scores = [
            (score_map[(sub["id"], q["id"])] if score_map.get((sub["id"], q["id"])) is not None else "")
            for q in exam_qs
        ]
        writer.writerow([
            _csv_safe_cell(exam["exam_code"]),
            _csv_safe_cell(exam["title"]),
            _csv_safe_cell(sub.get("roll_number", "")),
            _csv_safe_cell(sub.get("student_name", "")),
            _csv_safe_cell(sub.get("section", "")),
            _csv_safe_cell(sub.get("status", "")),
            score if score is not None else "",
            total_marks,
            pct,
            mins,
            _csv_safe_cell(sub.get("submitted_at", "")),
            _csv_safe_cell(sub.get("graded_at") or ""),
            "Yes" if sub.get("is_emergency") else "No",
            *q_scores,
            _csv_safe_cell(sub.get("feedback", "")),
        ])

    csv_bytes = output.getvalue().encode("utf-8-sig")
    safe_code = re.sub(r"[^a-zA-Z0-9_-]", "_", exam["exam_code"])
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_code}_marksheet.csv"'},
    )


@app.get("/api/submissions/{sub_id}")
def get_submission_detail(sub_id: int, current_user: dict = Depends(verify_auth)):
    """Teacher views detailed submission answer sheets for grading."""
    sub = db.get_submission_detail(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found.")
    return sub


@app.post("/api/submissions/{sub_id}/grade")
def grade_submission(
    sub_id: int,
    payload: GradeSubmissionRequest,
    current_user: dict = Depends(verify_auth)
):
    """Teacher publishes grades, question feedback, and overall evaluation."""
    sub = db.get_submission_detail(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found.")

    grades_data = [
        {
            "question_id": g.get_question_id(),
            "marks_awarded": g.get_marks(),
            "feedback": g.get_feedback()
        }
        for g in payload.get_grades_list()
    ]

    graded_by_id = current_user.get("user_id") if isinstance(current_user, dict) else None
    updated = db.grade_submission(
        submission_id=sub_id,
        grades=grades_data,
        overall_feedback=payload.overall_feedback or "",
        graded_by=graded_by_id
    )

    return {
        "message": "Grade and evaluation published successfully.",
        "submission": updated
    }


@app.patch("/api/exams/{id}/deadline")
def extend_exam_deadline(
    id: int,
    payload: ExamDeadlineUpdateRequest,
    current_user: dict = Depends(verify_auth)
):
    """Extends/updates an existing exam's deadline and optionally re-opens it (Teacher & Admin)."""
    try:
        parse_iso_datetime(payload.deadline)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid deadline format: {e}")

    updated = db.extend_exam_deadline(
        exam_id=id,
        new_deadline=payload.deadline,
        reopen_if_closed=payload.reopen_if_closed,
        duration_minutes=payload.duration_minutes,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Exam not found.")

    return {
        "message": "Exam deadline updated successfully.",
        "exam": updated,
    }


@app.patch("/api/exams/{id}/toggle")
def toggle_exam_status(id: int, current_user: dict = Depends(verify_auth)):
    """Toggles exam status between active and closed."""
    new_status = db.toggle_exam_status(id)
    if not new_status:
        raise HTTPException(status_code=404, detail="Exam not found.")
    return {
        "id": id,
        "status": new_status,
        "message": f"Exam status updated to {new_status}."
    }


@app.patch("/api/exams/{id}/status")
def update_exam_status(id: int, payload: dict, current_user: dict = Depends(verify_auth)):
    """Sets exam status explicitly to 'active' or 'closed'."""
    desired_status = (payload.get("status") or "").strip().lower()
    if desired_status not in ("active", "closed"):
        raise HTTPException(status_code=400, detail="Invalid status. Must be 'active' or 'closed'.")
    exam = db.get_exam_by_id(id, include_questions=False)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")
    if exam["status"] != desired_status:
        db.toggle_exam_status(id)
    return {
        "id": id,
        "status": desired_status,
        "message": f"Exam status updated to {desired_status}."
    }


@app.delete("/api/exams/{id}")
def delete_exam(id: int, current_user: dict = Depends(require_admin)):
    """Deletes an exam and cascades deletion to questions and submissions (Admin only)."""
    deleted = db.delete_exam(id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Exam not found.")
    return {
        "id": id,
        "message": "Exam deleted successfully."
    }


@app.get("/api/exams/{code}/qr")
def get_exam_qr_code(code: str, request: Request):
    """Generates and returns vector SVG QR code for an exam link."""
    exam = db.get_exam_by_code(code, include_questions=False)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    base_url = str(request.base_url).rstrip('/')
    exam_url = f"{base_url}/exam/{code}"
    svg_content = generate_qr_svg(exam_url, size=240)
    return Response(content=svg_content, media_type="image/svg+xml")


# Static files with performance caching headers
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")

class CachedStaticFiles(StaticFiles):
    """Serves static assets with aggressive 1-day caching headers for versioned resources."""
    def file_response(self, *args, **kwargs) -> Response:
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "public, max-age=86400, stale-while-revalidate=3600"
        return resp

if os.path.exists(STATIC_DIR):
    app.mount("/static", CachedStaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def serve_index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        response = FileResponse(index_path)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    return {"message": "Question Bank API is running. Static UI not found."}


@app.get("/exam/{exam_code}")
@app.get("/exam/{exam_code}/")
def serve_exam_room(exam_code: str):
    """Serves the distraction-free student exam room."""
    exam_html_path = os.path.join(STATIC_DIR, "exam.html")
    if os.path.exists(exam_html_path):
        response = FileResponse(exam_html_path)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    return JSONResponse(status_code=404, content={"detail": "Exam room UI not found."})
