import os
import re
import json
import secrets
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Request, Depends, Header
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.database import Database
from backend.models import (
    QuestionResponse,
    QuestionCreate,
    QuestionUpdate,
    BulkDeleteRequest,
    ExportRequest,
    UploadSummary,
    UploadStatsResponse
)
from backend.services.parser import extract_questions_from_file
from backend.services.dedup import clean_question_text, normalize_question_text
from backend.services.exporter import generate_word_document, generate_pdf_document
from backend.services.security import (
    auth_rate_limiter,
    validate_file_magic_bytes,
    MAX_FILE_SIZE_BYTES,
    MAX_BATCH_SIZE_BYTES
)

# Initialize database
DB_PATH = os.environ.get("DATABASE_URL") or os.environ.get("QUESTION_BANK_DB", "questions.db")
db = Database(DB_PATH)

# Authentication settings
APP_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()

class AuthVerifyRequest(BaseModel):
    password: str

def get_client_ip(request: Request) -> str:
    """Extracts client IP, checking X-Forwarded-For if behind a reverse proxy (e.g. Render)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"

def verify_auth(request: Request):
    """Enforces master passcode protection if APP_PASSWORD is set."""
    if not APP_PASSWORD:
        return True
    
    header_pass = request.headers.get("x-app-password")
    if header_pass and secrets.compare_digest(header_pass.encode("utf-8"), APP_PASSWORD.encode("utf-8")):
        return True
        
    query_pass = request.query_params.get("auth_token")
    if query_pass and secrets.compare_digest(query_pass.encode("utf-8"), APP_PASSWORD.encode("utf-8")):
        return True
        
    raise HTTPException(status_code=401, detail="Authentication required. Please enter master passcode.")

app = FastAPI(
    title="Question Bank Manager",
    description="Smart Question Extraction, Deduplication & Word Paper Builder",
    version="1.0.0"
)

# OWASP Security Headers Middleware
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
        "connect-src 'self' https://questionbank-studio.onrender.com;"
    )
    return response

# Hardened CORS policy: Only allow own Render domain, custom domains, and local development
raw_allowed = os.environ.get("ALLOWED_ORIGINS", "")
allowed_origins = [
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

@app.get("/api/auth/status")
def auth_status(request: Request):
    """Returns whether the app has password protection enabled."""
    if not APP_PASSWORD:
        return {"protected": False, "authenticated": True}
    header_pass = request.headers.get("x-app-password")
    is_auth = bool(header_pass and secrets.compare_digest(header_pass.encode("utf-8"), APP_PASSWORD.encode("utf-8")))
    return {"protected": True, "authenticated": is_auth}

@app.post("/api/auth/verify")
def auth_verify(request: Request, payload: AuthVerifyRequest):
    """Verifies master passcode with brute-force rate limiting and timing-attack protection."""
    if not APP_PASSWORD:
        return {"success": True, "message": "No password protection enabled"}

    client_ip = get_client_ip(request)

    # Check if client IP is currently locked out
    remaining_lockout = auth_rate_limiter.check_rate_limit(client_ip)
    if remaining_lockout is not None:
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Please wait {remaining_lockout} seconds before trying again.",
            headers={"Retry-After": str(remaining_lockout)}
        )

    # Constant-time comparison to prevent timing attacks
    is_valid = secrets.compare_digest(payload.password.encode("utf-8"), APP_PASSWORD.encode("utf-8"))

    if is_valid:
        auth_rate_limiter.record_success(client_ip)
        response = JSONResponse({"success": True, "message": "Authenticated successfully"})
        response.delete_cookie(key="app_auth_token")
        return response
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

@app.delete("/api/questions/{question_id}", dependencies=[Depends(verify_auth)])
def delete_question(question_id: int):
    """Deletes a question from the library."""
    success = db.delete_question(question_id)
    if not success:
        raise HTTPException(status_code=404, detail="Question not found")
    return {"message": "Question deleted successfully"}

@app.post("/api/questions/bulk-delete", dependencies=[Depends(verify_auth)])
def bulk_delete_questions(payload: BulkDeleteRequest):
    """Deletes multiple questions by their IDs in a single batch."""
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

@app.get("/api/backup")
def export_backup(request: Request):
    """Exports entire questions database as a structured JSON file."""
    verify_auth(request)
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

@app.post("/api/restore", dependencies=[Depends(verify_auth)])
async def import_backup(file: UploadFile = File(...)):
    """Restores/merges questions from an uploaded JSON backup file into the active database."""
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

@app.post("/api/template/upload", dependencies=[Depends(verify_auth)])
async def upload_custom_template(file: UploadFile = File(...)):
    """Uploads or replaces the default printout page template (.docx)."""
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

# Static files and root route
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def serve_index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Question Bank API is running. Static UI not found."}
