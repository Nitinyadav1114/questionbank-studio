import time
import os
import hashlib
import secrets
import threading
from typing import Dict, List, Optional, Tuple, Any

MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024       # 20 MB per file
MAX_BATCH_SIZE_BYTES = 50 * 1024 * 1024      # 50 MB total batch upload
HASH_ITERATIONS = 260_000                    # NIST SP 800-132 recommendation for PBKDF2-HMAC-SHA256
SESSION_INACTIVITY_TIMEOUT = 24 * 60 * 60    # 24 hours rolling expiry in seconds


def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """
    Hashes a password using PBKDF2-HMAC-SHA256 with 260,000 iterations and a random salt.
    Returns: (hash_hex, salt_hex)
    """
    if not salt:
        salt = secrets.token_hex(16)
    
    salt_bytes = bytes.fromhex(salt)
    pwd_bytes = password.encode("utf-8")
    hash_bytes = hashlib.pbkdf2_hmac("sha256", pwd_bytes, salt_bytes, HASH_ITERATIONS)
    return hash_bytes.hex(), salt


def verify_password(password: str, stored_hash: str, stored_salt: str) -> bool:
    """
    Verifies a plain text password against stored PBKDF2 hash and salt using constant-time comparison.
    """
    try:
        salt_bytes = bytes.fromhex(stored_salt)
        pwd_bytes = password.encode("utf-8")
        computed = hashlib.pbkdf2_hmac("sha256", pwd_bytes, salt_bytes, HASH_ITERATIONS).hex()
        return secrets.compare_digest(computed, stored_hash)
    except Exception:
        return False


class SessionManager:
    """
    Thread-safe session token store backed by Database (`user_sessions`) when bound,
    with an in-memory fallback for standalone unit tests. Tokens are hashed (SHA-256) before persistence.
    """
    def __init__(self, timeout_seconds: int = SESSION_INACTIVITY_TIMEOUT):
        self.timeout_seconds = timeout_seconds
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._db_getter = None

    def bind_database(self, db_or_getter):
        """Binds a Database instance or callable returning the active Database."""
        self._db_getter = db_or_getter

    def _get_db(self):
        if callable(self._db_getter):
            return self._db_getter()
        return self._db_getter

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_session(
        self,
        user: Dict[str, Any],
        ip_address: str = "",
        user_agent: str = "",
    ) -> str:
        """Issues a cryptographically secure 256-bit session token and persists it if DB is bound."""
        token = secrets.token_urlsafe(32)
        now = time.time()
        session_data = {
            "user_id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "role": user["role"],
            "created_at": now,
            "last_active": now,
        }

        db = self._get_db()
        if db is not None and user.get("id"):
            try:
                db.create_session_record(
                    token_hash=self._hash_token(token),
                    user_id=int(user["id"]),
                    ttl_seconds=self.timeout_seconds,
                    ip_address=ip_address or "",
                    user_agent=user_agent or "",
                )
            except Exception as e:
                print(f"[Warning] Failed to persist session to DB, keeping memory fallback: {e}")

        with self._lock:
            self._cleanup_expired(now)
            self.sessions[token] = session_data
        return token

    def get_session(self, token: str) -> Optional[Dict[str, Any]]:
        """Retrieves and refreshes an active session from DB (or memory fallback) if valid and user active."""
        if not token:
            return None
        db = self._get_db()
        if db is not None:
            try:
                record = db.get_session_record(
                    token_hash=self._hash_token(token),
                    extend_seconds=self.timeout_seconds,
                )
                if record is not None:
                    return record
                # Also remove from memory cache if absent/expired/revoked in DB
                with self._lock:
                    self.sessions.pop(token, None)
                return None
            except Exception as e:
                print(f"[Warning] DB session lookup failed, falling back to memory: {e}")

        now = time.time()
        with self._lock:
            session = self.sessions.get(token)
            if not session:
                return None
            if now - session["last_active"] > self.timeout_seconds:
                del self.sessions[token]
                return None
            session["last_active"] = now
            return dict(session)

    def destroy_session(self, token: str) -> bool:
        """Invalidates a session token upon explicit logout."""
        if not token:
            return False
        removed_db = False
        db = self._get_db()
        if db is not None:
            try:
                removed_db = db.delete_session_by_hash(self._hash_token(token))
            except Exception as e:
                print(f"[Warning] DB session delete failed: {e}")
        with self._lock:
            removed_mem = self.sessions.pop(token, None) is not None
        return removed_db or removed_mem

    def revoke_user_sessions(self, user_id: int, exclude_token: Optional[str] = None) -> int:
        """Immediately terminates active sessions belonging to a user (optionally keeping exclude_token)."""
        exclude_hash = self._hash_token(exclude_token) if exclude_token else None
        removed_db = 0
        db = self._get_db()
        if db is not None:
            try:
                removed_db = db.delete_sessions_for_user(int(user_id), exclude_token_hash=exclude_hash)
            except Exception as e:
                print(f"[Warning] DB user session revocation failed: {e}")
        removed_mem = 0
        with self._lock:
            to_drop = [
                t for t, s in self.sessions.items()
                if s.get("user_id") == user_id and (not exclude_token or t != exclude_token)
            ]
            for t in to_drop:
                self.sessions.pop(t, None)
                removed_mem += 1
        return max(removed_db, removed_mem)

    def _cleanup_expired(self, current_time: float):
        """Removes expired in-memory sessions."""
        expired = [
            t for t, s in self.sessions.items()
            if current_time - s["last_active"] > self.timeout_seconds
        ]
        for t in expired:
            self.sessions.pop(t, None)

    def reset_all(self):
        """Testing utility: clears all sessions."""
        db = self._get_db()
        if db is not None:
            try:
                db.delete_all_sessions()
            except Exception:
                pass
        with self._lock:
            self.sessions.clear()


# Global Session Manager instance
session_manager = SessionManager(timeout_seconds=SESSION_INACTIVITY_TIMEOUT)


def ensure_admin_user(database):
    """
    Ensures that an initial admin account exists in the database.
    If no admin user exists, one is created from environment variables or defaults.
    """
    try:
        users = database.list_users()
        has_admin = any(u.get("role") == "admin" for u in users)
        if not has_admin:
            admin_user = os.environ.get("ADMIN_USERNAME", "admin").strip()
            admin_pass = os.environ.get("ADMIN_PASSWORD") or os.environ.get("APP_PASSWORD") or "squire2026"
            pwd_hash, salt = hash_password(admin_pass)
            database.create_user(
                username=admin_user,
                display_name="Administrator",
                password_hash=pwd_hash,
                salt=salt,
                role="admin"
            )
    except Exception as e:
        print(f"[Warning] Failed to ensure admin user: {e}")


class RateLimiter:
    """
    Thread-safe in-memory sliding window rate limiter for brute-force protection.
    Default policy: 5 failed attempts within 60 seconds triggers a 300-second (5 min) lockout.
    """
    def __init__(self, max_attempts: int = 5, window_seconds: int = 60, lockout_seconds: int = 300):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self.failed_attempts: Dict[str, List[float]] = {}
        self.lockouts: Dict[str, float] = {}
        self._lock = threading.Lock()

    def check_rate_limit(self, client_ip: str) -> Optional[int]:
        """
        Checks if the IP is currently locked out.
        Returns remaining lockout seconds if locked out, or None if allowed.
        """
        with self._lock:
            now = time.time()
            if client_ip in self.lockouts:
                expiry = self.lockouts[client_ip]
                if now < expiry:
                    return max(1, int(expiry - now))
                else:
                    del self.lockouts[client_ip]
            return None

    def record_failure(self, client_ip: str) -> Tuple[bool, int]:
        """
        Records a failed attempt for client_ip.
        Returns: (is_locked_out, remaining_lockout_seconds)
        """
        with self._lock:
            now = time.time()
            # Clean up expired lockout
            if client_ip in self.lockouts and now >= self.lockouts[client_ip]:
                del self.lockouts[client_ip]

            # Record and filter attempts within sliding window
            attempts = self.failed_attempts.get(client_ip, [])
            attempts = [t for t in attempts if now - t <= self.window_seconds]
            attempts.append(now)
            self.failed_attempts[client_ip] = attempts

            if len(attempts) >= self.max_attempts:
                self.lockouts[client_ip] = now + self.lockout_seconds
                self.failed_attempts.pop(client_ip, None)
                return True, self.lockout_seconds

            return False, 0

    def record_success(self, client_ip: str):
        """Clears failed attempts and lockouts upon successful authentication."""
        with self._lock:
            self.failed_attempts.pop(client_ip, None)
            self.lockouts.pop(client_ip, None)

    def reset_all(self):
        """Utility for testing: resets all state."""
        with self._lock:
            self.failed_attempts.clear()
            self.lockouts.clear()


# Global authentication rate limiter instance
auth_rate_limiter = RateLimiter(max_attempts=5, window_seconds=60, lockout_seconds=300)


def validate_file_magic_bytes(filename: str, content: bytes) -> Tuple[bool, str]:
    """
    Validates file headers (magic bytes) to ensure files match their claimed extension.
    - .docx: Must be a valid PKZip archive container (b'PK\x03\x04').
    - .pdf: Must start with PDF header (b'%PDF-').
    """
    if not content:
        return False, f"File '{filename}' is empty (0 bytes)."

    name_lower = filename.lower().strip()

    if name_lower.endswith(".docx"):
        # Word .docx is an OpenXML ZIP archive starting with PK\x03\x04
        if len(content) < 4 or not content.startswith(b"PK\x03\x04"):
            return False, f"File '{filename}' does not have a valid Word (.docx) file signature."

    elif name_lower.endswith(".pdf"):
        # PDF spec: %PDF- appears at the start of the file (within the first 1024 bytes)
        header_sample = content[:1024]
        if b"%PDF-" not in header_sample:
            return False, f"File '{filename}' does not have a valid PDF (.pdf) file signature."

    return True, ""
