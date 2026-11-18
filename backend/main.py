import os
import re
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
    StudentSubmissionRequest,
    StudentAnswerInput,
    QuestionGradeInput,
    GradeSubmissionRequest,
    EmergencySubmissionPayload
)
from backend.services.parser import extract_questions_from_file
from backend.services.dedup import clean_question_text, normalize_question_text
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
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
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

@app.post("/api/upload", response_model=UploadStatsResponse, dependencies=[Depends(verify_auth)])
async def upload_files(
    files: List[UploadFile] = File(...),
    subject: str = Form(""),
    topic: str = Form("")
):
    """
    Upload one or more .docx or .pdf files.
    Enforces 20MB per-file and 50MB batch caps, validates magic-byte headers,
    extracts questions, and performs exact-match deduplication.
    """
    total_batch_size = 0
    validated_files = []

    # First pass: Validate file extensions, sizes, and magic bytes before parsing
    for file in files:
        filename = file.filename or "unknown_file"
        ext = filename.lower()
        if not (ext.endswith(".docx") or ext.endswith(".pdf")):
            raise HTTPException(status_code=400, detail=f"File '{filename}' is not a supported format (.docx or .pdf).")

        content = await file.read()
        file_size = len(content)

        if file_size > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File '{filename}' exceeds maximum allowed size of 20 MB ({file_size / (1024*1024):.1f} MB)."
            )

        total_batch_size += file_size
        if total_batch_size > MAX_BATCH_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Upload batch exceeds maximum allowed size of 50 MB ({total_batch_size / (1024*1024):.1f} MB)."
            )

        is_valid, err_msg = validate_file_magic_bytes(filename, content)
        if not is_valid:
            raise HTTPException(status_code=400, detail=err_msg)

        validated_files.append((filename, content))

    total_extracted = 0
    total_new = 0
    total_merged = 0
    file_summaries: List[UploadSummary] = []

    for filename, content in validated_files:
        try:
            extracted_questions = extract_questions_from_file(filename, content)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed parsing file '{filename}': {str(e)}")

        file_extracted = len(extracted_questions)
        file_new = 0
        file_merged = 0

        for q_raw in extracted_questions:
            clean_text = clean_question_text(q_raw)
            if not clean_text:
                continue

            norm_text = normalize_question_text(clean_text)
            if not norm_text:
                continue

            qid, is_merged = db.upsert_question(
                question_text=clean_text,
                normalized_text=norm_text,
                subject=subject.strip(),
                topic=topic.strip(),
                source_filename=filename
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
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200)
):
    """Returns paginated questions with search and filtering."""
    return db.get_questions(
        search=search,
        subject=subject,
        topic=topic,
        source=source,
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

    qid, is_merged = db.upsert_question(
        question_text=clean_text,
        normalized_text=norm_text,
        subject=payload.subject.strip() if payload.subject else "",
        topic=payload.topic.strip() if payload.topic else "",
        source_filename=source_name
    )

    return {
        "id": qid,
        "is_merged": is_merged,
        "message": "Duplicate detected: Merged into existing question and increased frequency counter." if is_merged else "Question added to library successfully."
    }

@app.post("/api/questions/by-ids")
def get_questions_by_ids(req: ExportRequest):
    """Returns full question details for a list of IDs in the exact requested order."""
    return db.get_questions_by_ids(req.question_ids)

@app.put("/api/questions/{question_id}", dependencies=[Depends(verify_auth)])
def update_question(question_id: int, payload: QuestionUpdate):
    """Updates question text, subject, or topic."""
    norm_text = None
    cleaned_text = None
    if payload.question_text is not None:
        cleaned_text = clean_question_text(payload.question_text)
        norm_text = normalize_question_text(cleaned_text)

    success = db.update_question(
        question_id=question_id,
        question_text=cleaned_text,
        normalized_text=norm_text,
        subject=payload.subject,
        topic=payload.topic
    )
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

@app.post("/api/questions/bulk-delete", dependencies=[Depends(require_admin)])
def bulk_delete_questions(payload: BulkDeleteRequest):
    """Deletes multiple questions by their IDs in a single batch (Admin only)."""
    count = db.delete_questions(payload.question_ids)
    return {
        "message": f"Successfully deleted {count} questions.",
        "deleted_count": count
    }

@app.get("/api/metadata")
def get_metadata():
    """Returns metadata (subjects, topics, sources, and duplicate statistics)."""
    return db.get_metadata()

@app.post("/api/export")
def export_questions(payload: ExportRequest):
    """
    Generates and downloads a clean Word document (.docx) or PDF (.pdf)
    containing the requested questions formatted as a numbered list.
    """
    questions = db.get_questions_by_ids(payload.question_ids)
    if not questions:
        raise HTTPException(status_code=400, detail="No valid questions found for export.")

    fmt = (payload.format or "docx").lower().strip()
    title = payload.title.strip() if payload.title else ""
    base_name = re.sub(r'[^a-zA-Z0-9_-]', '_', title) if title else "Question_Paper"

    use_tmpl = bool(payload.use_template)

    if fmt == "pdf":
        stream = generate_pdf_document(questions, title=title, use_template=use_tmpl)
        filename = f"{base_name}.pdf"
        media_type = "application/pdf"
    else:
        stream = generate_word_document(questions, title=title, use_template=use_tmpl)
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
            "question_order": q.question_order or (idx + 1)
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
        created_by=created_by_id
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
                "marks": q["marks"]
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
    """Teacher lists all student submissions for an exam."""
    exam = db.get_exam_by_id(id, include_questions=False)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    submissions = db.get_submissions_for_exam(id)
    return {
        "exam": exam,
        "submissions": submissions,
        "total": len(submissions)
    }


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


@app.delete("/api/exams/{id}")
def delete_exam(id: int, current_user: dict = Depends(verify_auth)):
    """Deletes an exam and cascades deletion to questions and submissions."""
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
