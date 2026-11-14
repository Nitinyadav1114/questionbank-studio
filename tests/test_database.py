import os
import pytest
import tempfile
import gc
from backend.database import Database

def test_backup_and_restore():
    fd, temp_db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    try:
        db = Database(temp_db_path)
        
        # Insert a few questions
        q1_id, _ = db.upsert_question("What is photosynthesis?", "what is photosynthesis", "Biology", "Plants", "exam1.docx")
        q2_id, _ = db.upsert_question("State Newton's second law of motion.", "state newtons second law of motion", "Physics", "Mechanics", "exam2.docx")
        
        # Export backup
        backup_data = db.get_all_questions_for_backup()
        assert len(backup_data) == 2
        assert any(q["question_text"] == "What is photosynthesis?" for q in backup_data)
        assert any(q["question_text"] == "State Newton's second law of motion." for q in backup_data)
        
        # Test restore into a separate new database
        fd2, temp_db2_path = tempfile.mkstemp(suffix=".db")
        os.close(fd2)
        try:
            db2 = Database(temp_db2_path)
            res = db2.restore_questions_from_backup(backup_data)
            assert res["restored"] == 2
            assert res["skipped"] == 0
            
            # Verify restored questions in db2
            restored = db2.get_questions()
            assert restored["total"] == 2
            
            # Re-restoring should merge as duplicates
            res2 = db2.restore_questions_from_backup(backup_data)
            assert res2["merged"] == 2
            assert res2["restored"] == 0
            
            meta = db2.get_metadata()
            assert meta["total_unique"] == 2
            assert meta["total_occurrences"] == 4
            assert meta["merged_duplicates"] == 2
        finally:
            del db2
            gc.collect()
            try:
                os.remove(temp_db2_path)
            except PermissionError:
                pass
                
    finally:
        del db
        gc.collect()
        try:
            os.remove(temp_db_path)
        except PermissionError:
            pass
