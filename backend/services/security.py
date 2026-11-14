import time
import threading
from typing import Dict, List, Optional, Tuple

MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024       # 20 MB per file
MAX_BATCH_SIZE_BYTES = 50 * 1024 * 1024      # 50 MB total batch upload

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
