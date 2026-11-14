import os
import re
import json
import sqlite3
from typing import List, Dict, Any, Optional, Tuple
from contextlib import contextmanager

try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False


class Database:
    def __init__(self, db_url_or_path: Optional[str] = None):
        target = db_url_or_path or os.environ.get("DATABASE_URL") or os.environ.get("QUESTION_BANK_DB", "questions.db")
        
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
        else:
            self.is_postgres = False
            self.db_url = None
            self.db_path = target
            
        self.init_db()

    @contextmanager
    def get_connection(self):
        """Context manager providing a database connection with auto-closing and dictionary row access."""
        if self.is_postgres:
            conn = psycopg2.connect(self.db_url)
            try:
                yield conn
            finally:
                conn.close()
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
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_questions_normalized ON questions(normalized_text);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_questions_subject ON questions(subject);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_questions_topic ON questions(topic);")
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
            return cursor.rowcount > 0

    def delete_question(self, question_id: int) -> bool:
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            query = self._format_query("DELETE FROM questions WHERE id = ?")
            cursor.execute(query, (question_id,))
            conn.commit()
            return cursor.rowcount > 0

    def delete_questions(self, question_ids: List[int]) -> int:
        if not question_ids:
            return 0
        with self.get_connection() as conn:
            cursor = self._get_cursor(conn)
            placeholders = ",".join("?" for _ in question_ids)
            query = self._format_query(f"DELETE FROM questions WHERE id IN ({placeholders})")
            cursor.execute(query, question_ids)
            conn.commit()
            return cursor.rowcount

    def get_metadata(self) -> Dict[str, Any]:
        """Returns distinct subjects, topics, and source files along with high-level stats."""
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

            return {
                "total_unique": unique_count,
                "total_occurrences": total_occurrences,
                "merged_duplicates": merged_count,
                "subjects": subjects,
                "topics": topics,
                "sources": sorted(list(all_sources)),
                "is_postgres": self.is_postgres
            }

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

        return {
            "restored": restored,
            "merged": merged,
            "skipped": skipped,
            "total": len(questions_data)
        }
