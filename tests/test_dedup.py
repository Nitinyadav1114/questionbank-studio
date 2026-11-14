import os
import gc
import tempfile
import pytest
from backend.database import Database
from backend.services.dedup import clean_question_text, normalize_question_text

def test_normalization():
    q1 = "1. What is Photosynthesis?"
    q2 = "Q.5 What is photosynthesis."
    q3 = "what is photosynthesis"

    assert normalize_question_text(q1) == "what is photosynthesis"
    assert normalize_question_text(q2) == "what is photosynthesis"
    assert normalize_question_text(q3) == "what is photosynthesis"

def test_database_upsert_exact_dedup():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    try:
        db = Database(db_path)

        # 1. Insert first question from 2021 exam
        raw_1 = "1. Explain the theory of relativity."
        clean_1 = clean_question_text(raw_1)
        norm_1 = normalize_question_text(clean_1)

        qid1, is_merged1 = db.upsert_question(
            question_text=clean_1,
            normalized_text=norm_1,
            subject="Physics",
            topic="Relativity",
            source_filename="Physics_2021.docx"
        )
        assert is_merged1 is False

        # Verify initial state
        q_data = db.get_questions_by_ids([qid1])[0]
        assert q_data["frequency"] == 1
        assert q_data["sources"] == ["Physics_2021.docx"]

        # 2. Insert same question from 2023 exam with different number
        raw_2 = "4. Explain the theory of relativity."
        clean_2 = clean_question_text(raw_2)
        norm_2 = normalize_question_text(clean_2)

        qid2, is_merged2 = db.upsert_question(
            question_text=clean_2,
            normalized_text=norm_2,
            subject="Physics",
            topic="Relativity",
            source_filename="Physics_2023.docx"
        )
        assert is_merged2 is True
        assert qid2 == qid1 # Same record ID merged!

        # Verify merged state
        q_data_updated = db.get_questions_by_ids([qid1])[0]
        assert q_data_updated["frequency"] == 2
        assert "Physics_2021.docx" in q_data_updated["sources"]
        assert "Physics_2023.docx" in q_data_updated["sources"]

        # 3. Insert different question
        raw_3 = "2. State Ohm's law."
        clean_3 = clean_question_text(raw_3)
        norm_3 = normalize_question_text(clean_3)

        qid3, is_merged3 = db.upsert_question(
            question_text=clean_3,
            normalized_text=norm_3,
            subject="Physics",
            topic="Electricity",
            source_filename="Physics_2021.docx"
        )
        assert is_merged3 is False
        assert qid3 != qid1

        # Check metadata
        meta = db.get_metadata()
        assert meta["total_unique"] == 2
        assert meta["total_occurrences"] == 3
        assert meta["merged_duplicates"] == 1
        assert "Physics" in meta["subjects"]

    finally:
        del db
        gc.collect()
        try:
            if os.path.exists(db_path):
                os.remove(db_path)
        except PermissionError:
            pass
