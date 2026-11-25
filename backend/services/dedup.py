import re
from difflib import SequenceMatcher
from typing import List, Optional, Tuple

# Comprehensive list of regex patterns to detect and strip question prefixes:
# 1. Serial numbers: 1., 1), 1:, 1 -, 1/ , 1\t, 1 (space)
# 2. Prefixes: Q1, Q.1, Q 1, Question 1:, Que 1., Prob 1.
# 3. Brackets: (1), [1], (1).
# 4. Roman numerals: i., ii., iii., iv., v., (i), (ii), I., II.
# 5. Letters: a., b., c., (a), (b), A., B.
# 6. Bullets: •, *, -, ▪, ▫, →, >
QUESTION_PREFIX_PATTERNS = [
    re.compile(r"^\s*(?:(?:Q(?:uestion|ues|ue)?|Prob(?:lem)?)\.?\s*)?(\d+)\s*[\.\)\:\-\/\t ]\s*(.*)$", re.IGNORECASE | re.DOTALL),
    re.compile(r"^\s*[\(\[]\s*(\d+)\s*[\)\]][\.\:\-\t ]?\s*(.*)$", re.IGNORECASE | re.DOTALL),
    re.compile(r"^\s*(?:[\(\[]\s*)?([ivxlcdm]+|[a-zA-Z])\s*[\.\)\]][\:\-\t ]?\s*(.*)$", re.IGNORECASE | re.DOTALL),
    re.compile(r"^\s*[\•\*\-\▪\▫\→\>]\s+(.*)$", re.IGNORECASE | re.DOTALL),
]

# Document footer patterns commonly embedded during PDF/DOCX extraction
FOOTER_PATTERNS = [
    re.compile(
        r"\bClass\s*:\s*\d+\w*\s*(?:\([^)]*\))?\s*Subject\s*:\s*[^.\n]*?Page\s+\d+\s+of\s+\d+",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bClass\s*:\s*\d+\w*\s*\(\d{4}[-–]\d{2,4}\)\s*Subject\s*:\s*English(?:\s+Compulsory)?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bClass\s*:\s*\d+\w*\s*\(\d{4}[-–]\d{2,4}\)\s*Subject\s*:\s*[^.\n?!]{2,45}$",
        re.IGNORECASE,
    ),
    re.compile(r"\bGiriraj\s+Yadav\s*[‘'\"`]?JUGNU[’'\"`]?\s*(?:Mob\.?\s*No\.?\s*\d+)?", re.IGNORECASE),
    re.compile(r"\bMob\.?\s*No\.?\s*\d{8,12}\b", re.IGNORECASE),
    re.compile(r"\bPage\s+\d+\s+of\s+\d+\b", re.IGNORECASE),
]

# Trailing attached Lesson / Book / Section markers glued to end of a question
TRAILING_MARKER_REGEX = re.compile(
    r"(?:[\uf0d8\u2022]\s*)?"
    r"(?:Explanation\s+with\s+Reference\s+to\s+the\s+Context\s*[:-]*\s*)?"
    r"(?:(?:First\s+Flight|Foot\s*[Pp]rints\s+without\s+feet|Flamingo|Vistas|Beehive|Moments|Hornbill|Snapshots)\s*(?:\([^)]*\))?\s*)?"
    r"(?:(?:Prose|Poetry)\s*(?:Section)?\s+)?"
    r"(?:Lesson|Chapter|Unit)\s*[:.]?\s*\d+\s*[\.\:\-]?\s*.*$",
    re.IGNORECASE,
)

# Trailing bare book/context markers without lesson numbers
TRAILING_CONTEXT_ONLY_REGEX = re.compile(
    r"(?:[\uf0d8\u2022]\s*)?"
    r"(?:Explanation\s+with\s+Reference\s+to\s+the\s+Context\s*[:-]*)$",
    re.IGNORECASE,
)

# Standalone pure divider row patterns
PURE_BOOK_DIVIDER_RE = re.compile(
    r"^(?:Book\s*:\s*.*|"
    r"(?:First\s+Flight|Foot\s*[Pp]rints\s+without\s+feet|Flamingo|Vistas|Beehive|Moments|Hornbill|Snapshots)"
    r"(?:\s*\((?:Prose|Poetry)(?:\s+Section)?\))?)$",
    re.IGNORECASE,
)

PURE_LESSON_DIVIDER_RE = re.compile(
    r"^(?:(?:First\s+Flight|Foot\s*[Pp]rints\s+without\s+feet|Flamingo|Vistas|Beehive|Moments|Hornbill|Snapshots)\s*(?:\([^)]*\))?\s*)?"
    r"(?:(?:Prose|Poetry)\s*(?:Section)?\s*)?"
    r"(?:Lesson|Chapter|Unit)\s*[:.]?\s*\d+\b.*$",
    re.IGNORECASE,
)

PURE_SECTION_DIVIDER_RE = re.compile(
    r"^(?:Prose\s+Section|Poetry\s+Section|Grammar\s*[-:]?|Writing\s+Section|Reading\s+Section|"
    r"Literature\s+Section|Section\s+[A-Z0-9]+\s*[-:.]?|"
    r"(?:[\uf0d8\u2022]\s*)?Explanation\s+with\s+Reference\s+to\s+the\s+Context\s*[:-]*)$",
    re.IGNORECASE,
)

BARE_SUBCHAPTER_DIVIDERS = {
    "his first flight",
    "the black aeroplane",
    "a baker from goa",
    "coorg",
    "tea from assam",
    "prose section",
    "poetry section",
    "grammar",
    "grammar-",
}

TRAILING_OR_RE = re.compile(r"\s+\bOR\b\s*$")
MID_OR_SPLIT_RE = re.compile(r"(?<=[?.!])\s+\bOR\b\s+(?=[A-Za-z\"'‘“])")
TRAILING_MARKS_RE = re.compile(r"\s*[\(\[]\s*(\d+(?:\.\d+)?)\s*(?:marks?|pts?|m)\s*[\)\]]\s*$", re.IGNORECASE)


def normalize_quotes_and_chars(text: str) -> str:
    """
    Normalizes curly quotes, dashes, private-use Wingdings characters,
    and zero-width spaces into clean ASCII equivalents.
    """
    if not text:
        return ""
    replacements = {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u2032": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2033": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u00a0": " ",
        "\u200b": "",
        "\u200c": "",
        "\u200d": "",
        "\ufeff": "",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    # Remove private-use characters (e.g. Wingdings bullets like \uf0d8)
    text = re.sub(r"[\uf000-\uf8ff]", " ", text)
    # Fix stray double-quote artifacts like `'"i'll`
    text = re.sub(r"^['\"]+(['\"][A-Za-z])", r"\1", text)
    return text


OCR_WORD_FIXES = [
    (re.compile(r"\ba\s+re\b"), "are"),
    (re.compile(r"\bth\s+e\b"), "the"),
    (re.compile(r"\bwa\s+s\b"), "was"),
    (re.compile(r"\bH\s+ow\b"), "How"),
    (re.compile(r"\bn\s+ew\b"), "new"),
    (re.compile(r"\bnot\s+ice\b"), "notice"),
    (re.compile(r"\bstu\s+dy\b"), "study"),
    (re.compile(r"\bwor\s+ds\b"), "words"),
    (re.compile(r"\bsymb\s+ol\b"), "symbol"),
    (re.compile(r"\bCharl\s+ey\b"), "Charley"),
    (re.compile(r"\bdraw\s+s\b"), "draws"),
    (re.compile(r"\bdifferen\s+ces\b"), "differences"),
    (re.compile(r"\bAnna\s+n\b"), "Annan"),
    (re.compile(r"\be\s+bright\b", re.IGNORECASE), "Ebright"),
    (re.compile(r"\bThink\s*-\s*Tank\b", re.IGNORECASE), "Think-Tank"),
    (re.compile(r"\bthumb-\s+prints\b", re.IGNORECASE), "thumb-prints"),
    (re.compile(r"\bM\.\s*hamel\b", re.IGNORECASE), "M. Hamel"),
    (re.compile(r"\b(did|does|do|is|are|was|were|could|would|should|have|has|had)\s+n't\b", re.IGNORECASE), r"\1n't"),
]


def fix_ocr_spacing(text: str) -> str:
    """
    Fixes common PDF/OCR whitespace defects without corrupting legitimate words:
    - Collapses repeated whitespace
    - Removes space before ?, !, ,, ;, : and word-trailing .
    - Removes stray spaces right inside opening/closing quotes
    - Ensures space after ? or ! when jammed directly before a letter
    - Repairs known OCR split words & spaced possessive `'s`
    """
    if not text:
        return ""
    # Collapse whitespace first
    t = re.sub(r"\s+", " ", text).strip()
    # Fix spaces before punctuation: "novel , " -> "novel, ", "tigers ?" -> "tigers?"
    t = re.sub(r"\s+([?!,;:])", r"\1", t)
    # Fix space before period after a word character (e.g. "M . Hamel" -> "M. Hamel")
    t = re.sub(r"(?<=\w)\s+\.(?=\s|$)", ".", t)
    # Fix spaced possessive like "peddler 's" / "today 's"
    t = re.sub(r"\b([A-Za-z]{2,})\s+'s\b", r"\1's", t)
    # Fix safe targeted OCR split words
    for pat, repl in OCR_WORD_FIXES:
        t = pat.sub(repl, t)
    # Fix missing space after ? or ! before next sentence (e.g. "necklace?What" -> "necklace? What")
    t = re.sub(r"([?!])([A-Za-z])", r"\1 \2", t)
    # Clean stray space right after opening quote or before closing quote when paired
    t = re.sub(r'"\s+([^"]+?)\s*"', r'"\1"', t)
    t = re.sub(r"(^|[\s,(])'\s+([^']+?)\s*'(?=$|[\s.,?!;:])", r"\1'\2'", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def strip_attached_footers(text: str) -> str:
    """Removes embedded page/teacher/school footers from question strings."""
    if not text:
        return ""
    cleaned = text
    for pat in FOOTER_PATTERNS:
        cleaned = pat.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def strip_trailing_markers(text: str) -> Tuple[str, Optional[str]]:
    """
    Strips trailing Lesson/Book/Section markers glued onto the end of a question.
    Returns: (cleaned_text, extracted_marker_text_or_None)
    """
    if not text:
        return "", None

    marker_parts: List[str] = []
    working = text.strip()

    m = TRAILING_MARKER_REGEX.search(working)
    if m:
        marker_parts.append(m.group(0).strip())
        working = working[: m.start()].strip()

    m2 = TRAILING_CONTEXT_ONLY_REGEX.search(working)
    if m2:
        marker_parts.append(m2.group(0).strip())
        working = working[: m2.start()].strip()

    extracted = " ".join(marker_parts).strip() if marker_parts else None
    return working, extracted


def strip_trailing_or(text: str) -> str:
    """Strips dangling trailing 'OR' markers from a question."""
    if not text:
        return ""
    return TRAILING_OR_RE.sub("", text).strip()


def split_or_questions(text: str) -> List[str]:
    """
    Splits two distinct questions joined by uppercase 'OR' (e.g., 'Question A? OR Question B?').
    Only splits when both halves are substantial (>= 15 chars) so phrases like 'X or Y' are untouched.
    """
    if not text:
        return []
    parts = MID_OR_SPLIT_RE.split(text)
    if len(parts) <= 1:
        return [text]
    valid_parts = [p.strip() for p in parts if len(p.strip()) >= 15]
    if len(valid_parts) >= 2:
        return valid_parts
    return [text]


def extract_trailing_marks(text: str) -> Tuple[str, Optional[float]]:
    """Extracts explicit marks like '[5 Marks]' or '(3 marks)' from the end of text."""
    if not text:
        return "", None
    m = TRAILING_MARKS_RE.search(text)
    if not m:
        return text, None
    try:
        marks_val = float(m.group(1))
    except ValueError:
        return text, None
    stripped = text[: m.start()].strip()
    return stripped, marks_val


def is_pure_divider(text: str) -> Tuple[bool, Optional[str]]:
    """
    Detects whether a line/row is purely a Book/Lesson/Section divider rather than a question.
    Returns: (is_divider, divider_text)
    """
    if not text:
        return True, None
    t = normalize_quotes_and_chars(text)
    t = strip_attached_footers(t).strip()
    if not t:
        return True, None

    low = t.lower().strip(" .:-")
    if low in BARE_SUBCHAPTER_DIVIDERS:
        return True, t
    if PURE_BOOK_DIVIDER_RE.match(t) or PURE_LESSON_DIVIDER_RE.match(t) or PURE_SECTION_DIVIDER_RE.match(t):
        return True, t
    return False, None


def clean_question_text(raw_text: str) -> str:
    """
    Cleans raw extracted question text:
    - Normalizes quotes, private-use symbols, and OCR spacing
    - Strips embedded footers and trailing 'OR'
    - Strips leading question numbers/bullets/stray '*'
    - Standardizes inner whitespace while preserving casing and punctuation
    """
    if not raw_text:
        return ""

    text = normalize_quotes_and_chars(raw_text)
    text = strip_attached_footers(text)
    text = text.strip()
    # Strip stray leading asterisk stuck to word like "*Draw a brief..."
    text = re.sub(r"^\*(?=[A-Za-z])", "", text)

    for pattern in QUESTION_PREFIX_PATTERNS:
        match = pattern.match(text)
        if match:
            text = match.group(match.lastindex) if match.lastindex is not None else ""
            break

    text = strip_trailing_or(text)
    cleaned = fix_ocr_spacing(text)
    return cleaned


def normalize_question_text(raw_or_cleaned_text: str) -> str:
    """
    Produces canonical string for exact-match deduplication:
    - Strips leading numbering, footers, trailing OR
    - Normalizes quotes, dashes, honorific periods, and internal/punctuation whitespace
    - Lowercases
    - Strips trailing punctuation for consistent matching
    """
    cleaned = clean_question_text(raw_or_cleaned_text)
    normalized = cleaned.lower()
    # Unify honorific periods (mrs. -> mrs, mr. -> mr, mme. -> mme, dr. -> dr)
    normalized = re.sub(r"\b(mr|mrs|ms|dr|mme)\.(?=\s)", r"\1", normalized)
    # Remove decorative quote marks around words/phrases while keeping internal apostrophes (e.g., ohm's)
    normalized = normalized.replace('"', "")
    normalized = re.sub(r"(?<!\w)'|'(?!\w)", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    # Strip trailing punctuation and stray closing quotes for canonical comparison
    normalized = re.sub(r"[\.\?\!\,\:\;\"']+$", "", normalized).strip()
    normalized = re.sub(r"^[\"\'*]+", "", normalized).strip()
    return normalized


def compute_text_similarity(norm_a: str, norm_b: str) -> float:
    """Computes hybrid similarity score [0.0, 1.0] between two normalized question strings."""
    if not norm_a or not norm_b:
        return 0.0
    if norm_a == norm_b:
        return 1.0
    seq_ratio = SequenceMatcher(None, norm_a, norm_b).ratio()
    tokens_a = set(re.findall(r"[a-z0-9]+", norm_a))
    tokens_b = set(re.findall(r"[a-z0-9]+", norm_b))
    if not tokens_a or not tokens_b:
        return seq_ratio
    jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
    return round(0.65 * seq_ratio + 0.35 * jaccard, 4)
