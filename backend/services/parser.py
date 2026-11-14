import io
import re
from typing import List, BinaryIO
from docx import Document
from pypdf import PdfReader
from backend.services.dedup import clean_question_text, QUESTION_PREFIX_PATTERNS

HEADER_REGEX = re.compile(
    r"^(?:section|part|class|time|marks|maximum marks|max marks|roll no|instructions|date|subject|page|index|total marks|all questions|semester|mid term|annual examination)\b",
    re.IGNORECASE
)

QUESTION_STEMS = re.compile(
    r"^(?:what|why|how|explain|define|describe|state|calculate|distinguish|compare|differentiate|prove|show|find|write|discuss|evaluate|identify|list|name|give|mention|illustrate|outline)\b",
    re.IGNORECASE
)

def matches_question_prefix(text: str) -> bool:
    """Checks if a string begins with any recognized numbering or question prefix pattern."""
    for pattern in QUESTION_PREFIX_PATTERNS:
        if pattern.match(text):
            return True
    return False

def extract_questions_from_lines(lines: List[str]) -> List[str]:
    """
    Groups lines into discrete questions based on numbering and prefixes.
    Handles questions spanning multiple lines.
    If no numbered questions are found, falls back to paragraph extraction.
    """
    questions: List[str] = []
    current_q_lines: List[str] = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        if matches_question_prefix(line):
            # Finish previous question
            if current_q_lines:
                full_text = " ".join(current_q_lines).strip()
                cleaned = clean_question_text(full_text)
                if cleaned:
                    questions.append(cleaned)
                current_q_lines = []

            # Clean and start new question
            cleaned_start = clean_question_text(line)
            if cleaned_start:
                current_q_lines.append(cleaned_start)
        else:
            # Continuation of existing question if open
            if current_q_lines:
                current_q_lines.append(line)

    # Append trailing question
    if current_q_lines:
        full_text = " ".join(current_q_lines).strip()
        cleaned = clean_question_text(full_text)
        if cleaned:
            questions.append(cleaned)

    # Fallback: If 0 numbered questions were found, extract sensible question paragraphs
    if not questions:
        questions = fallback_extract_questions(lines)

    return questions

def fallback_extract_questions(lines: List[str]) -> List[str]:
    """
    Intelligent fallback for unnumbered documents:
    Extracts standalone paragraphs that are likely questions (ends with '?', starts with question stems, or substantial text).
    Excludes headers/instructions.
    """
    extracted: List[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or len(line) < 6:
            continue

        # Skip obvious headers/metadata
        if HEADER_REGEX.match(line):
            continue

        cleaned = clean_question_text(line)
        if not cleaned:
            continue

        # Match question characteristics
        if (
            cleaned.endswith("?")
            or QUESTION_STEMS.match(cleaned)
            or (len(cleaned) >= 15 and not cleaned.endswith(":"))
        ):
            extracted.append(cleaned)

    return extracted

def extract_questions_from_docx(file_stream: BinaryIO) -> List[str]:
    """
    Extracts plain text questions from a Word (.docx) file stream.
    Supports:
    - Numbered paragraphs (1., Q1., etc.)
    - Word native list styling (<w:numPr> / 'List Number')
    - Tables (exam questions formatted inside table cells)
    - Fallback for unnumbered question documents
    """
    doc = Document(file_stream)
    lines: List[str] = []
    native_list_questions: List[str] = []

    # 1. Process document paragraphs
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        # Check if Word native bullet or numbered list
        is_native_list = (
            "list" in para.style.name.lower()
            or bool(para._element.xpath(".//w:numPr"))
        )

        if is_native_list:
            cleaned = clean_question_text(text)
            if cleaned and not HEADER_REGEX.match(cleaned):
                native_list_questions.append(cleaned)
        else:
            lines.append(text)

    # 2. Process document tables (common in question papers)
    table_questions: List[str] = []
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if not cells:
                continue

            # Skip header row (e.g. S.No, Question, Marks)
            first_cell = cells[0].lower()
            if any(h in first_cell for h in ["q.no", "s.no", "sr.no", "sl.no", "question", "marks"]):
                continue

            # In a multi-column table row, the longest cell is typically the question text
            question_candidate = max(cells, key=len)
            cleaned = clean_question_text(question_candidate)
            if cleaned and len(cleaned) >= 6 and not HEADER_REGEX.match(cleaned):
                table_questions.append(cleaned)

    # Decide extraction source priority
    # If standard line extraction with numbers yields questions, use it
    extracted_from_lines = extract_questions_from_lines(lines) if lines else []

    results = []
    if extracted_from_lines:
        results.extend(extracted_from_lines)
    if native_list_questions:
        results.extend(native_list_questions)
    if table_questions:
        results.extend(table_questions)

    # If nothing was extracted yet, try fallback across all lines
    if not results and lines:
        results = fallback_extract_questions(lines)

    # Remove duplicates within the same extracted file while preserving order
    seen = set()
    unique_results = []
    for q in results:
        norm = q.lower().strip()
        if norm not in seen:
            seen.add(norm)
            unique_results.append(q)

    return unique_results

def extract_questions_from_pdf(file_stream: BinaryIO) -> List[str]:
    """
    Extracts plain text questions from a PDF (.pdf) file stream.
    """
    reader = PdfReader(file_stream)
    all_lines: List[str] = []

    for page in reader.pages:
        page_text = page.extract_text() or ""
        for raw_line in page_text.splitlines():
            line = raw_line.strip()
            if line:
                all_lines.append(line)

    return extract_questions_from_lines(all_lines)

def extract_questions_from_file(filename: str, file_bytes: bytes) -> List[str]:
    """
    Dispatches file parsing based on extension (.docx or .pdf).
    """
    lower_name = filename.lower()
    stream = io.BytesIO(file_bytes)

    if lower_name.endswith(".docx"):
        return extract_questions_from_docx(stream)
    elif lower_name.endswith(".pdf"):
        return extract_questions_from_pdf(stream)
    else:
        raise ValueError(f"Unsupported file format '{filename}'. Only .docx and .pdf files are supported.")
