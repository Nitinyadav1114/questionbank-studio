import io
import re
from typing import Any, BinaryIO, Dict, List, Optional, Tuple
from docx import Document
from pypdf import PdfReader

from backend.services.dedup import (
    QUESTION_PREFIX_PATTERNS,
    clean_question_text,
    extract_trailing_marks,
    is_pure_divider,
    normalize_question_text,
    normalize_quotes_and_chars,
    split_or_questions,
    strip_attached_footers,
    strip_trailing_markers,
    strip_trailing_or,
)
from backend.services.curator import (
    extract_context_from_marker,
    infer_question_metadata,
)

HEADER_REGEX = re.compile(
    r"^(?:section|part|class|time|marks|maximum marks|max marks|roll no|instructions|date|subject|page|index|total marks|all questions|semester|mid term|annual examination)\b",
    re.IGNORECASE,
)

QUESTION_STEMS = re.compile(
    r"^(?:what|why|how|explain|define|describe|state|calculate|distinguish|compare|differentiate|prove|show|find|write|discuss|evaluate|identify|list|name|give|mention|illustrate|outline|draw|justify|highlight|narrate|comment|imagine|draft)\b",
    re.IGNORECASE,
)

STANDALONE_OR_RE = re.compile(r"^\s*OR\s*$")


def matches_question_prefix(text: str) -> bool:
    """Checks if a string begins with any recognized numbering or question prefix pattern."""
    for pattern in QUESTION_PREFIX_PATTERNS:
        if pattern.match(text):
            return True
    return False


def _finalize_raw_question(
    raw_block: str,
    context_state: Dict[str, str],
    sources: List[str],
    default_subject: str = "",
    default_topic: str = "",
    default_class: str = "",
) -> Tuple[List[Dict[str, Any]], Dict[str, str], int]:
    """
    Sanitizes a single assembled raw question block, splits OR-joined questions,
    strips trailing Lesson/Book markers (returning next_ctx updates), and infers metadata.
    Returns: (items_list, next_context_updates, dropped_count)
    """
    dropped = 0
    text = normalize_quotes_and_chars(raw_block)
    text = strip_attached_footers(text)
    if text != normalize_quotes_and_chars(raw_block).strip():
        f_ctx = extract_context_from_marker(raw_block)
        for k in ("class_level", "subject"):
            if f_ctx.get(k):
                context_state[k] = f_ctx[k]

    is_div, div_text = is_pure_divider(text)
    if is_div:
        d_ctx = extract_context_from_marker(div_text or text)
        return [], d_ctx, 1

    body_no_marker, trailing_marker = strip_trailing_markers(text)
    next_ctx: Dict[str, str] = {}
    if trailing_marker:
        next_ctx = extract_context_from_marker(trailing_marker)

    is_div2, _ = is_pure_divider(body_no_marker)
    if not body_no_marker or is_div2:
        return [], next_ctx, 1

    body_no_or = strip_trailing_or(body_no_marker)
    parts = split_or_questions(body_no_or)
    items: List[Dict[str, Any]] = []

    for part in parts:
        part_no_marks, explicit_marks = extract_trailing_marks(part)
        cleaned = clean_question_text(part_no_marks)
        if not cleaned:
            dropped += 1
            continue
        norm = normalize_question_text(cleaned)
        if not norm:
            dropped += 1
            continue

        meta = infer_question_metadata(
            cleaned_text=cleaned,
            sources=sources,
            existing_subject=default_subject,
            existing_topic=default_topic,
            existing_class=default_class,
            context_state=context_state,
            explicit_marks=explicit_marks,
        )
        items.append(
            {
                "question_text": cleaned,
                "normalized_text": norm,
                **meta,
            }
        )

    return items, next_ctx, dropped


def _fallback_extract_structured(
    lines: List[str],
    context_state: Dict[str, str],
    sources: List[str],
    default_subject: str = "",
    default_topic: str = "",
    default_class: str = "",
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Intelligent fallback for unnumbered documents:
    Extracts standalone paragraphs that are likely questions while tracking dividers & dropping headers/footers.
    """
    extracted: List[Dict[str, Any]] = []
    ctx = dict(context_state)
    dropped = 0

    for raw_line in lines:
        line = normalize_quotes_and_chars(raw_line).strip()
        if not line or len(line) < 6:
            continue

        # Update context from dividers/footers and skip them
        is_div, div_text = is_pure_divider(line)
        if is_div or STANDALONE_OR_RE.match(line):
            d_ctx = extract_context_from_marker(div_text or line)
            ctx.update({k: v for k, v in d_ctx.items() if v})
            dropped += 1
            continue

        line_no_footer = strip_attached_footers(line)
        if not line_no_footer or HEADER_REGEX.match(line_no_footer):
            f_ctx = extract_context_from_marker(line)
            ctx.update({k: v for k, v in f_ctx.items() if v})
            dropped += 1
            continue

        # Check question characteristics before stripping
        cand_no_marks, explicit_marks = extract_trailing_marks(line_no_footer)
        cand_no_marker, trailing_marker = strip_trailing_markers(cand_no_marks)
        cleaned = clean_question_text(cand_no_marker)
        if not cleaned:
            if trailing_marker:
                ctx.update({k: v for k, v in extract_context_from_marker(trailing_marker).items() if v})
            dropped += 1
            continue

        if (
            cleaned.endswith("?")
            or QUESTION_STEMS.match(cleaned)
            or (len(cleaned) >= 15 and not cleaned.endswith(":"))
        ):
            items, next_ctx, d_cnt = _finalize_raw_question(
                line,
                ctx,
                sources,
                default_subject=default_subject,
                default_topic=default_topic,
                default_class=default_class,
            )
            extracted.extend(items)
            dropped += d_cnt
            ctx.update({k: v for k, v in next_ctx.items() if v})
        else:
            dropped += 1

    return extracted, dropped


def extract_structured_questions_from_lines(
    lines: List[str],
    filename: str = "",
    default_subject: str = "",
    default_topic: str = "",
    default_class: str = "",
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Extracts structured question items from raw text lines, tracking Lesson/Book/Section markers,
    dropping pure dividers/footers/OR lines, normalizing quotes/OCR spaces, and inferring metadata.
    Returns: (items_list, dropped_dividers_or_noise_count)
    """
    sources = [filename] if filename else []
    ctx: Dict[str, str] = {}
    questions: List[Dict[str, Any]] = []
    current_q_lines: List[str] = []
    dropped_count = 0

    def flush_current():
        nonlocal dropped_count
        if not current_q_lines:
            return
        full_raw = " ".join(current_q_lines).strip()
        items, next_ctx, d_cnt = _finalize_raw_question(
            full_raw,
            ctx,
            sources,
            default_subject=default_subject,
            default_topic=default_topic,
            default_class=default_class,
        )
        questions.extend(items)
        dropped_count += d_cnt
        if next_ctx:
            ctx.update({k: v for k, v in next_ctx.items() if v})
        current_q_lines.clear()

    for raw_line in lines:
        line = normalize_quotes_and_chars(raw_line).strip()
        if not line:
            continue

        # Check standalone OR line
        if STANDALONE_OR_RE.match(line):
            flush_current()
            dropped_count += 1
            continue

        # Strip footers first and harvest class/subject context
        line_no_footer = strip_attached_footers(line)
        if line_no_footer != line:
            f_ctx = extract_context_from_marker(line)
            for k in ("class_level", "subject"):
                if f_ctx.get(k):
                    ctx[k] = f_ctx[k]
        if not line_no_footer:
            dropped_count += 1
            continue

        # Pure divider line (Book: ..., Lesson: ..., Prose Section, etc.)
        is_div, div_text = is_pure_divider(line_no_footer)
        if is_div:
            flush_current()
            d_ctx = extract_context_from_marker(div_text or line_no_footer)
            ctx.update({k: v for k, v in d_ctx.items() if v})
            if div_text and re.search(r"\b(prose|book:|footprints|vistas)\b", div_text, re.I) and "context" not in div_text.lower():
                ctx.pop("section_hint", None)
            dropped_count += 1
            continue

        if matches_question_prefix(line_no_footer):
            flush_current()
            current_q_lines.append(line_no_footer)
        else:
            # Skip non-question document headers before any question starts
            if not current_q_lines:
                if HEADER_REGEX.match(line_no_footer):
                    h_ctx = extract_context_from_marker(line_no_footer)
                    ctx.update({k: v for k, v in h_ctx.items() if v})
                continue
            current_q_lines.append(line_no_footer)

    flush_current()

    if not questions:
        questions, fb_dropped = _fallback_extract_structured(
            lines,
            ctx,
            sources,
            default_subject=default_subject,
            default_topic=default_topic,
            default_class=default_class,
        )
        dropped_count += fb_dropped

    return questions, dropped_count


def extract_questions_from_lines(lines: List[str]) -> List[str]:
    """Backward-compatible line extractor returning plain cleaned question strings."""
    items, _ = extract_structured_questions_from_lines(lines)
    return [item["question_text"] for item in items]


def extract_structured_questions_from_docx(
    file_stream: BinaryIO,
    filename: str = "",
    default_subject: str = "",
    default_topic: str = "",
    default_class: str = "",
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Extracts structured questions from a Word (.docx) file stream in true document order.
    Handles numbered paragraphs, Word native list styling (<w:numPr> / 'List Number'),
    section/lesson headings, tables, and unnumbered paragraph fallbacks.
    """
    doc = Document(file_stream)
    sources = [filename] if filename else []
    ctx: Dict[str, str] = {}
    dropped_count = 0

    # Walk paragraphs in document order, separating normal lines and native list items
    # while keeping context synchronized!
    ordered_items: List[Dict[str, Any]] = []
    buffered_lines: List[str] = []

    def flush_buffered_lines():
        nonlocal dropped_count
        if not buffered_lines:
            return
        items, d_cnt = extract_structured_questions_from_lines(
            buffered_lines,
            filename=filename,
            default_subject=default_subject,
            default_topic=default_topic,
            default_class=default_class,
        )
        # Re-apply accumulated ctx if items missed context
        for it in items:
            if not it.get("topic") and ctx.get("topic"):
                it["topic"] = ctx["topic"]
            if not it.get("class_level") and ctx.get("class_level"):
                it["class_level"] = ctx["class_level"]
            if not it.get("subject") and ctx.get("subject"):
                it["subject"] = ctx["subject"]
        ordered_items.extend(items)
        dropped_count += d_cnt
        buffered_lines.clear()

    for para in doc.paragraphs:
        text = normalize_quotes_and_chars(para.text).strip()
        if not text:
            continue

        is_native_list = (
            "list" in para.style.name.lower()
            or bool(para._element.xpath(".//w:numPr"))
        )

        if is_native_list:
            # Flush any preceding heading/text block first and harvest context from it
            if buffered_lines:
                # Check if buffered lines were just headings/dividers or also numbered questions
                # First update ctx from any divider lines in buffered_lines
                for bl in buffered_lines:
                    is_div, div_txt = is_pure_divider(bl)
                    if is_div:
                        ctx.update({k: v for k, v in extract_context_from_marker(div_txt or bl).items() if v})
                flush_buffered_lines()

            if STANDALONE_OR_RE.match(text):
                dropped_count += 1
                continue

            is_div, div_txt = is_pure_divider(text)
            if is_div:
                ctx.update({k: v for k, v in extract_context_from_marker(div_txt or text).items() if v})
                dropped_count += 1
                continue

            if HEADER_REGEX.match(text):
                dropped_count += 1
                continue

            items, next_ctx, d_cnt = _finalize_raw_question(
                text,
                ctx,
                sources,
                default_subject=default_subject,
                default_topic=default_topic,
                default_class=default_class,
            )
            ordered_items.extend(items)
            dropped_count += d_cnt
            ctx.update({k: v for k, v in next_ctx.items() if v})
        else:
            # Update context proactively on pure divider paragraphs for native list items that follow
            is_div, div_txt = is_pure_divider(text)
            if is_div:
                ctx.update({k: v for k, v in extract_context_from_marker(div_txt or text).items() if v})
            buffered_lines.append(text)

    flush_buffered_lines()

    # 2. Process document tables (common in question papers)
    for table in doc.tables:
        marks_col_idx: Optional[int] = None
        for r_idx, row in enumerate(table.rows):
            raw_cells = [normalize_quotes_and_chars(cell.text).strip() for cell in row.cells]
            non_empty = [c for c in raw_cells if c]
            if not non_empty:
                continue

            first_cell = non_empty[0].lower()
            if r_idx == 0 or any(h in first_cell for h in ["q.no", "s.no", "sr.no", "sl.no", "question", "marks"]):
                for c_idx, c_val in enumerate(raw_cells):
                    if "mark" in c_val.lower():
                        marks_col_idx = c_idx
                continue

            # Extract marks if marks column is known and numeric
            row_marks: Optional[float] = None
            if marks_col_idx is not None and marks_col_idx < len(raw_cells):
                m_cell = raw_cells[marks_col_idx]
                if re.fullmatch(r"\d+(?:\.\d+)?", m_cell):
                    try:
                        row_marks = float(m_cell)
                    except ValueError:
                        row_marks = None

            question_candidate = max(non_empty, key=len)
            if len(question_candidate) < 6 or HEADER_REGEX.match(question_candidate):
                dropped_count += 1
                continue

            items, next_ctx, d_cnt = _finalize_raw_question(
                question_candidate,
                ctx,
                sources,
                default_subject=default_subject,
                default_topic=default_topic,
                default_class=default_class,
            )
            for it in items:
                if row_marks is not None:
                    it["default_marks"] = row_marks
            ordered_items.extend(items)
            dropped_count += d_cnt
            ctx.update({k: v for k, v in next_ctx.items() if v})

    # Deduplicate within the same extracted file while preserving order
    seen = set()
    unique_items: List[Dict[str, Any]] = []
    for it in ordered_items:
        norm = it["normalized_text"]
        if norm and norm not in seen:
            seen.add(norm)
            unique_items.append(it)

    return unique_items, dropped_count


def extract_questions_from_docx(file_stream: BinaryIO) -> List[str]:
    """Backward-compatible DOCX extractor returning plain cleaned question strings."""
    items, _ = extract_structured_questions_from_docx(file_stream)
    return [item["question_text"] for item in items]


def extract_structured_questions_from_pdf(
    file_stream: BinaryIO,
    filename: str = "",
    default_subject: str = "",
    default_topic: str = "",
    default_class: str = "",
) -> Tuple[List[Dict[str, Any]], int]:
    """Extracts structured questions from a PDF (.pdf) file stream."""
    reader = PdfReader(file_stream)
    all_lines: List[str] = []

    for page in reader.pages:
        page_text = page.extract_text() or ""
        for raw_line in page_text.splitlines():
            line = raw_line.strip()
            if line:
                all_lines.append(line)

    items, dropped = extract_structured_questions_from_lines(
        all_lines,
        filename=filename,
        default_subject=default_subject,
        default_topic=default_topic,
        default_class=default_class,
    )

    # Deduplicate within same PDF file preserving order
    seen = set()
    unique_items: List[Dict[str, Any]] = []
    for it in items:
        norm = it["normalized_text"]
        if norm and norm not in seen:
            seen.add(norm)
            unique_items.append(it)

    return unique_items, dropped


def extract_questions_from_pdf(file_stream: BinaryIO) -> List[str]:
    """Backward-compatible PDF extractor returning plain cleaned question strings."""
    items, _ = extract_structured_questions_from_pdf(file_stream)
    return [item["question_text"] for item in items]


def extract_structured_questions_from_file(
    filename: str,
    file_bytes: bytes,
    default_subject: str = "",
    default_topic: str = "",
    default_class: str = "",
) -> Tuple[List[Dict[str, Any]], int]:
    """Dispatches structured extraction based on extension (.docx or .pdf)."""
    lower_name = filename.lower()
    stream = io.BytesIO(file_bytes)

    if lower_name.endswith(".docx"):
        return extract_structured_questions_from_docx(
            stream,
            filename=filename,
            default_subject=default_subject,
            default_topic=default_topic,
            default_class=default_class,
        )
    elif lower_name.endswith(".pdf"):
        return extract_structured_questions_from_pdf(
            stream,
            filename=filename,
            default_subject=default_subject,
            default_topic=default_topic,
            default_class=default_class,
        )
    else:
        raise ValueError(f"Unsupported file format '{filename}'. Only .docx and .pdf files are supported.")


def extract_questions_from_file(filename: str, file_bytes: bytes) -> List[str]:
    """Backward-compatible file extractor returning plain cleaned question strings."""
    items, _ = extract_structured_questions_from_file(filename, file_bytes)
    return [item["question_text"] for item in items]
