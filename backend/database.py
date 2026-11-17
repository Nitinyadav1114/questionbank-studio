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
                self.pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=self.db_url)
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
        """Context manager providing a database connection with auto-closing and dictionary row access."""
        if self.is_postgres:
            conn = None
            try:
                if self.pool is not None:
                    conn = self.pool.getconn()
                    # Check if connection is still healthy; if closed or broken, recreate
                    if getattr(conn, "closed", 1) != 0:
                        try:
                            self.pool.putconn(conn, close=True)
                        except Exception:
                            pass
                        conn = psycopg2.connect(self.db_url)
                else:
                    conn = psycopg2.connect(self.db_url)
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
                    if self.pool is not None:
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
            conn = sqlite3.connect(self.db_path)
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
            conn.commit()

    def upsert_question(
        self,
        question_text: str,
        normalized_text: str,
        subject: str = "",
        topic: str = "",
        source_filename: str = ""
    ) -> Tuple[int, bool]:
        """
        Inserts a new question or merges if exact normalized match exists.
        Returns: (question_id, is_merged)
        """
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            query = self._format_query(
                "SELECT id, frequency, sources, subject, topic FROM questions WHERE normalized_text = ?"
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

                update_query = self._format_query("""
                    UPDATE questions
                    SET frequency = ?,
                        sources = ?,
                        subject = ?,
                        topic = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """)
                cursor.execute(update_query, (current_freq + 1, json.dumps(sources_list), new_subject, new_topic, question_id))
                conn.commit()
                self.invalidate_metadata_cache()
                return question_id, True
            else:
                sources_list = [source_filename] if source_filename else []
                insert_query = self._format_query("""
                    INSERT INTO questions (question_text, normalized_text, subject, topic, frequency, sources)
                    VALUES (?, ?, ?, ?, 1, ?)
                    RETURNING id
                """)
                cursor.execute(insert_query, (question_text, normalized_text, subject, topic, json.dumps(sources_list)))
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
        page: int = 1,
        limit: int = 50
    ) -> Dict[str, Any]:
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            query_parts = ["1=1"]
            params: List[Any] = []

            if search and search.strip():
                if self.is_postgres:
                    query_parts.append("(question_text ILIKE ? OR normalized_text ILIKE ?)")
                else:
                    query_parts.append("(question_text LIKE ? OR normalized_text LIKE ?)")
                search_param = f"%{search.strip()}%"
                params.extend([search_param, search_param])

            if subject and subject.strip():
                query_parts.append("LOWER(subject) = LOWER(?)")
                params.append(subject.strip())

            if topic and topic.strip():
                query_parts.append("LOWER(topic) = LOWER(?)")
                params.append(topic.strip())

            if source and source.strip():
                query_parts.append("sources LIKE ?")
                params.append(f"%{source.strip()}%")

            where_clause = " AND ".join(query_parts)

            count_query = self._format_query(f"SELECT COUNT(*) FROM questions WHERE {where_clause}")
            cursor.execute(count_query, params)
            total = cursor.fetchone()[0]

            offset = max(0, (page - 1) * limit)
            select_query = self._format_query(f"""
                SELECT id, question_text, subject, topic, frequency, sources, created_at, updated_at
                FROM questions
                WHERE {where_clause}
                ORDER BY updated_at DESC, id DESC
                LIMIT ? OFFSET ?
            """)
            cursor.execute(select_query, params + [limit, offset])

            rows = cursor.fetchall()
            items = []
            for r in rows:
                try:
                    srcs = json.loads(r["sources"]) if r["sources"] else []
                except Exception:
                    srcs = []
                items.append({
                    "id": r["id"],
                    "question_text": r["question_text"],
                    "subject": r["subject"] or "",
                    "topic": r["topic"] or "",
                    "frequency": r["frequency"] or 1,
                    "sources": srcs,
                    "created_at": str(r["created_at"]),
                    "updated_at": str(r["updated_at"])
                })

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
                SELECT id, question_text, subject, topic, frequency, sources, created_at, updated_at
                FROM questions
                WHERE id IN ({placeholders})
            """)
            cursor.execute(query, question_ids)
            rows = cursor.fetchall()
            q_map = {}
            for r in rows:
                try:
                    srcs = json.loads(r["sources"]) if r["sources"] else []
                except Exception:
                    srcs = []
                q_map[r["id"]] = {
                    "id": r["id"],
                    "question_text": r["question_text"],
                    "subject": r["subject"] or "",
                    "topic": r["topic"] or "",
                    "frequency": r["frequency"] or 1,
                    "sources": srcs,
                    "created_at": str(r["created_at"]),
                    "updated_at": str(r["updated_at"])
                }

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
        topic: Optional[str] = None
    ) -> bool:
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
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

            params.append(question_id)
            query = self._format_query(f"UPDATE questions SET {', '.join(updates)} WHERE id = ?")
            cursor.execute(query, params)
            conn.commit()
            if cursor.rowcount > 0:
                self.invalidate_metadata_cache()
                return True
            return False

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
        """Returns distinct subjects, topics, and source files along with high-level stats, using in-memory caching."""
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

            cursor.execute("SELECT DISTINCT subject FROM questions WHERE subject != '' AND subject IS NOT NULL ORDER BY subject ASC")
            subjects = [r[0] for r in cursor.fetchall()]

            cursor.execute("SELECT DISTINCT topic FROM questions WHERE topic != '' AND topic IS NOT NULL ORDER BY topic ASC")
            topics = [r[0] for r in cursor.fetchall()]

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
                "subjects": subjects,
                "topics": topics,
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
                SELECT id, question_text, normalized_text, subject, topic, frequency, sources, created_at, updated_at
                FROM questions
                ORDER BY id ASC
            """)
            rows = cursor.fetchall()
            items = []
            for r in rows:
                try:
                    srcs = json.loads(r["sources"]) if r["sources"] else []
                except Exception:
                    srcs = []
                items.append({
                    "id": r["id"],
                    "question_text": r["question_text"],
                    "normalized_text": r["normalized_text"],
                    "subject": r["subject"] or "",
                    "topic": r["topic"] or "",
                    "frequency": r["frequency"] or 1,
                    "sources": srcs,
                    "created_at": str(r["created_at"]),
                    "updated_at": str(r["updated_at"])
                })
            return items

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

                subject = q.get("subject", "").strip() if q.get("subject") else ""
                topic = q.get("topic", "").strip() if q.get("topic") else ""
                sources = q.get("sources", [])
                source_name = sources[0] if isinstance(sources, list) and sources else "Backup Import"

                query = self._format_query(
                    "SELECT id, frequency, sources, subject, topic FROM questions WHERE normalized_text = ?"
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

                    update_query = self._format_query("""
                        UPDATE questions
                        SET frequency = ?,
                            sources = ?,
                            subject = ?,
                            topic = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """)
                    cursor.execute(update_query, (current_freq + 1, json.dumps(sources_list), new_subject, new_topic, question_id))
                    merged += 1
                else:
                    sources_list = [source_name] if source_name else []
                    insert_query = self._format_query("""
                        INSERT INTO questions (question_text, normalized_text, subject, topic, frequency, sources)
                        VALUES (?, ?, ?, ?, 1, ?)
                    """)
                    cursor.execute(insert_query, (cleaned, norm_text, subject, topic, json.dumps(sources_list)))
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
        exam_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """Creates an exam with snapshot questions."""
        code = exam_code or self.generate_exam_slug(subject)
        q_list = questions or []
        if total_marks is None or total_marks <= 0:
            computed_total_marks = sum(float(q.get("marks", 1.0)) for q in q_list) if q_list else 0.0
        else:
            computed_total_marks = float(total_marks)

        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)

            actual_created_by = None
            if created_by is not None:
                cursor.execute(self._format_query("SELECT id FROM users WHERE id = ?"), (created_by,))
                if cursor.fetchone():
                    actual_created_by = created_by

            if self.is_postgres:
                insert_q = """
                    INSERT INTO exams (exam_code, title, subject, duration_minutes, deadline, total_marks, instructions, status, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'active', %s)
                    RETURNING id
                """
                cursor.execute(insert_q, (code, title.strip(), subject.strip(), duration_minutes, deadline, computed_total_marks, instructions, actual_created_by))
                exam_id = cursor.fetchone()[0]
            else:
                insert_q = """
                    INSERT INTO exams (exam_code, title, subject, duration_minutes, deadline, total_marks, instructions, status, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """
                cursor.execute(insert_q, (code, title.strip(), subject.strip(), duration_minutes, deadline, computed_total_marks, instructions, actual_created_by))
                exam_id = cursor.lastrowid

            for idx, q in enumerate(q_list):
                q_order = q.get("question_order") or (idx + 1)
                q_id = q.get("question_id")
                q_text = q.get("question_text") or ""
                q_marks = float(q.get("marks", 1.0))
                if self.is_postgres:
                    q_insert = """
                        INSERT INTO exam_questions (exam_id, question_id, question_order, question_text, marks)
                        VALUES (%s, %s, %s, %s, %s)
                    """
                    cursor.execute(q_insert, (exam_id, q_id, q_order, q_text, q_marks))
                else:
                    q_insert = """
                        INSERT INTO exam_questions (exam_id, question_id, question_order, question_text, marks)
                        VALUES (?, ?, ?, ?, ?)
                    """
                    cursor.execute(q_insert, (exam_id, q_id, q_order, q_text, q_marks))

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
                SELECT e.id, e.exam_code, e.title, e.subject, e.duration_minutes, e.deadline,
                       e.total_marks, e.instructions, e.status, e.created_by, e.created_at, e.updated_at,
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
                exams_list.append({
                    "id": r["id"],
                    "exam_code": r["exam_code"],
                    "title": r["title"],
                    "subject": r["subject"] or "",
                    "duration_minutes": r["duration_minutes"],
                    "deadline": str(r["deadline"]),
                    "total_marks": float(r["total_marks"]),
                    "instructions": r["instructions"] or "",
                    "status": r["status"],
                    "created_by": r["created_by"],
                    "created_at": str(r["created_at"]),
                    "updated_at": str(r["updated_at"]),
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
                SELECT id, exam_code, title, subject, duration_minutes, deadline,
                       total_marks, instructions, status, created_by, created_at, updated_at
                FROM exams
                WHERE exam_code = ?
            """)
            cursor.execute(query, (exam_code.strip(),))
            row = cursor.fetchone()
            if not row:
                return None

            exam = {
                "id": row["id"],
                "exam_code": row["exam_code"],
                "title": row["title"],
                "subject": row["subject"] or "",
                "duration_minutes": row["duration_minutes"],
                "deadline": str(row["deadline"]),
                "total_marks": float(row["total_marks"]),
                "instructions": row["instructions"] or "",
                "status": row["status"],
                "created_by": row["created_by"],
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
                "questions": []
            }

            if include_questions:
                q_query = self._format_query("""
                    SELECT id, question_id, question_order, question_text, marks
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
                        "marks": float(qr["marks"])
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
                SELECT id, exam_code, title, subject, duration_minutes, deadline,
                       total_marks, instructions, status, created_by, created_at, updated_at
                FROM exams
                WHERE id = ?
            """)
            cursor.execute(query, (exam_id,))
            row = cursor.fetchone()
            if not row:
                return None

            exam = {
                "id": row["id"],
                "exam_code": row["exam_code"],
                "title": row["title"],
                "subject": row["subject"] or "",
                "duration_minutes": row["duration_minutes"],
                "deadline": str(row["deadline"]),
                "total_marks": float(row["total_marks"]),
                "instructions": row["instructions"] or "",
                "status": row["status"],
                "created_by": row["created_by"],
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
                "questions": []
            }

            if include_questions:
                q_query = self._format_query("""
                    SELECT id, question_id, question_order, question_text, marks
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
                        "marks": float(qr["marks"])
                    }
                    for qr in q_rows
                ]
                exam["questions_count"] = len(exam["questions"])
            return exam

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
        answers: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Records student submission answers with duplicate detection."""
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

            if self.is_postgres:
                sub_q = """
                    INSERT INTO exam_submissions (exam_id, student_name, roll_number, section, time_taken_seconds, status)
                    VALUES (%s, %s, %s, %s, %s, 'submitted')
                    RETURNING id, submitted_at
                """
                cursor.execute(sub_q, (exam_id, clean_name, clean_roll, clean_section, time_taken_seconds))
                row = cursor.fetchone()
                submission_id = row[0]
                submitted_at = str(row[1])
            else:
                sub_q = """
                    INSERT INTO exam_submissions (exam_id, student_name, roll_number, section, time_taken_seconds, status)
                    VALUES (?, ?, ?, ?, ?, 'submitted')
                """
                cursor.execute(sub_q, (exam_id, clean_name, clean_roll, clean_section, time_taken_seconds))
                submission_id = cursor.lastrowid
                submitted_at = datetime.now(timezone.utc).isoformat()

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
            "status": "submitted"
        }

    def get_submission_by_exam_and_roll(self, exam_id: int, roll_number: str) -> Optional[Dict[str, Any]]:
        """Retrieves a submission by exam ID and student roll number."""
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            clean_roll = roll_number.strip().upper()
            query = self._format_query("""
                SELECT s.id, s.exam_id, s.student_name, s.roll_number, s.section,
                       s.submitted_at, s.time_taken_seconds, s.status, s.total_score,
                       s.feedback, s.graded_at, e.title AS exam_title, e.exam_code, e.total_marks
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
                "submitted_at": str(row["submitted_at"]),
                "time_taken_seconds": row["time_taken_seconds"],
                "status": row["status"],
                "total_score": float(row["total_score"]) if row["total_score"] is not None else None,
                "percentage": round((float(row["total_score"]) / float(row["total_marks"])) * 100, 1) if (row["total_score"] is not None and row["total_marks"] > 0) else None,
                "feedback": row["feedback"] or "",
                "graded_at": str(row["graded_at"]) if row["graded_at"] else None,
                "questions": []
            }

            ans_query = self._format_query("""
                SELECT esa.id, esa.question_id, esa.typed_answer, esa.image_data,
                       esa.marks_awarded, esa.feedback,
                       eq.question_order, eq.question_text, eq.marks AS max_marks
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
                       s.feedback, s.graded_at, e.total_marks
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
                    "submitted_at": str(r["submitted_at"]),
                    "time_taken_seconds": r["time_taken_seconds"],
                    "status": r["status"],
                    "total_score": float(r["total_score"]) if r["total_score"] is not None else None,
                    "total_marks": float(r["total_marks"]),
                    "feedback": r["feedback"] or "",
                    "graded_at": str(r["graded_at"]) if r["graded_at"] else None
                }
                for r in rows
            ]

    def get_submission_detail(self, submission_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves full submission details with answers for grading studio."""
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            query = self._format_query("""
                SELECT s.id, s.exam_id, s.student_name, s.roll_number, s.section,
                       s.submitted_at, s.time_taken_seconds, s.status, s.total_score,
                       s.feedback, s.graded_at, s.graded_by,
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
                "submitted_at": str(row["submitted_at"]),
                "time_taken_seconds": row["time_taken_seconds"],
                "status": row["status"],
                "total_score": float(row["total_score"]) if row["total_score"] is not None else None,
                "percentage": round((float(row["total_score"]) / float(row["total_marks"])) * 100, 1) if (row["total_score"] is not None and row["total_marks"] > 0) else None,
                "feedback": row["feedback"] or "",
                "graded_by": row["graded_by"],
                "graded_at": str(row["graded_at"]) if row["graded_at"] else None,
                "answers": []
            }

            ans_query = self._format_query("""
                SELECT esa.id, esa.question_id, esa.typed_answer, esa.image_data,
                       esa.marks_awarded, esa.feedback,
                       eq.question_order, eq.question_text, eq.marks AS max_marks
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
