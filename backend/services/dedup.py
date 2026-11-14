import re

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

def clean_question_text(raw_text: str) -> str:
    """
    Cleans raw extracted question text:
    - Strips leading question numbers/bullets
    - Standardizes inner whitespace
    - Preserves casing and punctuation for display and export
    """
    if not raw_text:
        return ""

    text = raw_text.strip()
    for pattern in QUESTION_PREFIX_PATTERNS:
        match = pattern.match(text)
        if match:
            text = match.group(match.lastindex) if match.lastindex is not None else ""
            break

    # Collapse multiple consecutive whitespaces (including newlines and tabs) into single space
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned

def normalize_question_text(raw_or_cleaned_text: str) -> str:
    """
    Produces canonical string for exact-match deduplication:
    - Strips leading numbering
    - Normalizes internal whitespace
    - Lowercases
    - Strips trailing period or question mark for consistent matching
    """
    cleaned = clean_question_text(raw_or_cleaned_text)
    normalized = cleaned.lower()
    # Strip trailing punctuation for canonical comparison
    normalized = re.sub(r"[\.\?\!\,\:\;]+$", "", normalized).strip()
    return normalized
