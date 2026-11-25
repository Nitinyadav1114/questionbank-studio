import os
import re
import json
import time
import secrets
from datetime import datetime, timezone
import sqlite3
from typing import List, Dict, Any, Optional, Tuple
from contextlib import contextmanager

try:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False


def _iso_ts(val) -> str:
    """Formats naive DB timestamps/datetimes as explicit UTC ISO-8601 strings so JS Date() parses them consistently."""
    if val is None:
        return ""
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        return val.isoformat()
    s = str(val)
    if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?$", s):
        return s.replace(" ", "T") + "+00:00"
    return s


class Database:
    def __init__(self, db_url_or_path: Optional[str] = None):
        target = db_url_or_path or os.environ.get("DATABASE_URL") or os.environ.get("QUESTION_BANK_DB", "questions.db")
        
        self._metadata_cache: Optional[Dict[str, Any]] = None
        self._metadata_cache_time: float = 0.0
        self._metadata_ttl: float = 300.0  # 5 minutes in-memory cache
        self.pool = None

        if target.startswith("postgres://") or target.startswith("postgresql://"):
            if not PSYCOPG2_AVAILABLE:
                raise RuntimeError("psycopg2 is required for PostgreSQL connections. Run 'pip install psycopg2-binary'.")
            self.is_postgres = True
            # Cloud providers like Render sometimes provide postgres:// which psycopg2 prefers as postgresql://
            url = re.sub(r"^postgres://", "postgresql://", target)
            # Normalize Neon pooler hostname to direct hostname if present to guarantee DNS resolution
            url = re.sub(r"-pooler\.", ".", url)
            self.db_url = url
            self.db_path = None
            try:
                self.pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=25, dsn=self.db_url)
            except Exception as e:
                print(f"[Warning] Failed to initialize ThreadedConnectionPool: {e}")
                self.pool = None
        else:
            self.is_postgres = False
            self.db_url = None
            self.db_path = target
            
        self.init_db()

    def invalidate_metadata_cache(self):
        """Invalidates in-memory metadata cache upon data modification."""
        self._metadata_cache = None
        self._metadata_cache_time = 0.0

    @contextmanager
    def get_connection(self):
        """Context manager providing a resilient database connection with auto-closing, health checks, and retry."""
        if self.is_postgres:
            conn = None
            last_err = None
            for attempt in range(3):
                is_new_conn = False
                try:
                    if self.pool is not None:
                        try:
                            conn = self.pool.getconn()
                        except Exception:
                            # If connection pool is exhausted or failed under sudden spike, connect directly
                            conn = psycopg2.connect(self.db_url)
                            is_new_conn = True

                        # Ping connection to guarantee it wasn't severed during Neon serverless sleep
                        is_healthy = False
                        if getattr(conn, "closed", 1) == 0:
                            try:
                                with conn.cursor() as cur:
                                    cur.execute("SELECT 1")
                                is_healthy = True
                            except Exception:
                                is_healthy = False

                        if not is_healthy:
                            if not is_new_conn and self.pool is not None:
                                try:
                                    self.pool.putconn(conn, close=True)
                                except Exception:
                                    pass
                            conn = psycopg2.connect(self.db_url)
                            is_new_conn = True
                    else:
                        conn = psycopg2.connect(self.db_url)
                        is_new_conn = True
                    break
                except Exception as e:
                    last_err = e
                    if attempt == 2:
                        raise last_err
                    time.sleep(0.15 * (2 ** attempt))

            try:
                yield conn
            except Exception:
                if conn and getattr(conn, "closed", 1) == 0:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                raise
            finally:
                if conn:
                    if self.pool is not None and not is_new_conn:
                        try:
                            if getattr(conn, "closed", 1) == 0:
                                self.pool.putconn(conn)
                            else:
                                self.pool.putconn(conn, close=True)
                        except Exception:
                            pass
                    else:
                        try:
                            conn.close()
                        except Exception:
                            pass
        else:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                yield conn
            finally:
                conn.close()

    def _get_cursor(self, conn):
        if self.is_postgres:
            return conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        return conn.cursor()

    def _format_query(self, query: str) -> str:
        """Translates '?' parameter markers to '%s' if running on PostgreSQL."""
        if self.is_postgres:
            return query.replace("?", "%s")
        return query

    def init_db(self):
        """Initializes table schema and indexes if they do not exist."""
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            if self.is_postgres:
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS questions (
                    id SERIAL PRIMARY KEY,
                    question_text TEXT NOT NULL,
                    normalized_text TEXT NOT NULL UNIQUE,
                    subject TEXT DEFAULT '',
                    topic TEXT DEFAULT '',
                    frequency INTEGER DEFAULT 1,
                    sources TEXT NOT NULL DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """)
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) UNIQUE NOT NULL,
                    display_name VARCHAR(150) NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    salt VARCHAR(64) NOT NULL,
                    role VARCHAR(20) NOT NULL DEFAULT 'teacher',
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """)
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS exams (
                    id SERIAL PRIMARY KEY,
                    exam_code VARCHAR(50) UNIQUE NOT NULL,
                    title VARCHAR(300) NOT NULL,
                    subject VARCHAR(200) DEFAULT '',
                    duration_minutes INTEGER NOT NULL DEFAULT 60,
                    deadline TIMESTAMP NOT NULL,
                    total_marks REAL NOT NULL DEFAULT 0.0,
                    instructions TEXT DEFAULT '',
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    created_by INTEGER DEFAULT NULL REFERENCES users(id) ON DELETE SET NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """)
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS exam_questions (
                    id SERIAL PRIMARY KEY,
                    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
                    question_id INTEGER DEFAULT NULL REFERENCES questions(id) ON DELETE SET NULL,
                    question_order INTEGER NOT NULL DEFAULT 1,
                    question_text TEXT NOT NULL,
                    marks REAL NOT NULL DEFAULT 1.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """)
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS exam_submissions (
                    id SERIAL PRIMARY KEY,
                    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
                    student_name VARCHAR(150) NOT NULL,
                    roll_number VARCHAR(100) NOT NULL,
                    section VARCHAR(50) DEFAULT '',
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    time_taken_seconds INTEGER DEFAULT 0,
                    status VARCHAR(20) NOT NULL DEFAULT 'submitted',
                    total_score REAL DEFAULT NULL,
                    feedback TEXT DEFAULT '',
                    graded_by INTEGER DEFAULT NULL REFERENCES users(id) ON DELETE SET NULL,
                    graded_at TIMESTAMP DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(exam_id, roll_number)
                );
                """)
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS exam_submission_answers (
                    id SERIAL PRIMARY KEY,
                    submission_id INTEGER NOT NULL REFERENCES exam_submissions(id) ON DELETE CASCADE,
                    question_id INTEGER NOT NULL REFERENCES exam_questions(id) ON DELETE CASCADE,
                    typed_answer TEXT DEFAULT '',
                    image_data TEXT DEFAULT '',
                    marks_awarded REAL DEFAULT NULL,
                    feedback TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """)
            else:
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question_text TEXT NOT NULL,
                    normalized_text TEXT NOT NULL UNIQUE,
                    subject TEXT DEFAULT '',
                    topic TEXT DEFAULT '',
                    frequency INTEGER DEFAULT 1,
                    sources TEXT NOT NULL DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """)
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username VARCHAR(100) UNIQUE NOT NULL,
                    display_name VARCHAR(150) NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    salt VARCHAR(64) NOT NULL,
                    role VARCHAR(20) NOT NULL DEFAULT 'teacher',
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """)
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS exams (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exam_code VARCHAR(50) UNIQUE NOT NULL,
                    title VARCHAR(300) NOT NULL,
                    subject VARCHAR(200) DEFAULT '',
                    duration_minutes INTEGER NOT NULL DEFAULT 60,
                    deadline TIMESTAMP NOT NULL,
                    total_marks REAL NOT NULL DEFAULT 0.0,
                    instructions TEXT DEFAULT '',
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    created_by INTEGER DEFAULT NULL REFERENCES users(id) ON DELETE SET NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """)
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS exam_questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
                    question_id INTEGER DEFAULT NULL REFERENCES questions(id) ON DELETE SET NULL,
                    question_order INTEGER NOT NULL DEFAULT 1,
                    question_text TEXT NOT NULL,
                    marks REAL NOT NULL DEFAULT 1.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """)
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS exam_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
                    student_name VARCHAR(150) NOT NULL,
                    roll_number VARCHAR(100) NOT NULL,
                    section VARCHAR(50) DEFAULT '',
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    time_taken_seconds INTEGER DEFAULT 0,
                    status VARCHAR(20) NOT NULL DEFAULT 'submitted',
                    total_score REAL DEFAULT NULL,
                    feedback TEXT DEFAULT '',
                    graded_by INTEGER DEFAULT NULL REFERENCES users(id) ON DELETE SET NULL,
                    graded_at TIMESTAMP DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(exam_id, roll_number)
                );
                """)
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS exam_submission_answers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    submission_id INTEGER NOT NULL REFERENCES exam_submissions(id) ON DELETE CASCADE,
                    question_id INTEGER NOT NULL REFERENCES exam_questions(id) ON DELETE CASCADE,
                    typed_answer TEXT DEFAULT '',
                    image_data TEXT DEFAULT '',
                    marks_awarded REAL DEFAULT NULL,
                    feedback TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """)
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_questions_normalized ON questions(normalized_text);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_questions_subject ON questions(subject);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_questions_topic ON questions(topic);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_questions_frequency ON questions(frequency);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_exams_code ON exams(exam_code);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_exams_status ON exams(status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_exams_created_at ON exams(created_at);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_exam_questions_exam_id ON exam_questions(exam_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_exam_questions_order ON exam_questions(exam_id, question_order);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_exam_submissions_exam_id ON exam_submissions(exam_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_exam_submissions_roll ON exam_submissions(exam_id, roll_number);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_exam_submissions_status ON exam_submissions(status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sub_answers_sub_id ON exam_submission_answers(submission_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sub_answers_q_id ON exam_submission_answers(question_id);")

            # Resilient schema migration: structured question metadata fields
            if self.is_postgres:
                cursor.execute("ALTER TABLE questions ADD COLUMN IF NOT EXISTS class_level TEXT DEFAULT '';")
                cursor.execute("ALTER TABLE questions ADD COLUMN IF NOT EXISTS question_type TEXT DEFAULT '';")
                cursor.execute("ALTER TABLE questions ADD COLUMN IF NOT EXISTS difficulty TEXT DEFAULT '';")
                cursor.execute("ALTER TABLE questions ADD COLUMN IF NOT EXISTS default_marks REAL DEFAULT NULL;")
                cursor.execute("ALTER TABLE questions ADD COLUMN IF NOT EXISTS needs_review BOOLEAN DEFAULT FALSE;")
                cursor.execute("ALTER TABLE questions ADD COLUMN IF NOT EXISTS review_reason TEXT DEFAULT '';")
                cursor.execute("ALTER TABLE exams ADD COLUMN IF NOT EXISTS class_level VARCHAR(100) DEFAULT '';")
                cursor.execute("ALTER TABLE exams ADD COLUMN IF NOT EXISTS institute_name VARCHAR(200) DEFAULT 'The Squire''s Way';")
                cursor.execute("ALTER TABLE exam_questions ADD COLUMN IF NOT EXISTS section_title VARCHAR(200) DEFAULT '';")
            else:
                cursor.execute("PRAGMA table_info(questions);")
                q_cols = [r[1] for r in cursor.fetchall()]
                if "class_level" not in q_cols:
                    cursor.execute("ALTER TABLE questions ADD COLUMN class_level TEXT DEFAULT '';")
                if "question_type" not in q_cols:
                    cursor.execute("ALTER TABLE questions ADD COLUMN question_type TEXT DEFAULT '';")
                if "difficulty" not in q_cols:
                    cursor.execute("ALTER TABLE questions ADD COLUMN difficulty TEXT DEFAULT '';")
                if "default_marks" not in q_cols:
                    cursor.execute("ALTER TABLE questions ADD COLUMN default_marks REAL DEFAULT NULL;")
                if "needs_review" not in q_cols:
                    cursor.execute("ALTER TABLE questions ADD COLUMN needs_review BOOLEAN DEFAULT 0;")
                if "review_reason" not in q_cols:
                    cursor.execute("ALTER TABLE questions ADD COLUMN review_reason TEXT DEFAULT '';")

                cursor.execute("PRAGMA table_info(exams);")
                e_cols = [r[1] for r in cursor.fetchall()]
                if "class_level" not in e_cols:
                    cursor.execute("ALTER TABLE exams ADD COLUMN class_level VARCHAR(100) DEFAULT '';")
                if "institute_name" not in e_cols:
                    cursor.execute("ALTER TABLE exams ADD COLUMN institute_name VARCHAR(200) DEFAULT 'The Squire''s Way';")

                cursor.execute("PRAGMA table_info(exam_questions);")
                eq_cols = [r[1] for r in cursor.fetchall()]
                if "section_title" not in eq_cols:
                    cursor.execute("ALTER TABLE exam_questions ADD COLUMN section_title VARCHAR(200) DEFAULT '';")

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_questions_class_level ON questions(class_level);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_questions_type ON questions(question_type);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_questions_difficulty ON questions(difficulty);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_questions_needs_review ON questions(needs_review);")

            # Resilient schema migration: emergency submission tracking
            try:
                if self.is_postgres:
                    cursor.execute("ALTER TABLE exam_submissions ADD COLUMN IF NOT EXISTS is_emergency BOOLEAN DEFAULT FALSE;")
                    cursor.execute("ALTER TABLE exam_submissions ADD COLUMN IF NOT EXISTS emergency_hash VARCHAR(100) DEFAULT NULL;")
                else:
                    cursor.execute("PRAGMA table_info(exam_submissions);")
                    cols = [r[1] for r in cursor.fetchall()]
                    if "is_emergency" not in cols:
                        cursor.execute("ALTER TABLE exam_submissions ADD COLUMN is_emergency BOOLEAN DEFAULT 0;")
                    if "emergency_hash" not in cols:
                        cursor.execute("ALTER TABLE exam_submissions ADD COLUMN emergency_hash VARCHAR(100) DEFAULT NULL;")
            except Exception:
                pass

            conn.commit()

    def _bool_val(self, val: bool):
        return bool(val) if self.is_postgres else int(bool(val))

    def _row_to_question_dict(self, r, include_normalized: bool = False) -> Dict[str, Any]:
        try:
            srcs = json.loads(r["sources"]) if r["sources"] else []
        except Exception:
            srcs = []
        keys = r.keys() if hasattr(r, "keys") else []
        def _get(col, default=None):
            if col in keys:
                return r[col]
            return default

        item = {
            "id": r["id"],
            "question_text": r["question_text"],
            "class_level": _get("class_level") or "",
            "subject": _get("subject") or "",
            "topic": _get("topic") or "",
            "question_type": _get("question_type") or "",
            "difficulty": _get("difficulty") or "",
            "default_marks": float(_get("default_marks")) if _get("default_marks") is not None else None,
            "needs_review": bool(_get("needs_review")) if _get("needs_review") is not None else False,
            "review_reason": _get("review_reason") or "",
            "frequency": r["frequency"] or 1,
            "sources": srcs,
            "created_at": str(r["created_at"]),
            "updated_at": str(r["updated_at"]),
        }
        if include_normalized:
            item["normalized_text"] = _get("normalized_text") or ""
        return item

    def find_existing_normalized_map(self, normalized_texts: List[str]) -> Dict[str, Dict[str, Any]]:
        """Batch-looks up existing questions by normalized_text for fast import preview."""
        if not normalized_texts:
            return {}
        unique_norms = list(dict.fromkeys([n for n in normalized_texts if n]))
        if not unique_norms:
            return {}
        found: Dict[str, Dict[str, Any]] = {}
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            chunk_size = 200
            for i in range(0, len(unique_norms), chunk_size):
                chunk = unique_norms[i : i + chunk_size]
                placeholders = ",".join("?" for _ in chunk)
                q = self._format_query(
                    f"SELECT id, normalized_text, question_text, frequency, class_level, subject, topic FROM questions WHERE normalized_text IN ({placeholders})"
                )
                cursor.execute(q, chunk)
                for r in cursor.fetchall():
                    found[r["normalized_text"]] = {
                        "id": r["id"],
                        "question_text": r["question_text"],
                        "frequency": r["frequency"] or 1,
                        "class_level": r["class_level"] or "",
                        "subject": r["subject"] or "",
                        "topic": r["topic"] or "",
                    }
        return found

    def upsert_question(
        self,
        question_text: str,
        normalized_text: str,
        subject: str = "",
        topic: str = "",
        source_filename: str = "",
        class_level: str = "",
        question_type: str = "",
        difficulty: str = "",
        default_marks: Optional[float] = None,
        needs_review: bool = False,
        review_reason: str = "",
    ) -> Tuple[int, bool]:
        """
        Inserts a new question or merges if exact normalized match exists.
        Returns: (question_id, is_merged)
        """
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            query = self._format_query(
                "SELECT id, frequency, sources, subject, topic, class_level, question_type, difficulty, default_marks, needs_review, review_reason "
                "FROM questions WHERE normalized_text = ?"
            )
            cursor.execute(query, (normalized_text,))
            row = cursor.fetchone()

            if row:
                question_id = row["id"]
                current_freq = row["frequency"] or 1
                try:
                    sources_list = json.loads(row["sources"]) if row["sources"] else []
                except Exception:
                    sources_list = []

                if source_filename and source_filename not in sources_list:
                    sources_list.append(source_filename)

                new_subject = row["subject"] if row["subject"] else subject
                new_topic = row["topic"] if row["topic"] else topic
                new_class = row["class_level"] if row["class_level"] else class_level
                new_type = row["question_type"] if row["question_type"] else question_type
                new_diff = row["difficulty"] if row["difficulty"] else difficulty
                new_marks = row["default_marks"] if row["default_marks"] is not None else default_marks
                existing_nr = bool(row["needs_review"]) if row["needs_review"] is not None else False
                new_nr = existing_nr
                new_reason = row["review_reason"] or ""

                update_query = self._format_query("""
                    UPDATE questions
                    SET frequency = ?,
                        sources = ?,
                        subject = ?,
                        topic = ?,
                        class_level = ?,
                        question_type = ?,
                        difficulty = ?,
                        default_marks = ?,
                        needs_review = ?,
                        review_reason = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """)
                cursor.execute(
                    update_query,
                    (
                        current_freq + 1,
                        json.dumps(sources_list),
                        new_subject,
                        new_topic,
                        new_class,
                        new_type,
                        new_diff,
                        new_marks,
                        self._bool_val(new_nr),
                        new_reason,
                        question_id,
                    ),
                )
                conn.commit()
                self.invalidate_metadata_cache()
                return question_id, True
            else:
                sources_list = [source_filename] if source_filename else []
                insert_query = self._format_query("""
                    INSERT INTO questions (
                        question_text, normalized_text, class_level, subject, topic,
                        question_type, difficulty, default_marks, needs_review, review_reason,
                        frequency, sources
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                    RETURNING id
                """)
                cursor.execute(
                    insert_query,
                    (
                        question_text,
                        normalized_text,
                        class_level,
                        subject,
                        topic,
                        question_type,
                        difficulty,
                        default_marks,
                        self._bool_val(needs_review),
                        review_reason,
                        json.dumps(sources_list),
                    ),
                )
                inserted_id = cursor.fetchone()[0]
                conn.commit()
                self.invalidate_metadata_cache()
                return inserted_id, False

    def get_questions(
        self,
        search: Optional[str] = None,
        subject: Optional[str] = None,
        topic: Optional[str] = None,
        source: Optional[str] = None,
        class_level: Optional[str] = None,
        question_type: Optional[str] = None,
        difficulty: Optional[str] = None,
        needs_review: Optional[bool] = None,
        sort_by: str = "recent",
        page: int = 1,
        limit: int = 50,
    ) -> Dict[str, Any]:
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            query_parts = ["1=1"]
            params: List[Any] = []

            if search and search.strip():
                if self.is_postgres:
                    query_parts.append("(question_text ILIKE ? OR normalized_text ILIKE ? OR topic ILIKE ?)")
                else:
                    query_parts.append("(question_text LIKE ? OR normalized_text LIKE ? OR topic LIKE ?)")
                search_param = f"%{search.strip()}%"
                params.extend([search_param, search_param, search_param])

            if subject and subject.strip():
                query_parts.append("LOWER(subject) = LOWER(?)")
                params.append(subject.strip())

            if topic and topic.strip():
                query_parts.append("LOWER(topic) = LOWER(?)")
                params.append(topic.strip())

            if class_level and class_level.strip():
                query_parts.append("LOWER(class_level) = LOWER(?)")
                params.append(class_level.strip())

            if question_type and question_type.strip():
                query_parts.append("LOWER(question_type) = LOWER(?)")
                params.append(question_type.strip())

            if difficulty and difficulty.strip():
                query_parts.append("LOWER(difficulty) = LOWER(?)")
                params.append(difficulty.strip())

            if needs_review is not None:
                if needs_review:
                    query_parts.append("needs_review = ?" if self.is_postgres else "COALESCE(needs_review, 0) = 1")
                    if self.is_postgres:
                        params.append(True)
                else:
                    query_parts.append("COALESCE(needs_review, FALSE) = FALSE" if self.is_postgres else "COALESCE(needs_review, 0) = 0")

            if source and source.strip():
                query_parts.append("sources LIKE ?")
                params.append(f"%{source.strip()}%")

            where_clause = " AND ".join(query_parts)

            sort_map = {
                "recent": "updated_at DESC, id DESC",
                "most_repeated": "frequency DESC, updated_at DESC, id DESC",
                "frequency_desc": "frequency DESC, updated_at DESC, id DESC",
                "least_repeated": "frequency ASC, id ASC",
                "frequency_asc": "frequency ASC, id ASC",
                "marks_desc": "COALESCE(default_marks, -1) DESC, frequency DESC, id DESC",
                "marks_asc": "COALESCE(default_marks, 9999) ASC, frequency DESC, id DESC",
                "oldest": "id ASC",
            }
            order_by = sort_map.get((sort_by or "recent").lower().strip(), "updated_at DESC, id DESC")

            count_query = self._format_query(f"SELECT COUNT(*) FROM questions WHERE {where_clause}")
            cursor.execute(count_query, params)
            total = cursor.fetchone()[0]

            offset = max(0, (page - 1) * limit)
            select_query = self._format_query(f"""
                SELECT id, question_text, class_level, subject, topic, question_type, difficulty,
                       default_marks, needs_review, review_reason, frequency, sources, created_at, updated_at
                FROM questions
                WHERE {where_clause}
                ORDER BY {order_by}
                LIMIT ? OFFSET ?
            """)
            cursor.execute(select_query, params + [limit, offset])

            rows = cursor.fetchall()
            items = [self._row_to_question_dict(r) for r in rows]

            return {
                "total": total,
                "page": page,
                "limit": limit,
                "items": items
            }

    def get_questions_by_ids(self, question_ids: List[int]) -> List[Dict[str, Any]]:
        if not question_ids:
            return []
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            placeholders = ",".join("?" for _ in question_ids)
            query = self._format_query(f"""
                SELECT id, question_text, class_level, subject, topic, question_type, difficulty,
                       default_marks, needs_review, review_reason, frequency, sources, created_at, updated_at
                FROM questions
                WHERE id IN ({placeholders})
            """)
            cursor.execute(query, question_ids)
            rows = cursor.fetchall()
            q_map = {r["id"]: self._row_to_question_dict(r) for r in rows}

            ordered = []
            for qid in question_ids:
                if qid in q_map:
                    ordered.append(q_map[qid])
            return ordered

    def update_question(
        self,
        question_id: int,
        question_text: Optional[str] = None,
        normalized_text: Optional[str] = None,
        subject: Optional[str] = None,
        topic: Optional[str] = None,
        class_level: Optional[str] = None,
        question_type: Optional[str] = None,
        difficulty: Optional[str] = None,
        default_marks: Optional[float] = None,
        clear_default_marks: bool = False,
        needs_review: Optional[bool] = None,
        review_reason: Optional[str] = None,
    ) -> bool:
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)

            if normalized_text is not None:
                dup_q = self._format_query("SELECT id FROM questions WHERE normalized_text = ? AND id != ?")
                cursor.execute(dup_q, (normalized_text, question_id))
                dup_row = cursor.fetchone()
                if dup_row:
                    raise ValueError(
                        f"A question with identical normalized text already exists (#{dup_row['id']}). Use Merge Duplicates to combine them."
                    )

            updates = ["updated_at = CURRENT_TIMESTAMP"]
            params: List[Any] = []

            if question_text is not None:
                updates.append("question_text = ?")
                params.append(question_text)
            if normalized_text is not None:
                updates.append("normalized_text = ?")
                params.append(normalized_text)
            if subject is not None:
                updates.append("subject = ?")
                params.append(subject)
            if topic is not None:
                updates.append("topic = ?")
                params.append(topic)
            if class_level is not None:
                updates.append("class_level = ?")
                params.append(class_level)
            if question_type is not None:
                updates.append("question_type = ?")
                params.append(question_type)
            if difficulty is not None:
                updates.append("difficulty = ?")
                params.append(difficulty)
            if clear_default_marks:
                updates.append("default_marks = NULL")
            elif default_marks is not None:
                updates.append("default_marks = ?")
                params.append(float(default_marks))
            if needs_review is not None:
                updates.append("needs_review = ?")
                params.append(self._bool_val(needs_review))
                if not needs_review and review_reason is None:
                    updates.append("review_reason = ?")
                    params.append("")
            if review_reason is not None:
                updates.append("review_reason = ?")
                params.append(review_reason)

            params.append(question_id)
            query = self._format_query(f"UPDATE questions SET {', '.join(updates)} WHERE id = ?")
            cursor.execute(query, params)
            conn.commit()
            if cursor.rowcount > 0:
                self.invalidate_metadata_cache()
                return True
            return False

    def bulk_update_questions(
        self,
        question_ids: List[int],
        subject: Optional[str] = None,
        topic: Optional[str] = None,
        class_level: Optional[str] = None,
        question_type: Optional[str] = None,
        difficulty: Optional[str] = None,
        default_marks: Optional[float] = None,
        needs_review: Optional[bool] = None,
        review_reason: Optional[str] = None,
    ) -> int:
        if not question_ids:
            return 0
        updates = ["updated_at = CURRENT_TIMESTAMP"]
        params: List[Any] = []

        if subject is not None:
            updates.append("subject = ?")
            params.append(subject)
        if topic is not None:
            updates.append("topic = ?")
            params.append(topic)
        if class_level is not None:
            updates.append("class_level = ?")
            params.append(class_level)
        if question_type is not None:
            updates.append("question_type = ?")
            params.append(question_type)
        if difficulty is not None:
            updates.append("difficulty = ?")
            params.append(difficulty)
        if default_marks is not None:
            updates.append("default_marks = ?")
            params.append(float(default_marks))
        if needs_review is not None:
            updates.append("needs_review = ?")
            params.append(self._bool_val(needs_review))
            if not needs_review and review_reason is None:
                updates.append("review_reason = ?")
                params.append("")
        if review_reason is not None:
            updates.append("review_reason = ?")
            params.append(review_reason)

        if len(updates) == 1:
            return 0

        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            placeholders = ",".join("?" for _ in question_ids)
            query = self._format_query(f"UPDATE questions SET {', '.join(updates)} WHERE id IN ({placeholders})")
            cursor.execute(query, params + question_ids)
            conn.commit()
            count = cursor.rowcount
            if count > 0:
                self.invalidate_metadata_cache()
            return count

    def merge_questions(
        self,
        target_id: int,
        source_ids: List[int],
        merged_text: Optional[str] = None,
        merged_normalized_text: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Merges one or more duplicate question records (`source_ids`) into `target_id`.
        Sums frequencies, unions source filenames, preserves best metadata, repoints exam_questions,
        and deletes `source_ids`.
        """
        clean_sources = [sid for sid in dict.fromkeys(source_ids) if sid != target_id]
        if not clean_sources:
            raise ValueError("At least one distinct duplicate question ID must be provided to merge.")

        all_ids = [target_id] + clean_sources
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            placeholders = ",".join("?" for _ in all_ids)
            cursor.execute(
                self._format_query(
                    f"SELECT id, question_text, normalized_text, class_level, subject, topic, question_type, "
                    f"difficulty, default_marks, needs_review, review_reason, frequency, sources "
                    f"FROM questions WHERE id IN ({placeholders})"
                ),
                all_ids,
            )
            rows = cursor.fetchall()
            row_map = {r["id"]: r for r in rows}
            if target_id not in row_map:
                return None

            target = row_map[target_id]
            total_freq = int(target["frequency"] or 1)
            try:
                merged_src_list = json.loads(target["sources"]) if target["sources"] else []
            except Exception:
                merged_src_list = []

            class_level = target["class_level"] or ""
            subject = target["subject"] or ""
            topic = target["topic"] or ""
            q_type = target["question_type"] or ""
            diff = target["difficulty"] or ""
            def_marks = target["default_marks"]

            actual_losers = []
            for sid in clean_sources:
                src_row = row_map.get(sid)
                if not src_row:
                    continue
                actual_losers.append(sid)
                total_freq += int(src_row["frequency"] or 1)
                try:
                    s_srcs = json.loads(src_row["sources"]) if src_row["sources"] else []
                except Exception:
                    s_srcs = []
                for s in s_srcs:
                    if s and s not in merged_src_list:
                        merged_src_list.append(s)

                if not class_level and src_row["class_level"]:
                    class_level = src_row["class_level"]
                if not subject and src_row["subject"]:
                    subject = src_row["subject"]
                if not topic and src_row["topic"]:
                    topic = src_row["topic"]
                if not q_type and src_row["question_type"]:
                    q_type = src_row["question_type"]
                if not diff and src_row["difficulty"]:
                    diff = src_row["difficulty"]
                if def_marks is None and src_row["default_marks"] is not None:
                    def_marks = src_row["default_marks"]

            if not actual_losers:
                raise ValueError("None of the specified source duplicate IDs were found.")

            # Repoint exam_questions referencing losers
            loser_ph = ",".join("?" for _ in actual_losers)
            cursor.execute(
                self._format_query(f"UPDATE exam_questions SET question_id = ? WHERE question_id IN ({loser_ph})"),
                [target_id] + actual_losers,
            )

            # Delete losers BEFORE updating normalized_text to avoid UNIQUE constraint collision
            cursor.execute(
                self._format_query(f"DELETE FROM questions WHERE id IN ({loser_ph})"),
                actual_losers,
            )

            final_text = merged_text if merged_text is not None else target["question_text"]
            final_norm = merged_normalized_text if merged_normalized_text is not None else target["normalized_text"]

            # Ensure final_norm doesn't collide with any other unrelated row
            cursor.execute(
                self._format_query("SELECT id FROM questions WHERE normalized_text = ? AND id != ?"),
                (final_norm, target_id),
            )
            other_dup = cursor.fetchone()
            if other_dup:
                raise ValueError(f"Merged text matches another existing question (#{other_dup['id']}). Include #{other_dup['id']} in the merge.")

            upd_q = self._format_query("""
                UPDATE questions
                SET question_text = ?,
                    normalized_text = ?,
                    class_level = ?,
                    subject = ?,
                    topic = ?,
                    question_type = ?,
                    difficulty = ?,
                    default_marks = ?,
                    needs_review = ?,
                    review_reason = ?,
                    frequency = ?,
                    sources = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """)
            cursor.execute(
                upd_q,
                (
                    final_text,
                    final_norm,
                    class_level,
                    subject,
                    topic,
                    q_type,
                    diff,
                    def_marks,
                    self._bool_val(False),
                    "",
                    total_freq,
                    json.dumps(merged_src_list),
                    target_id,
                ),
            )
            conn.commit()
            self.invalidate_metadata_cache()

        res = self.get_questions_by_ids([target_id])
        return res[0] if res else None

    def find_potential_duplicates(self, threshold: float = 0.80, limit_groups: int = 40) -> List[Dict[str, Any]]:
        """
        Scans the library for near-duplicate question groups (typos, minor wording/punctuation differences)
        so teachers can review and merge them cleanly.
        """
        from backend.services.dedup import compute_text_similarity

        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            cursor.execute("""
                SELECT id, question_text, normalized_text, class_level, subject, topic, question_type,
                       difficulty, default_marks, needs_review, review_reason, frequency, sources, created_at, updated_at
                FROM questions
                ORDER BY frequency DESC, id ASC
            """)
            rows = cursor.fetchall()

        records = [self._row_to_question_dict(r, include_normalized=True) for r in rows]
        n = len(records)
        if n < 2:
            return []

        # Bucket by class_level + token signature to keep comparison fast even at 5000+ rows
        visited = set()
        groups: List[Dict[str, Any]] = []

        # Precompute word tokens
        tokens_list = [set(re.findall(r"[a-z0-9]{3,}", rec["normalized_text"])) for rec in records]

        for i in range(n):
            if records[i]["id"] in visited:
                continue
            ri = records[i]
            ti = tokens_list[i]
            if len(ri["normalized_text"]) < 12:
                continue

            cluster = [ri]
            best_sim = 0.0
            cls_i = (ri.get("class_level") or "").strip().lower()
            for j in range(i + 1, n):
                rj = records[j]
                if rj["id"] in visited:
                    continue
                cls_j = (rj.get("class_level") or "").strip().lower()
                if cls_i and cls_j and cls_i != cls_j:
                    continue
                # Quick length & token overlap filter before SequenceMatcher
                len_a, len_b = len(ri["normalized_text"]), len(rj["normalized_text"])
                if min(len_a, len_b) / max(len_a, len_b, 1) < 0.65:
                    continue
                tj = tokens_list[j]
                if ti and tj:
                    overlap = len(ti & tj) / max(len(ti | tj), 1)
                    if overlap < 0.45:
                        continue
                sim = compute_text_similarity(ri["normalized_text"], rj["normalized_text"])
                # Prevent cross-chapter / cross-subject false positives unless near-verbatim (>= 0.95)
                eff_threshold = threshold
                topic_j = (rj.get("topic") or "").strip().lower()
                subj_j = (rj.get("subject") or "").strip().lower()
                cluster_topics = {(c.get("topic") or "").strip().lower() for c in cluster if (c.get("topic") or "").strip()}
                cluster_subjects = {(c.get("subject") or "").strip().lower() for c in cluster if (c.get("subject") or "").strip()}
                if topic_j and any(t != topic_j for t in cluster_topics):
                    eff_threshold = max(eff_threshold, 0.95)
                if subj_j and any(s != subj_j for s in cluster_subjects):
                    eff_threshold = max(eff_threshold, 0.95)
                if sim >= eff_threshold:
                    cluster.append(rj)
                    best_sim = max(best_sim, sim)

            if len(cluster) > 1:
                for item in cluster:
                    visited.add(item["id"])
                groups.append({
                    "similarity": round(best_sim * 100, 1),
                    "suggested_target_id": cluster[0]["id"],
                    "questions": cluster,
                })
                if len(groups) >= limit_groups:
                    break

        return groups

    def auto_pick_questions(
        self,
        class_level: Optional[str] = None,
        subject: Optional[str] = None,
        topics: Optional[List[str]] = None,
        question_type: Optional[str] = None,
        difficulty: Optional[str] = None,
        count: Optional[int] = None,
        target_marks: Optional[float] = None,
        prefer_most_repeated: bool = True,
        spread_topics: bool = True,
        exclude_needs_review: bool = True,
        exclude_ids: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """
        1-Click Auto-Pick Paper Builder: selects balanced questions matching filters,
        up to `count` questions or `target_marks`, prioritizing most repeated questions and chapter diversity.
        """
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            query_parts = ["1=1"]
            params: List[Any] = []

            if class_level and class_level.strip():
                query_parts.append("LOWER(class_level) = LOWER(?)")
                params.append(class_level.strip())
            if subject and subject.strip():
                query_parts.append("LOWER(subject) = LOWER(?)")
                params.append(subject.strip())
            if topics:
                clean_topics = [t.strip().lower() for t in topics if t and t.strip()]
                if clean_topics:
                    t_ph = ",".join("?" for _ in clean_topics)
                    query_parts.append(f"LOWER(topic) IN ({t_ph})")
                    params.extend(clean_topics)
            if question_type and question_type.strip():
                query_parts.append("LOWER(question_type) = LOWER(?)")
                params.append(question_type.strip())
            if difficulty and difficulty.strip():
                query_parts.append("LOWER(difficulty) = LOWER(?)")
                params.append(difficulty.strip())
            if exclude_needs_review:
                query_parts.append("COALESCE(needs_review, FALSE) = FALSE" if self.is_postgres else "COALESCE(needs_review, 0) = 0")
            if exclude_ids:
                ex_ph = ",".join("?" for _ in exclude_ids)
                query_parts.append(f"id NOT IN ({ex_ph})")
                params.extend(exclude_ids)

            where_clause = " AND ".join(query_parts)
            order_sql = "frequency DESC, updated_at DESC, id ASC" if prefer_most_repeated else "updated_at DESC, id DESC"
            query = self._format_query(f"""
                SELECT id, question_text, class_level, subject, topic, question_type, difficulty,
                       default_marks, needs_review, review_reason, frequency, sources, created_at, updated_at
                FROM questions
                WHERE {where_clause}
                ORDER BY {order_sql}
            """)
            cursor.execute(query, params)
            candidates = [self._row_to_question_dict(r) for r in cursor.fetchall()]

        if not candidates:
            return {"questions": [], "total_picked": 0, "total_marks": 0.0, "available_matching": 0}

        # Order candidates with round-robin chapter spread if spread_topics=True
        if spread_topics:
            buckets: Dict[str, List[Dict[str, Any]]] = {}
            for c in candidates:
                key = (c.get("topic") or "General").lower()
                buckets.setdefault(key, []).append(c)
            ordered_candidates: List[Dict[str, Any]] = []
            bucket_lists = list(buckets.values())
            max_len = max(len(b) for b in bucket_lists)
            for idx in range(max_len):
                for b in bucket_lists:
                    if idx < len(b):
                        ordered_candidates.append(b[idx])
        else:
            ordered_candidates = candidates

        picked: List[Dict[str, Any]] = []
        running_marks = 0.0
        max_count = count if (count and count > 0) else None
        max_marks = float(target_marks) if (target_marks and target_marks > 0) else None
        if max_count is None and max_marks is None:
            max_count = 10

        for cand in ordered_candidates:
            q_marks = float(cand["default_marks"]) if cand.get("default_marks") is not None else 2.0
            if max_marks is not None:
                # Never exceed target_marks
                if running_marks + q_marks > max_marks:
                    continue
            picked.append(cand)
            running_marks += q_marks
            if max_count is not None and len(picked) >= max_count:
                break
            if max_marks is not None and running_marks >= max_marks:
                break

        return {
            "questions": picked,
            "total_picked": len(picked),
            "total_marks": round(running_marks, 2),
            "available_matching": len(candidates),
        }

    def delete_question(self, question_id: int) -> bool:
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            query = self._format_query("DELETE FROM questions WHERE id = ?")
            cursor.execute(query, (question_id,))
            conn.commit()
            if cursor.rowcount > 0:
                self.invalidate_metadata_cache()
                return True
            return False

    def delete_questions(self, question_ids: List[int]) -> int:
        if not question_ids:
            return 0
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            placeholders = ",".join("?" for _ in question_ids)
            query = self._format_query(f"DELETE FROM questions WHERE id IN ({placeholders})")
            cursor.execute(query, question_ids)
            conn.commit()
            count = cursor.rowcount
            if count > 0:
                self.invalidate_metadata_cache()
            return count

    def get_metadata(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Returns distinct classes, subjects, topics, types, difficulties, and sources with stats."""
        now = time.time()
        if not force_refresh and self._metadata_cache is not None and (now - self._metadata_cache_time < self._metadata_ttl):
            return dict(self._metadata_cache)

        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)

            cursor.execute("SELECT COUNT(*), COALESCE(SUM(frequency), 0) FROM questions")
            row = cursor.fetchone()
            unique_count = row[0] or 0
            total_occurrences = row[1] or 0
            merged_count = max(0, total_occurrences - unique_count)

            nr_sql = "SELECT COUNT(*) FROM questions WHERE needs_review = TRUE" if self.is_postgres else "SELECT COUNT(*) FROM questions WHERE COALESCE(needs_review, 0) = 1"
            cursor.execute(nr_sql)
            needs_review_count = cursor.fetchone()[0] or 0

            cursor.execute("SELECT DISTINCT class_level FROM questions WHERE class_level != '' AND class_level IS NOT NULL ORDER BY class_level ASC")
            class_levels = [r[0] for r in cursor.fetchall()]

            cursor.execute("SELECT DISTINCT subject FROM questions WHERE subject != '' AND subject IS NOT NULL ORDER BY subject ASC")
            subjects = [r[0] for r in cursor.fetchall()]

            cursor.execute("SELECT DISTINCT topic FROM questions WHERE topic != '' AND topic IS NOT NULL ORDER BY topic ASC")
            topics = [r[0] for r in cursor.fetchall()]

            cursor.execute("SELECT DISTINCT question_type FROM questions WHERE question_type != '' AND question_type IS NOT NULL ORDER BY question_type ASC")
            question_types = [r[0] for r in cursor.fetchall()]

            cursor.execute("SELECT DISTINCT difficulty FROM questions WHERE difficulty != '' AND difficulty IS NOT NULL ORDER BY difficulty ASC")
            difficulties = [r[0] for r in cursor.fetchall()]

            cursor.execute("SELECT sources FROM questions")
            all_sources = set()
            for r in cursor.fetchall():
                if r[0]:
                    try:
                        for s in json.loads(r[0]):
                            if s:
                                all_sources.add(s)
                    except Exception:
                        pass

            res = {
                "total_unique": unique_count,
                "total_occurrences": total_occurrences,
                "merged_duplicates": merged_count,
                "needs_review_count": needs_review_count,
                "class_levels": class_levels,
                "subjects": subjects,
                "topics": topics,
                "question_types": question_types,
                "difficulties": difficulties,
                "sources": sorted(list(all_sources)),
                "is_postgres": self.is_postgres
            }
            self._metadata_cache = res
            self._metadata_cache_time = time.time()
            return res

    def get_all_questions_for_backup(self) -> List[Dict[str, Any]]:
        """Exports all questions in full detail for JSON backup and portability."""
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            cursor.execute("""
                SELECT id, question_text, normalized_text, class_level, subject, topic,
                       question_type, difficulty, default_marks, needs_review, review_reason,
                       frequency, sources, created_at, updated_at
                FROM questions
                ORDER BY id ASC
            """)
            rows = cursor.fetchall()
            return [self._row_to_question_dict(r, include_normalized=True) for r in rows]

    def restore_questions_from_backup(self, questions_data: List[Dict[str, Any]]) -> Dict[str, int]:
        """Restores a list of question records from backup, merging with existing where applicable."""
        restored = 0
        merged = 0
        skipped = 0
        from backend.services.dedup import clean_question_text, normalize_question_text

        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            for q in questions_data:
                q_text = q.get("question_text", "")
                cleaned = clean_question_text(q_text)
                if not cleaned:
                    skipped += 1
                    continue

                norm_text = q.get("normalized_text") or normalize_question_text(cleaned)
                if not norm_text:
                    skipped += 1
                    continue

                subject = (q.get("subject") or "").strip()
                topic = (q.get("topic") or "").strip()
                class_level = (q.get("class_level") or "").strip()
                question_type = (q.get("question_type") or "").strip()
                difficulty = (q.get("difficulty") or "").strip()
                default_marks = q.get("default_marks")
                needs_review = bool(q.get("needs_review", False))
                review_reason = (q.get("review_reason") or "").strip()
                sources = q.get("sources", [])
                source_name = sources[0] if isinstance(sources, list) and sources else "Backup Import"

                query = self._format_query(
                    "SELECT id, frequency, sources, subject, topic, class_level, question_type, difficulty, default_marks "
                    "FROM questions WHERE normalized_text = ?"
                )
                cursor.execute(query, (norm_text,))
                row = cursor.fetchone()

                if row:
                    question_id = row["id"]
                    current_freq = row["frequency"] or 1
                    try:
                        sources_list = json.loads(row["sources"]) if row["sources"] else []
                    except Exception:
                        sources_list = []

                    if source_name and source_name not in sources_list:
                        sources_list.append(source_name)

                    new_subject = row["subject"] if row["subject"] else subject
                    new_topic = row["topic"] if row["topic"] else topic
                    new_class = row["class_level"] if row["class_level"] else class_level
                    new_type = row["question_type"] if row["question_type"] else question_type
                    new_diff = row["difficulty"] if row["difficulty"] else difficulty
                    new_marks = row["default_marks"] if row["default_marks"] is not None else default_marks

                    update_query = self._format_query("""
                        UPDATE questions
                        SET frequency = ?,
                            sources = ?,
                            subject = ?,
                            topic = ?,
                            class_level = ?,
                            question_type = ?,
                            difficulty = ?,
                            default_marks = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """)
                    cursor.execute(
                        update_query,
                        (current_freq + 1, json.dumps(sources_list), new_subject, new_topic, new_class, new_type, new_diff, new_marks, question_id),
                    )
                    merged += 1
                else:
                    sources_list = [s for s in sources if s] if isinstance(sources, list) and sources else ([source_name] if source_name else [])
                    insert_query = self._format_query("""
                        INSERT INTO questions (
                            question_text, normalized_text, class_level, subject, topic,
                            question_type, difficulty, default_marks, needs_review, review_reason,
                            frequency, sources
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """)
                    cursor.execute(
                        insert_query,
                        (
                            cleaned,
                            norm_text,
                            class_level,
                            subject,
                            topic,
                            question_type,
                            difficulty,
                            default_marks,
                            self._bool_val(needs_review),
                            review_reason,
                            json.dumps(sources_list),
                        ),
                    )
                    restored += 1

            conn.commit()
            self.invalidate_metadata_cache()

        return {
            "restored": restored,
            "merged": merged,
            "skipped": skipped,
            "total": len(questions_data)
        }

    # ================= User Management Methods =================

    def create_user(
        self,
        username: str,
        display_name: str,
        password_hash: str,
        salt: str,
        role: str = "teacher"
    ) -> int:
        """Creates a new user record. Returns the new user ID."""
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            clean_username = username.strip().lower()
            clean_name = display_name.strip() or clean_username
            clean_role = role.strip().lower() if role.strip().lower() in ("admin", "teacher") else "teacher"

            if self.is_postgres:
                query = """
                    INSERT INTO users (username, display_name, password_hash, salt, role, is_active)
                    VALUES (%s, %s, %s, %s, %s, TRUE)
                    RETURNING id
                """
                cursor.execute(query, (clean_username, clean_name, password_hash, salt, clean_role))
                user_id = cursor.fetchone()[0]
            else:
                query = """
                    INSERT INTO users (username, display_name, password_hash, salt, role, is_active)
                    VALUES (?, ?, ?, ?, ?, 1)
                """
                cursor.execute(query, (clean_username, clean_name, password_hash, salt, clean_role))
                user_id = cursor.lastrowid

            conn.commit()
            return user_id

    def get_user_by_username(self, username: str, case_sensitive: bool = True) -> Optional[Dict[str, Any]]:
        """Retrieves a user by username (case-sensitive by default)."""
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            if case_sensitive:
                query = self._format_query("""
                    SELECT id, username, display_name, password_hash, salt, role, is_active, created_at, updated_at
                    FROM users
                    WHERE username = ?
                """)
            else:
                query = self._format_query("""
                    SELECT id, username, display_name, password_hash, salt, role, is_active, created_at, updated_at
                    FROM users
                    WHERE LOWER(username) = LOWER(?)
                """)
            cursor.execute(query, (username.strip(),))
            row = cursor.fetchone()
            if not row:
                return None
            if case_sensitive and row["username"] != username.strip():
                return None
            return {
                "id": row["id"],
                "username": row["username"],
                "display_name": row["display_name"],
                "password_hash": row["password_hash"],
                "salt": row["salt"],
                "role": row["role"],
                "is_active": bool(row["is_active"]),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"])
            }

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves a user by ID."""
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            query = self._format_query("""
                SELECT id, username, display_name, password_hash, salt, role, is_active, created_at, updated_at
                FROM users
                WHERE id = ?
            """)
            cursor.execute(query, (user_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "username": row["username"],
                "display_name": row["display_name"],
                "password_hash": row["password_hash"],
                "salt": row["salt"],
                "role": row["role"],
                "is_active": bool(row["is_active"]),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"])
            }

    def list_users(self) -> List[Dict[str, Any]]:
        """Lists all registered users (excluding sensitive password hashes)."""
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            query = "SELECT id, username, display_name, role, is_active, created_at, updated_at FROM users ORDER BY id ASC"
            cursor.execute(query)
            rows = cursor.fetchall()
            return [
                {
                    "id": r["id"],
                    "username": r["username"],
                    "display_name": r["display_name"],
                    "role": r["role"],
                    "is_active": bool(r["is_active"]),
                    "created_at": str(r["created_at"]),
                    "updated_at": str(r["updated_at"])
                }
                for r in rows
            ]

    def update_user_password(self, user_id: int, password_hash: str, salt: str) -> bool:
        """Updates user password hash and salt."""
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            query = self._format_query("""
                UPDATE users
                SET password_hash = ?, salt = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """)
            cursor.execute(query, (password_hash, salt, user_id))
            conn.commit()
            return cursor.rowcount > 0

    def delete_user(self, user_id: int) -> bool:
        """Deletes a user by ID."""
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            query = self._format_query("DELETE FROM users WHERE id = ?")
            cursor.execute(query, (user_id,))
            conn.commit()
            return cursor.rowcount > 0

    def count_users(self) -> int:
        """Returns the total number of users."""
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            cursor.execute("SELECT COUNT(*) FROM users")
            res = cursor.fetchone()
            return res[0] if res else 0

    # ==========================================
    # Digital Exams & Evaluation Studio Methods
    # ==========================================

    def generate_exam_slug(self, subject: str = "") -> str:
        """Generates a short unique exam slug, e.g. ENG-2026-X9A."""
        clean_subj = re.sub(r'[^A-Za-z]', '', subject or "").upper()[:4] or "EXAM"
        if len(clean_subj) < 3:
            clean_subj = (clean_subj + "EXAM")[:3]
        year = datetime.now(timezone.utc).year
        charset = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            for _ in range(100):
                suffix = "".join(secrets.choice(charset) for _ in range(3))
                candidate = f"{clean_subj}-{year}-{suffix}"
                query = self._format_query("SELECT id FROM exams WHERE exam_code = ?")
                cursor.execute(query, (candidate,))
                if not cursor.fetchone():
                    return candidate
        return f"{clean_subj}-{year}-{int(time.time()) % 10000}"

    def create_exam(
        self,
        title: str,
        subject: str = "",
        duration_minutes: int = 60,
        deadline: str = "",
        instructions: str = "",
        total_marks: Optional[float] = None,
        questions: Optional[List[Dict[str, Any]]] = None,
        created_by: Optional[int] = None,
        exam_code: Optional[str] = None,
        class_level: str = "",
        institute_name: str = "The Squire's Way"
    ) -> Dict[str, Any]:
        """Creates an exam with snapshot questions."""
        code = exam_code or self.generate_exam_slug(subject)
        q_list = questions or []
        if total_marks is None or total_marks <= 0:
            computed_total_marks = sum(float(q.get("marks", 1.0)) for q in q_list) if q_list else 0.0
        else:
            computed_total_marks = float(total_marks)

        clean_class = (class_level or "").strip()
        clean_inst = (institute_name or "The Squire's Way").strip()

        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)

            actual_created_by = None
            if created_by is not None:
                cursor.execute(self._format_query("SELECT id FROM users WHERE id = ?"), (created_by,))
                if cursor.fetchone():
                    actual_created_by = created_by

            if self.is_postgres:
                insert_q = """
                    INSERT INTO exams (exam_code, title, subject, class_level, institute_name, duration_minutes, deadline, total_marks, instructions, status, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s)
                    RETURNING id
                """
                cursor.execute(insert_q, (code, title.strip(), subject.strip(), clean_class, clean_inst, duration_minutes, deadline, computed_total_marks, instructions, actual_created_by))
                exam_id = cursor.fetchone()[0]
            else:
                insert_q = """
                    INSERT INTO exams (exam_code, title, subject, class_level, institute_name, duration_minutes, deadline, total_marks, instructions, status, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """
                cursor.execute(insert_q, (code, title.strip(), subject.strip(), clean_class, clean_inst, duration_minutes, deadline, computed_total_marks, instructions, actual_created_by))
                exam_id = cursor.lastrowid

            for idx, q in enumerate(q_list):
                q_order = q.get("question_order") or (idx + 1)
                q_id = q.get("question_id")
                q_text = q.get("question_text") or ""
                q_marks = float(q.get("marks", 1.0))
                q_sec = (q.get("section_title") or "").strip()
                if self.is_postgres:
                    q_insert = """
                        INSERT INTO exam_questions (exam_id, question_id, question_order, question_text, marks, section_title)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """
                    cursor.execute(q_insert, (exam_id, q_id, q_order, q_text, q_marks, q_sec))
                else:
                    q_insert = """
                        INSERT INTO exam_questions (exam_id, question_id, question_order, question_text, marks, section_title)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """
                    cursor.execute(q_insert, (exam_id, q_id, q_order, q_text, q_marks, q_sec))

            conn.commit()

        return self.get_exam_by_id(exam_id)

    def get_exams(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        page: int = 1
    ) -> Dict[str, Any]:
        """Lists exams with aggregated questions count and submissions count."""
        offset = max(0, (page - 1) * limit)
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            base_where = ""
            params = []
            if status:
                base_where = "WHERE e.status = ?"
                params.append(status)

            count_query = f"SELECT COUNT(*) FROM exams e {base_where}"
            cursor.execute(self._format_query(count_query), tuple(params))
            row = cursor.fetchone()
            total_count = row[0] if row else 0

            query = f"""
                SELECT e.id, e.exam_code, e.title, e.subject, e.class_level, e.institute_name,
                       e.duration_minutes, e.deadline, e.total_marks, e.instructions,
                       e.status, e.created_by, e.created_at, e.updated_at,
                       COUNT(DISTINCT eq.id) AS questions_count,
                       COUNT(DISTINCT es.id) AS submissions_count,
                       COUNT(DISTINCT CASE WHEN es.status = 'submitted' THEN es.id END) AS pending_count
                FROM exams e
                LEFT JOIN exam_questions eq ON eq.exam_id = e.id
                LEFT JOIN exam_submissions es ON es.exam_id = e.id
                {base_where}
                GROUP BY e.id
                ORDER BY e.created_at DESC
                LIMIT ? OFFSET ?
            """
            exec_params = list(params) + [limit, offset]
            cursor.execute(self._format_query(query), tuple(exec_params))
            rows = cursor.fetchall()

            exams_list = []
            for r in rows:
                keys = r.keys() if hasattr(r, "keys") else []
                exams_list.append({
                    "id": r["id"],
                    "exam_code": r["exam_code"],
                    "title": r["title"],
                    "subject": r["subject"] or "",
                    "class_level": (r["class_level"] if "class_level" in keys else "") or "",
                    "institute_name": (r["institute_name"] if "institute_name" in keys else "") or "The Squire's Way",
                    "duration_minutes": r["duration_minutes"],
                    "deadline": _iso_ts(r["deadline"]),
                    "total_marks": float(r["total_marks"]),
                    "instructions": r["instructions"] or "",
                    "status": r["status"],
                    "created_by": r["created_by"],
                    "created_at": _iso_ts(r["created_at"]),
                    "updated_at": _iso_ts(r["updated_at"]),
                    "questions_count": int(r["questions_count"]),
                    "submissions_count": int(r["submissions_count"]),
                    "pending_count": int(r["pending_count"])
                })
            return {
                "exams": exams_list,
                "total": total_count,
                "page": page,
                "limit": limit
            }

    def get_exam_by_code(self, exam_code: str, include_questions: bool = True) -> Optional[Dict[str, Any]]:
        """Retrieves an exam by unique slug code, optionally including questions."""
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            query = self._format_query("""
                SELECT id, exam_code, title, subject, class_level, institute_name, duration_minutes, deadline,
                       total_marks, instructions, status, created_by, created_at, updated_at
                FROM exams
                WHERE exam_code = ?
            """)
            cursor.execute(query, (exam_code.strip(),))
            row = cursor.fetchone()
            if not row:
                return None

            keys = row.keys() if hasattr(row, "keys") else []
            exam = {
                "id": row["id"],
                "exam_code": row["exam_code"],
                "title": row["title"],
                "subject": row["subject"] or "",
                "class_level": (row["class_level"] if "class_level" in keys else "") or "",
                "institute_name": (row["institute_name"] if "institute_name" in keys else "") or "The Squire's Way",
                "duration_minutes": row["duration_minutes"],
                "deadline": _iso_ts(row["deadline"]),
                "total_marks": float(row["total_marks"]),
                "instructions": row["instructions"] or "",
                "status": row["status"],
                "created_by": row["created_by"],
                "created_at": _iso_ts(row["created_at"]),
                "updated_at": _iso_ts(row["updated_at"]),
                "questions": []
            }

            if include_questions:
                q_query = self._format_query("""
                    SELECT id, question_id, question_order, question_text, marks, section_title
                    FROM exam_questions
                    WHERE exam_id = ?
                    ORDER BY question_order ASC
                """)
                cursor.execute(q_query, (row["id"],))
                q_rows = cursor.fetchall()
                exam["questions"] = [
                    {
                        "id": qr["id"],
                        "question_id": qr["question_id"],
                        "question_order": qr["question_order"],
                        "question_text": qr["question_text"],
                        "marks": float(qr["marks"]),
                        "section_title": (qr["section_title"] if "section_title" in (qr.keys() if hasattr(qr, "keys") else []) else "") or ""
                    }
                    for qr in q_rows
                ]
                exam["questions_count"] = len(exam["questions"])
            return exam

    def get_exam_by_id(self, exam_id: int, include_questions: bool = True) -> Optional[Dict[str, Any]]:
        """Retrieves an exam by primary key ID."""
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            query = self._format_query("""
                SELECT id, exam_code, title, subject, class_level, institute_name, duration_minutes, deadline,
                       total_marks, instructions, status, created_by, created_at, updated_at
                FROM exams
                WHERE id = ?
            """)
            cursor.execute(query, (exam_id,))
            row = cursor.fetchone()
            if not row:
                return None

            keys = row.keys() if hasattr(row, "keys") else []
            exam = {
                "id": row["id"],
                "exam_code": row["exam_code"],
                "title": row["title"],
                "subject": row["subject"] or "",
                "class_level": (row["class_level"] if "class_level" in keys else "") or "",
                "institute_name": (row["institute_name"] if "institute_name" in keys else "") or "The Squire's Way",
                "duration_minutes": row["duration_minutes"],
                "deadline": _iso_ts(row["deadline"]),
                "total_marks": float(row["total_marks"]),
                "instructions": row["instructions"] or "",
                "status": row["status"],
                "created_by": row["created_by"],
                "created_at": _iso_ts(row["created_at"]),
                "updated_at": _iso_ts(row["updated_at"]),
                "questions": []
            }

            if include_questions:
                q_query = self._format_query("""
                    SELECT id, question_id, question_order, question_text, marks, section_title
                    FROM exam_questions
                    WHERE exam_id = ?
                    ORDER BY question_order ASC
                """)
                cursor.execute(q_query, (row["id"],))
                q_rows = cursor.fetchall()
                exam["questions"] = [
                    {
                        "id": qr["id"],
                        "question_id": qr["question_id"],
                        "question_order": qr["question_order"],
                        "question_text": qr["question_text"],
                        "marks": float(qr["marks"]),
                        "section_title": (qr["section_title"] if "section_title" in (qr.keys() if hasattr(qr, "keys") else []) else "") or ""
                    }
                    for qr in q_rows
                ]
                exam["questions_count"] = len(exam["questions"])
            return exam

    def extend_exam_deadline(
        self,
        exam_id: int,
        new_deadline: str,
        reopen_if_closed: bool = False,
        duration_minutes: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Updates an exam's deadline (and optionally re-opens it or adjusts duration)."""
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            cursor.execute(self._format_query("SELECT id, status FROM exams WHERE id = ?"), (exam_id,))
            row = cursor.fetchone()
            if not row:
                return None

            updates = ["deadline = ?", "updated_at = CURRENT_TIMESTAMP"]
            params: List[Any] = [new_deadline]

            if reopen_if_closed and row["status"] != "active":
                updates.append("status = 'active'")
            if duration_minutes is not None:
                updates.append("duration_minutes = ?")
                params.append(int(duration_minutes))

            params.append(exam_id)
            cursor.execute(
                self._format_query(f"UPDATE exams SET {', '.join(updates)} WHERE id = ?"),
                params,
            )
            conn.commit()
        return self.get_exam_by_id(exam_id, include_questions=False)

    def toggle_exam_status(self, exam_id: int) -> Optional[str]:
        """Toggles an exam's status between 'active' and 'closed'."""
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            query = self._format_query("SELECT status FROM exams WHERE id = ?")
            cursor.execute(query, (exam_id,))
            row = cursor.fetchone()
            if not row:
                return None
            curr_status = row["status"]
            new_status = "closed" if curr_status == "active" else "active"
            update_query = self._format_query("""
                UPDATE exams
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """)
            cursor.execute(update_query, (new_status, exam_id))
            conn.commit()
            return new_status

    def delete_exam(self, exam_id: int) -> bool:
        """Deletes an exam and cascades deletion to questions and submissions."""
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            query = self._format_query("DELETE FROM exams WHERE id = ?")
            cursor.execute(query, (exam_id,))
            conn.commit()
            return cursor.rowcount > 0

    def create_submission(
        self,
        exam_id: int,
        student_name: str,
        roll_number: str,
        section: str = "",
        time_taken_seconds: int = 0,
        answers: Optional[List[Dict[str, Any]]] = None,
        is_emergency: bool = False,
        emergency_hash: Optional[str] = None
    ) -> Dict[str, Any]:
        """Records student submission answers with duplicate detection and emergency audit flags."""
        integrity_errors = (sqlite3.IntegrityError,)
        if PSYCOPG2_AVAILABLE:
            integrity_errors = (sqlite3.IntegrityError, psycopg2.IntegrityError)

        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            clean_name = student_name.strip()
            clean_roll = roll_number.strip().upper()
            clean_section = section.strip() if section else ""

            # Check duplicate
            check_q = self._format_query("""
                SELECT id FROM exam_submissions
                WHERE exam_id = ? AND UPPER(roll_number) = ?
            """)
            cursor.execute(check_q, (exam_id, clean_roll))
            if cursor.fetchone():
                raise ValueError(f"A submission for Roll Number '{clean_roll}' already exists for this exam.")

            try:
                if self.is_postgres:
                    sub_q = """
                        INSERT INTO exam_submissions (exam_id, student_name, roll_number, section, time_taken_seconds, status, is_emergency, emergency_hash)
                        VALUES (%s, %s, %s, %s, %s, 'submitted', %s, %s)
                        RETURNING id, submitted_at
                    """
                    cursor.execute(sub_q, (exam_id, clean_name, clean_roll, clean_section, time_taken_seconds, is_emergency, emergency_hash))
                    row = cursor.fetchone()
                    submission_id = row[0]
                    submitted_at = _iso_ts(row[1])
                else:
                    sub_q = """
                        INSERT INTO exam_submissions (exam_id, student_name, roll_number, section, time_taken_seconds, status, is_emergency, emergency_hash)
                        VALUES (?, ?, ?, ?, ?, 'submitted', ?, ?)
                    """
                    cursor.execute(sub_q, (exam_id, clean_name, clean_roll, clean_section, time_taken_seconds, int(is_emergency), emergency_hash))
                    submission_id = cursor.lastrowid
                    submitted_at = datetime.now(timezone.utc).isoformat()
            except integrity_errors:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise ValueError(f"A submission for Roll Number '{clean_roll}' already exists for this exam.")

            if answers:
                for ans in answers:
                    q_id = ans.get("question_id")
                    t_ans = ans.get("typed_answer") or ""
                    img = ans.get("image_data") or ""
                    if self.is_postgres:
                        ans_q = """
                            INSERT INTO exam_submission_answers (submission_id, question_id, typed_answer, image_data)
                            VALUES (%s, %s, %s, %s)
                        """
                        cursor.execute(ans_q, (submission_id, q_id, t_ans, img))
                    else:
                        ans_q = """
                            INSERT INTO exam_submission_answers (submission_id, question_id, typed_answer, image_data)
                            VALUES (?, ?, ?, ?)
                        """
                        cursor.execute(ans_q, (submission_id, q_id, t_ans, img))

            conn.commit()

        return {
            "submission_id": submission_id,
            "exam_id": exam_id,
            "student_name": clean_name,
            "roll_number": clean_roll,
            "section": clean_section,
            "submitted_at": submitted_at,
            "time_taken_seconds": time_taken_seconds,
            "status": "submitted",
            "is_emergency": bool(is_emergency),
            "emergency_hash": emergency_hash
        }

    def get_exam_stats(self, exam: Dict[str, Any], submissions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Computes class summary stats for an exam's submissions."""
        total_subs = len(submissions)
        graded = [s for s in submissions if s.get("status") == "graded" and s.get("total_score") is not None]
        pending_count = sum(1 for s in submissions if s.get("status") != "graded")
        total_marks = float(exam.get("total_marks") or 0.0)

        if not graded:
            return {
                "total_submissions": total_subs,
                "graded_count": 0,
                "pending_count": pending_count,
                "average_score": None,
                "average_percentage": None,
                "highest_score": None,
                "lowest_score": None,
                "pass_count": 0,
                "pass_rate": None,
            }

        scores = [float(s["total_score"]) for s in graded]
        avg_score = round(sum(scores) / len(scores), 2)
        highest = max(scores)
        lowest = min(scores)
        avg_pct = round((avg_score / total_marks) * 100, 1) if total_marks > 0 else None
        pass_count = sum(1 for sc in scores if (total_marks <= 0 or (sc / total_marks) >= 0.40))
        pass_rate = round((pass_count / len(scores)) * 100, 1)

        return {
            "total_submissions": total_subs,
            "graded_count": len(graded),
            "pending_count": pending_count,
            "average_score": avg_score,
            "average_percentage": avg_pct,
            "highest_score": highest,
            "lowest_score": lowest,
            "pass_count": pass_count,
            "pass_rate": pass_rate,
        }

    def get_submission_by_exam_and_roll(self, exam_id: int, roll_number: str) -> Optional[Dict[str, Any]]:
        """Retrieves a submission by exam ID and student roll number."""
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            clean_roll = roll_number.strip().upper()
            query = self._format_query("""
                SELECT s.id, s.exam_id, s.student_name, s.roll_number, s.section,
                       s.submitted_at, s.time_taken_seconds, s.status, s.total_score,
                       s.feedback, s.graded_at, s.is_emergency, s.emergency_hash,
                       e.title AS exam_title, e.exam_code, e.total_marks
                FROM exam_submissions s
                JOIN exams e ON e.id = s.exam_id
                WHERE s.exam_id = ? AND UPPER(s.roll_number) = ?
            """)
            cursor.execute(query, (exam_id, clean_roll))
            row = cursor.fetchone()
            if not row:
                return None

            sub_dict = {
                "id": row["id"],
                "exam_id": row["exam_id"],
                "exam_title": row["exam_title"],
                "exam_code": row["exam_code"],
                "total_marks": float(row["total_marks"]),
                "student_name": row["student_name"],
                "roll_number": row["roll_number"],
                "section": row["section"] or "",
                "submitted_at": _iso_ts(row["submitted_at"]),
                "time_taken_seconds": row["time_taken_seconds"],
                "status": row["status"],
                "is_emergency": bool(row["is_emergency"]) if "is_emergency" in row.keys() else False,
                "emergency_hash": row["emergency_hash"] if "emergency_hash" in row.keys() else None,
                "total_score": float(row["total_score"]) if row["total_score"] is not None else None,
                "percentage": round((float(row["total_score"]) / float(row["total_marks"])) * 100, 1) if (row["total_score"] is not None and row["total_marks"] > 0) else None,
                "feedback": row["feedback"] or "",
                "graded_at": _iso_ts(row["graded_at"]) if row["graded_at"] else None,
                "questions": []
            }

            ans_query = self._format_query("""
                SELECT esa.id, esa.question_id, esa.typed_answer, esa.image_data,
                       esa.marks_awarded, esa.feedback,
                       eq.question_order, eq.question_text, eq.marks AS max_marks, eq.section_title
                FROM exam_submission_answers esa
                JOIN exam_questions eq ON eq.id = esa.question_id
                WHERE esa.submission_id = ?
                ORDER BY eq.question_order ASC
            """)
            cursor.execute(ans_query, (row["id"],))
            ans_rows = cursor.fetchall()
            sub_dict["questions"] = [
                {
                    "question_id": ar["question_id"],
                    "question_order": ar["question_order"],
                    "question_text": ar["question_text"],
                    "marks": float(ar["max_marks"]),
                    "section_title": (ar["section_title"] if "section_title" in (ar.keys() if hasattr(ar, "keys") else []) else "") or "",
                    "marks_awarded": float(ar["marks_awarded"]) if ar["marks_awarded"] is not None else None,
                    "typed_answer": ar["typed_answer"] or "",
                    "image_data": ar["image_data"] or "",
                    "feedback": ar["feedback"] or ""
                }
                for ar in ans_rows
            ]
            return sub_dict

    def get_submissions_for_exam(self, exam_id: int) -> List[Dict[str, Any]]:
        """Lists all submissions for a specific exam for teacher evaluation."""
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            query = self._format_query("""
                SELECT s.id, s.exam_id, s.student_name, s.roll_number, s.section,
                       s.submitted_at, s.time_taken_seconds, s.status, s.total_score,
                       s.feedback, s.graded_at, s.is_emergency, s.emergency_hash, e.total_marks
                FROM exam_submissions s
                JOIN exams e ON e.id = s.exam_id
                WHERE s.exam_id = ?
                ORDER BY s.submitted_at DESC
            """)
            cursor.execute(query, (exam_id,))
            rows = cursor.fetchall()
            return [
                {
                    "id": r["id"],
                    "exam_id": r["exam_id"],
                    "student_name": r["student_name"],
                    "roll_number": r["roll_number"],
                    "section": r["section"] or "",
                    "submitted_at": _iso_ts(r["submitted_at"]),
                    "time_taken_seconds": r["time_taken_seconds"],
                    "status": r["status"],
                    "is_emergency": bool(r["is_emergency"]) if "is_emergency" in r.keys() else False,
                    "emergency_hash": r["emergency_hash"] if "emergency_hash" in r.keys() else None,
                    "total_score": float(r["total_score"]) if r["total_score"] is not None else None,
                    "total_marks": float(r["total_marks"]),
                    "feedback": r["feedback"] or "",
                    "graded_at": _iso_ts(r["graded_at"]) if r["graded_at"] else None
                }
                for r in rows
            ]

    def get_exam_marksheet_scores(self, exam_id: int) -> Tuple[List[Dict[str, Any]], Dict[Tuple[int, int], Optional[float]]]:
        """Returns ordered exam questions and {(submission_id, exam_question_id): marks_awarded} for CSV marksheet."""
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            cursor.execute(
                self._format_query(
                    "SELECT id, question_order, marks FROM exam_questions WHERE exam_id = ? ORDER BY question_order ASC"
                ),
                (exam_id,),
            )
            q_rows = [
                {"id": r["id"], "question_order": r["question_order"], "marks": float(r["marks"])}
                for r in cursor.fetchall()
            ]
            cursor.execute(
                self._format_query("""
                    SELECT esa.submission_id, esa.question_id, esa.marks_awarded
                    FROM exam_submission_answers esa
                    JOIN exam_submissions s ON s.id = esa.submission_id
                    WHERE s.exam_id = ?
                """),
                (exam_id,),
            )
            score_map: Dict[Tuple[int, int], Optional[float]] = {}
            for r in cursor.fetchall():
                score_map[(r["submission_id"], r["question_id"])] = (
                    float(r["marks_awarded"]) if r["marks_awarded"] is not None else None
                )
            return q_rows, score_map

    def get_submission_detail(self, submission_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves full submission details with answers for grading studio."""
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            query = self._format_query("""
                SELECT s.id, s.exam_id, s.student_name, s.roll_number, s.section,
                       s.submitted_at, s.time_taken_seconds, s.status, s.total_score,
                       s.feedback, s.graded_at, s.graded_by, s.is_emergency, s.emergency_hash,
                       e.title AS exam_title, e.exam_code, e.subject AS exam_subject, e.total_marks
                FROM exam_submissions s
                JOIN exams e ON e.id = s.exam_id
                WHERE s.id = ?
            """)
            cursor.execute(query, (submission_id,))
            row = cursor.fetchone()
            if not row:
                return None

            sub_dict = {
                "id": row["id"],
                "exam_id": row["exam_id"],
                "exam_title": row["exam_title"],
                "exam_code": row["exam_code"],
                "exam_subject": row["exam_subject"] or "",
                "total_marks": float(row["total_marks"]),
                "student_name": row["student_name"],
                "roll_number": row["roll_number"],
                "section": row["section"] or "",
                "submitted_at": _iso_ts(row["submitted_at"]),
                "time_taken_seconds": row["time_taken_seconds"],
                "status": row["status"],
                "is_emergency": bool(row["is_emergency"]) if "is_emergency" in row.keys() else False,
                "emergency_hash": row["emergency_hash"] if "emergency_hash" in row.keys() else None,
                "total_score": float(row["total_score"]) if row["total_score"] is not None else None,
                "percentage": round((float(row["total_score"]) / float(row["total_marks"])) * 100, 1) if (row["total_score"] is not None and row["total_marks"] > 0) else None,
                "feedback": row["feedback"] or "",
                "graded_by": row["graded_by"],
                "graded_at": _iso_ts(row["graded_at"]) if row["graded_at"] else None,
                "answers": []
            }

            ans_query = self._format_query("""
                SELECT esa.id, esa.question_id, esa.typed_answer, esa.image_data,
                       esa.marks_awarded, esa.feedback,
                       eq.question_order, eq.question_text, eq.marks AS max_marks, eq.section_title
                FROM exam_submission_answers esa
                JOIN exam_questions eq ON eq.id = esa.question_id
                WHERE esa.submission_id = ?
                ORDER BY eq.question_order ASC
            """)
            cursor.execute(ans_query, (submission_id,))
            ans_rows = cursor.fetchall()
            sub_dict["answers"] = [
                {
                    "id": ar["id"],
                    "question_id": ar["question_id"],
                    "question_order": ar["question_order"],
                    "question_text": ar["question_text"],
                    "max_marks": float(ar["max_marks"]),
                    "section_title": (ar["section_title"] if "section_title" in (ar.keys() if hasattr(ar, "keys") else []) else "") or "",
                    "marks_awarded": float(ar["marks_awarded"]) if ar["marks_awarded"] is not None else None,
                    "typed_answer": ar["typed_answer"] or "",
                    "image_data": ar["image_data"] or "",
                    "feedback": ar["feedback"] or ""
                }
                for ar in ans_rows
            ]
            return sub_dict

    def grade_submission(
        self,
        submission_id: int,
        grades: List[Dict[str, Any]],
        overall_feedback: str = "",
        graded_by: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Publishes teacher grading and feedback for a submission."""
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            total_awarded = 0.0

            for g in grades:
                q_id = g.get("question_id")
                marks = float(g.get("marks_awarded", 0.0))
                fb = g.get("feedback") or ""
                total_awarded += marks

                update_ans_q = self._format_query("""
                    UPDATE exam_submission_answers
                    SET marks_awarded = ?, feedback = ?
                    WHERE submission_id = ? AND question_id = ?
                """)
                cursor.execute(update_ans_q, (marks, fb, submission_id, q_id))

            actual_graded_by = None
            if graded_by is not None:
                cursor.execute(self._format_query("SELECT id FROM users WHERE id = ?"), (graded_by,))
                if cursor.fetchone():
                    actual_graded_by = graded_by

            update_sub_q = self._format_query("""
                UPDATE exam_submissions
                SET total_score = ?, feedback = ?, status = 'graded', graded_by = ?, graded_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """)
            cursor.execute(update_sub_q, (total_awarded, overall_feedback, actual_graded_by, submission_id))
            conn.commit()

        return self.get_submission_detail(submission_id)

    def export_full_backup(self) -> Dict[str, Any]:
        """Exports a complete JSON disaster recovery backup of questions, exams, and submissions."""
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)

            # 1. Questions
            cursor.execute("SELECT id, question_text, normalized_text, class_level, subject, topic, question_type, difficulty, default_marks, needs_review, review_reason, frequency, sources, created_at, updated_at FROM questions ORDER BY id ASC")
            q_rows = cursor.fetchall()
            questions = [dict(r) for r in q_rows]

            # 2. Users (sanitized without salt or sensitive tokens)
            cursor.execute("SELECT id, username, display_name, role, is_active, created_at FROM users ORDER BY id ASC")
            u_rows = cursor.fetchall()
            users = [dict(r) for r in u_rows]

            # 3. Exams
            cursor.execute("SELECT id, exam_code, title, subject, class_level, institute_name, duration_minutes, deadline, total_marks, instructions, status, created_by, created_at FROM exams ORDER BY id ASC")
            e_rows = cursor.fetchall()
            exams = [dict(r) for r in e_rows]

            # 4. Exam Questions
            cursor.execute("SELECT id, exam_id, question_id, question_order, question_text, marks, section_title, created_at FROM exam_questions ORDER BY exam_id ASC, question_order ASC")
            eq_rows = cursor.fetchall()
            exam_questions = [dict(r) for r in eq_rows]

            # 5. Exam Submissions
            cursor.execute("SELECT id, exam_id, student_name, roll_number, section, submitted_at, time_taken_seconds, status, total_score, feedback, graded_by, graded_at, created_at, is_emergency, emergency_hash FROM exam_submissions ORDER BY id ASC")
            es_rows = cursor.fetchall()
            submissions = [dict(r) for r in es_rows]

            # 6. Submission Answers
            cursor.execute("SELECT id, submission_id, question_id, typed_answer, image_data, marks_awarded, feedback, created_at FROM exam_submission_answers ORDER BY submission_id ASC, id ASC")
            esa_rows = cursor.fetchall()
            answers = [dict(r) for r in esa_rows]

            def sanitize_record(d):
                clean = {}
                for k, v in d.items():
                    if isinstance(v, datetime):
                        clean[k] = v.isoformat()
                    elif v is not None and not isinstance(v, (str, int, float, bool, list, dict)):
                        clean[k] = str(v)
                    else:
                        clean[k] = v
                return clean

            return {
                "backup_version": "3.5.0",
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "counts": {
                    "questions": len(questions),
                    "users": len(users),
                    "exams": len(exams),
                    "exam_questions": len(exam_questions),
                    "submissions": len(submissions),
                    "answers": len(answers)
                },
                "data": {
                    "questions": [sanitize_record(q) for q in questions],
                    "users": [sanitize_record(u) for u in users],
                    "exams": [sanitize_record(e) for e in exams],
                    "exam_questions": [sanitize_record(eq) for eq in exam_questions],
                    "submissions": [sanitize_record(s) for s in submissions],
                    "answers": [sanitize_record(a) for a in answers]
                }
            }
