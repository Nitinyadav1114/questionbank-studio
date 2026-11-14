import io
import pytest
from docx import Document
from backend.services.dedup import clean_question_text, normalize_question_text
from backend.services.parser import (
    extract_questions_from_lines,
    extract_questions_from_docx,
    extract_questions_from_file
)

def test_clean_question_text_patterns():
    # Various serial numbering formats
    assert clean_question_text("1. What is momentum?") == "What is momentum?"
    assert clean_question_text("2) Define velocity.") == "Define velocity."
    assert clean_question_text("3: State Ohm's law.") == "State Ohm's law."
    assert clean_question_text("Q4. Explain gravity.") == "Explain gravity."
    assert clean_question_text("Question 5: Describe chloroplasts.") == "Describe chloroplasts."
    assert clean_question_text("(6) Calculate the kinetic energy.") == "Calculate the kinetic energy."
    assert clean_question_text("Q.7 What is acceleration?") == "What is acceleration?"
    assert clean_question_text("[8] State Pascal's law.") == "State Pascal's law."
    assert clean_question_text("i. Roman numeral question.") == "Roman numeral question."
    assert clean_question_text("(ii) Second roman question.") == "Second roman question."
    assert clean_question_text("• Bullet question.") == "Bullet question."

def test_extract_questions_from_lines_multiline():
    lines = [
        "Welcome to the Physics Mid-Term Examination",
        "Instructions: Answer all questions.",
        "1. What is Newton's first law of motion?",
        "Provide two real-world examples.",
        "2. Define inertia and explain how mass affects it.",
        "3. A car accelerates from rest at 2 m/s^2.",
        "Calculate the velocity after 5 seconds.",
        "Also find the total distance traveled."
    ]

    questions = extract_questions_from_lines(lines)
    assert len(questions) == 3
    assert questions[0] == "What is Newton's first law of motion? Provide two real-world examples."
    assert questions[1] == "Define inertia and explain how mass affects it."
    assert questions[2] == "A car accelerates from rest at 2 m/s^2. Calculate the velocity after 5 seconds. Also find the total distance traveled."

def test_extract_from_docx_standard():
    doc = Document()
    doc.add_heading("Chemistry Final Paper", level=1)
    doc.add_paragraph("1. What is an exothermic reaction?")
    doc.add_paragraph("2. Write the chemical formula for water.")
    doc.add_paragraph("3. Balance the equation: H2 + O2 -> H2O.")

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)

    extracted = extract_questions_from_file("chem_test.docx", buf.getvalue())
    assert len(extracted) == 3
    assert extracted[0] == "What is an exothermic reaction?"
    assert extracted[1] == "Write the chemical formula for water."
    assert extracted[2] == "Balance the equation: H2 + O2 -> H2O."

def test_extract_from_docx_native_list():
    # Test Word document created using Word's List Number feature
    doc = Document()
    doc.add_paragraph("What is speed?", style="List Number")
    doc.add_paragraph("Explain the theory of relativity.", style="List Number")

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)

    extracted = extract_questions_from_docx(buf)
    assert len(extracted) == 2
    assert "What is speed?" in extracted
    assert "Explain the theory of relativity." in extracted

def test_extract_from_docx_tables():
    # Test question bank formatted inside a table
    doc = Document()
    table = doc.add_table(rows=3, cols=3)
    # Header
    table.rows[0].cells[0].text = "S.No"
    table.rows[0].cells[1].text = "Question Description"
    table.rows[0].cells[2].text = "Marks"
    # Row 1
    table.rows[1].cells[0].text = "1"
    table.rows[1].cells[1].text = "Define kinetic energy."
    table.rows[1].cells[2].text = "5"
    # Row 2
    table.rows[2].cells[0].text = "2"
    table.rows[2].cells[1].text = "State Archimedes principle."
    table.rows[2].cells[2].text = "3"

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)

    extracted = extract_questions_from_docx(buf)
    assert len(extracted) == 2
    assert "Define kinetic energy." in extracted
    assert "State Archimedes principle." in extracted

def test_extract_from_docx_unumbered_fallback():
    # Test question bank with plain unnumbered questions
    doc = Document()
    doc.add_paragraph("Section A: General Questions")
    doc.add_paragraph("Total Marks: 100")
    doc.add_paragraph("What is the principle of conservation of momentum?")
    doc.add_paragraph("Explain the difference between mass and weight.")

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)

    extracted = extract_questions_from_docx(buf)
    assert len(extracted) == 2
    assert "What is the principle of conservation of momentum?" in extracted
    assert "Explain the difference between mass and weight." in extracted
