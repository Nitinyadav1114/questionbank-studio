import os
import re
import json
import argparse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.services.dedup import (
    clean_question_text,
    normalize_question_text,
    normalize_quotes_and_chars,
    fix_ocr_spacing,
    strip_attached_footers,
    strip_trailing_markers,
    strip_trailing_or,
    split_or_questions,
    extract_trailing_marks,
    is_pure_divider,
)

# Canonical Chapter Names & Normalization Map
CHAPTER_CANONICAL_MAP = {
    # Class 10 First Flight (Prose)
    "a letter to god": ("A Letter to God", "Class 10"),
    "nelson mandela": ("Nelson Mandela: Long Walk to Freedom", "Class 10"),
    "nelson mandela: long walk to freedom": ("Nelson Mandela: Long Walk to Freedom", "Class 10"),
    "two stories about flying": ("Two Stories about Flying", "Class 10"),
    "his first flight": ("Two Stories about Flying", "Class 10"),
    "the black aeroplane": ("Two Stories about Flying", "Class 10"),
    "from the diary of anne frank": ("From the Diary of Anne Frank", "Class 10"),
    "glimpses of india": ("Glimpses of India", "Class 10"),
    "glimpes of india": ("Glimpses of India", "Class 10"),
    "a baker from goa": ("Glimpses of India", "Class 10"),
    "coorg": ("Glimpses of India", "Class 10"),
    "tea from assam": ("Glimpses of India", "Class 10"),
    "mijbil the otter": ("Mijbil the Otter", "Class 10"),
    "madam rides the bus": ("Madam Rides the Bus", "Class 10"),
    "the sermon at benares": ("The Sermon at Benares", "Class 10"),
    "the proposal": ("The Proposal", "Class 10"),
    # Class 10 First Flight (Poetry)
    "dust of snow": ("Dust of Snow", "Class 10"),
    "fire and ice": ("Fire and Ice", "Class 10"),
    "a tiger in the zoo": ("A Tiger in the Zoo", "Class 10"),
    "how to tell wild animals": ("How to Tell Wild Animals", "Class 10"),
    "the ball poem": ("The Ball Poem", "Class 10"),
    "amanda": ("Amanda!", "Class 10"),
    "amanda!": ("Amanda!", "Class 10"),
    "the trees": ("The Trees", "Class 10"),
    "fog": ("Fog", "Class 10"),
    "the tale of custard the dragon": ("The Tale of Custard the Dragon", "Class 10"),
    "for anne gregory": ("For Anne Gregory", "Class 10"),
    # Class 10 Footprints Without Feet
    "a triumph of surgery": ("A Triumph of Surgery", "Class 10"),
    "the thief's story": ("The Thief's Story", "Class 10"),
    "the midnight visitor": ("The Midnight Visitor", "Class 10"),
    "a question of trust": ("A Question of Trust", "Class 10"),
    "footprints without feet": ("Footprints Without Feet", "Class 10"),
    "the making of a scientist": ("The Making of a Scientist", "Class 10"),
    "the necklace": ("The Necklace", "Class 10"),
    "bholi": ("Bholi", "Class 10"),
    "the book that saved the earth": ("The Book That Saved the Earth", "Class 10"),
    # Class 12 Flamingo (Prose)
    "the last lesson": ("The Last Lesson", "Class 12"),
    "last lesson": ("The Last Lesson", "Class 12"),
    "lost spring": ("Lost Spring", "Class 12"),
    "deep water": ("Deep Water", "Class 12"),
    "the rattrap": ("The Rattrap", "Class 12"),
    "indigo": ("Indigo", "Class 12"),
    "poets and pancakes": ("Poets and Pancakes", "Class 12"),
    "the interview": ("The Interview", "Class 12"),
    "going places": ("Going Places", "Class 12"),
    # Class 12 Flamingo (Poetry)
    "my mother at sixty-six": ("My Mother at Sixty-Six", "Class 12"),
    "my mother at sixty six": ("My Mother at Sixty-Six", "Class 12"),
    "keeping quiet": ("Keeping Quiet", "Class 12"),
    "keeping quite": ("Keeping Quiet", "Class 12"),
    "a thing of beauty": ("A Thing of Beauty", "Class 12"),
    "a roadside stand": ("A Roadside Stand", "Class 12"),
    "aunt jennifer's tigers": ("Aunt Jennifer's Tigers", "Class 12"),
    # Class 12 Vistas
    "the third level": ("The Third Level", "Class 12"),
    "the tiger king": ("The Tiger King", "Class 12"),
    "journey to the end of the earth": ("Journey to the End of the Earth", "Class 12"),
    "the enemy": ("The Enemy", "Class 12"),
    "on the face of it": ("On the Face of It", "Class 12"),
    "memories of childhood": ("Memories of Childhood", "Class 12"),
    # Class 9 Beehive & Moments
    "the fun they had": ("The Fun They Had", "Class 9"),
    "the sound of music": ("The Sound of Music", "Class 9"),
    "the little girl": ("The Little Girl", "Class 9"),
    "reach for the top": ("Reach for the Top", "Class 9"),
    "the adventures of toto": ("The Adventures of Toto", "Class 9"),
    "iswaran the storyteller": ("Iswaran the Storyteller", "Class 9"),
    "in the kingdom of fools": ("In the Kingdom of Fools", "Class 9"),
    "the happy prince": ("The Happy Prince", "Class 9"),
    "wind": ("Wind", "Class 9"),
    "a legend of the northland": ("A Legend of the Northland", "Class 9"),
    "a house is not a home": ("A House Is Not a Home", "Class 9"),
}

CANONICAL_LITERATURE_TOPICS = {v[0] for v in CHAPTER_CANONICAL_MAP.values()}

# Content keyword rules (checked when explicit marker context is missing)
CHAPTER_KEYWORD_RULES: List[Tuple[str, str, str]] = [
    # Class 10
    (r"\b(lencho|hailstorm|postmaster|new coin|bunch of crooks|act of charity)\b", "A Letter to God", "Class 10"),
    (r"\b(mandela|apartheid|twin obligations?|national anthems?|south africa|oppressor|inauguration)\b", "Nelson Mandela: Long Walk to Freedom", "Class 10"),
    (r"\b(seagull|ledge|black aeroplane|dakota|control cent(?:er|re)|his first flight|take the risk)\b", "Two Stories about Flying", "Class 10"),
    (r"\b(anne frank|anne(?:'s)?\b.*(?:diary|essay|parents|chatterbox|grandmother)|keesing|kitty|chatterbox|quack,\s*quack|mr\.?\s*keesing)\b", "From the Diary of Anne Frank", "Class 10"),
    (r"\b(pad[ae]r|kabai|baker|baking|bread|jackfruit|goa|coorg|kodagu|kaveri|tea from assam|tea bushes|tea.*legend|legend.*tea|rajvir|pranjol|bodhidharma)\b", "Glimpses of India", "Class 10"),
    (r"\b(mijbil|mij\b|otter|basra|camusfearna|airhostess)\b", "Mijbil the Otter", "Class 10"),
    (r"\b(valli|bus ride|madam rides|conductor call valli)\b", "Madam Rides the Bus", "Class 10"),
    (r"\b(buddha|gautama|kisa gotami|benares|mustard seed|earthen vessels|mortals|sermon)\b", "The Sermon at Benares", "Class 10"),
    (r"\b(lomov|natalya|nataliya|chubukov|oxen meadows|squeezer|guess\b|the proposal)\b", "The Proposal", "Class 10"),
    (r"\b(dust of snow|hemlock|crow shook|poet's mood|day of poet saved)\b", "Dust of Snow", "Class 10"),
    (r"\b(fire.*ice|ice.*fire|world end.*poet|end of the world|desire.*hatred)\b", "Fire and Ice", "Class 10"),
    (r"\b(tiger.*zoo|tiger.*cage|tiger.*live|tiger.*natural habitat|behind the bars|terrorise the villagers)\b", "A Tiger in the Zoo", "Class 10"),
    (r"\b(asian lion|bengal tiger|leopard|chameleon|wild animals|beasts of prey|discerned)\b", "How to Tell Wild Animals", "Class 10"),
    (r"\b(ball poem|losing the ball|lost.*ball|boy learning.*poem|intrude on the boy|through the boy|world of possessions|money is external|epistemology of loss|happened to the boy)\b", "The Ball Poem", "Class 10"),
    (r"\b(amanda|amada|rapunzel|mermaid|child.*instructed)\b", "Amanda!", "Class 10"),
    (r"\b(the trees|the tress|trees inside|twigs|boughs|branches.*patient|sun bury its feet|compare their branches)\b", "The Trees", "Class 10"),
    (r"\b(poem.*fog|\bfog\b|cat feet|harbour and city)\b", "Fog", "Class 10"),
    (r"\b(custard|belinda|pirate|ink\b.*blink|dragon.*custard|dragon.*pirate)\b", "The Tale of Custard the Dragon", "Class 10"),
    (r"\b(anne gregory|gregory|yellow hair|golden hair|young woman's hair|old religious man|god's love)\b", "For Anne Gregory", "Class 10"),
    (r"\b(tricki|pumph?rey|herriot|harriot|convalescing|pampered|surgery|feeding the dogs|feeding time)\b", "A Triumph of Surgery", "Class 10"),
    (r"\b(hari singh?|anil\b|thief(?:'s)? story|rob anil|people.*robbed)\b", "The Thief's Story", "Class 10"),
    (r"\b(ausable|fowler|max\b.*(?:balcony|room|scream|police|got in)|how has max|midnight visitor|secret agents?)\b", "The Midnight Visitor", "Class 10"),
    (r"\b(horace|danby|dandy|shotover grange|lady in red|question of trust|steal every year|open the safe)\b", "A Question of Trust", "Class 10"),
    (r"\b(griffin|invisible man|mrs\.?\s*hall|clergyman|curious episode.*study|wandering the streets|footprints without feet)\b", "Footprints Without Feet", "Class 10"),
    (r"\b(ebright|e\s*bright|monarch|pupa|weiherer|science fair|making of a scientist|richard.*mother)\b", "The Making of a Scientist", "Class 10"),
    (r"\b(matilda|loisel|loisela|necklace|forestier|minister's ball)\b", "The Necklace", "Class 10"),
    (r"\b(bholi|sulekha|bishamber|ramlal)\b", "Bholi", "Class 10"),
    (r"\b(think\s*-?\s*tank|noodle|omega|iota|oop|martians?|mother goose|era of the book|invade the earth|saved the earth|sandwich.*book)\b", "The Book That Saved the Earth", "Class 10"),
    # Class 12
    (r"\b(franz|m\.?\s*hamel|alsace|lorraine|berlin.*school|last lesson|french language|back\s*benches.*class)\b", "The Last Lesson", "Class 12"),
    (r"\b(saheb|mukesh|seemapuri|firozabad|bangle|bengal makers|rag\s*pickers|lost spring|garbage to them is gold|glass bangles|child labour|without shoes or chappals)\b", "Lost Spring", "Class 12"),
    (r"\b(douglas|y\.?m\.?c\.?a|yakima|deep water|fear of water|build a swimmer|misadventure|started down a third time)\b", "Deep Water", "Class 12"),
    (r"\b(rattrap|peddler|edla|ironmaster|ramsjo|kronor|crofter)\b", "The Rattrap", "Class 12"),
    (r"\b(gandhiji|champaran|rajkumar shukla|indigo|sharecropper|tenants and landlords|plight of the peasants)\b", "Indigo", "Class 12"),
    (r"\b(subbu|gemini studio|pancakes|office boy|moral re-armament|\bmra\b|god that failed|fiery misery|national integration|doing nothing at the studios|englishman's visit|tamil drama)\b", "Poets and Pancakes", "Class 12"),
    (r"\b(umberto eco|\beco's\b|naipaul|kipling|name of the rose|interstitial|interviews?|interviewed|thumb[\s-]*prints on his windpipe|chief source of information)\b", "The Interview", "Class 12"),
    (r"\b(sophie|danny casey|geoff|jansie|going places)\b", "Going Places", "Class 12"),
    (r"\b(cochin|amma|sixty[\s-]*six|wan,\s*pale|late winter's moon|driving from my parent|mother.*car|affection for her mother|merry children|spilling out of their homes|poetess as a daughter|mother sitting beside her)\b", "My Mother at Sixty-Six", "Class 12"),
    (r"\b(keeping qui(?:et|te)|count to twelve|exotic moment|green wars|no truck with death|total inactivity|single-minded|speak in any language|fighting wars|cause of our sadness|sadness.*poet refers)\b", "Keeping Quiet", "Class 12"),
    (r"\b(things? of beauty|beautiful thing|bower quiet|lovely tales|immortal drink|grandeur.*mighty dead|tied to the earth|suffering and pain|troubles? and sufferings?)\b", "A Thing of Beauty", "Class 12"),
    (r"\b(roadside stand|childish long?ing|childish logging|polished traffic|wild berries|flower of cities|car owners stop)\b", "A Roadside Stand", "Class 12"),
    (r"\b(aunt jennifer|wedding b[ao]nd|ordeals|prancing|tigers in the poem symbolize|jennifer's life|uncle's (?:band|wedding))\b", "Aunt Jennifer's Tigers", "Class 12"),
    (r"\b(third level|charley|galesburg|louisa|sam's letter|letter received by sam|old style currency|grand central)\b", "The Third Level", "Class 12"),
    (r"\b(tiger king|jung jung bahadur|pratibandapuram|hundredth tiger|100th tiger|maharaja|chief astrologer)\b", "The Tiger King", "Class 12"),
    (r"\b(antarctica|antarctica content|gondwana|students on ice|tishani doshi|future of humankind|global temperature)\b", "Journey to the End of the Earth", "Class 12"),
    (r"\b(sadao|hana|general takima|american soldier|tom to escape|sent with troops)\b", "The Enemy", "Class 12"),
    (r"\b(mr\.?\s*lamb|mr\.?\s*lam\b|derry|tin leg|crab apples|on the face of it|secluded places|master of the garden)\b", "On the Face of It", "Class 12"),
    (r"\b(zitkala|bama|annan|anna\s*n|memories of childhood|singled|untouchability|judewin)\b", "Memories of Childhood", "Class 12"),
    # Class 9
    (r"\b(telebook|margie|tommy|mechanical teacher)\b", "The Fun They Had", "Class 9"),
    (r"\b(shehnai|pungi|bismillah|evelyn)\b", "The Sound of Music", "Class 9"),
    (r"\b(kezia|little girl|pin[\s-]*cushion)\b", "The Little Girl", "Class 9"),
    (r"\b(santosh|snotosh|maria sharapova)\b", "Reach for the Top", "Class 9"),
    (r"\b(toto|grandfather.*zoo)\b", "The Adventures of Toto", "Class 9"),
    (r"\b(iswaran|mahendr[au])\b", "Iswaran the Storyteller", "Class 9"),
    (r"\b(kingdom of fools|guru.*disciple|bricklayer|real culprit)\b", "In the Kingdom of Fools", "Class 9"),
    (r"\b(swallow.*prince|happy prince|seamstress)\b", "The Happy Prince", "Class 9"),
    (r"\b(wind,\s*come softly|wind god winnows|crumbling|threw them all down.*books)\b", "Wind", "Class 9"),
    (r"\b(legend of the northland|saint peter)\b", "A Legend of the Northland", "Class 9"),
    (r"\b(break down in tears after the fire)\b", "A House Is Not a Home", "Class 9"),
]

# Known writing / paragraph / story / letter topic stub patterns
WRITING_PROMPT_RE = re.compile(
    r"\b(write a letter(?!\s+to\s+god\b)|official letter|write an? (?:report|advertisement|article|paragraph|story|notice|email|application)|"
    r"draft a notice|matrimonials|you are [A-Z][a-z]+|imagine that you are)\b",
    re.IGNORECASE,
)

GRAMMAR_PROMPT_RE = re.compile(
    r"(?:\.{3,}|…{2,}|_{3,}|\(\s*(?:perfect participle|both[\s-]+and|so[\s-]+that|or/and|as well as\s*/\s*both|till/|"
    r"too\s*-\s*to|no sooner|not only|passive voice|indirect speech|reported speech|tense|preposition|determiner|conjunction)\s*\))",
    re.IGNORECASE,
)

OCR_ARTIFACT_PATTERNS = [
    (re.compile(r"\b(anna\s+n|stu\s+dy|wor\s+ds|th\s+e|not\s+ice|e\s+bright|a\s+re|o\s+f|i\s+the\s+poet)\b", re.I), "Possible OCR split-word spacing"),
    (re.compile(r"\b(snotosh|brunt|tittle|loisela|happned|threatenting|post-martem|childish\s+logging|the\s+tress|glimpes)\b", re.I), "Possible OCR/spelling typo"),
    (re.compile(r"\(\d{3,4}\)\s*$"), "Contains guidebook page number"),
]

LEGACY_CLASS_TOPIC_RE = re.compile(r"^\s*class\s*[-]?\s*(\d{1,2})\s*(?:th|st|nd|rd)?\s*$", re.IGNORECASE)
FILENAME_CLASS_RE = re.compile(r"(?:^|[_\-\s])(?:class[_\-\s]*)?(9|10|11|12)(?:th)?(?=[_\-\s.]|$)", re.IGNORECASE)


def canonicalize_class_label(raw: str) -> str:
    if not raw:
        return ""
    m = re.search(r"\b(9|10|11|12)(?:th|st|nd|rd)?\b", str(raw), re.IGNORECASE)
    if m:
        return f"Class {m.group(1)}"
    return raw.strip()


def extract_context_from_marker(marker_text: str) -> Dict[str, str]:
    """
    Parses a Book / Lesson / Section marker string into structured context updates:
    { class_level, subject, topic, section_hint }
    """
    if not marker_text:
        return {}

    ctx: Dict[str, str] = {}
    t = normalize_quotes_and_chars(marker_text).strip()

    # Check Class & Subject in marker
    cls_m = re.search(r"\bClass\s*[:\-]?\s*(9|10|11|12)(?:th)?\b", t, re.I)
    if cls_m:
        ctx["class_level"] = f"Class {cls_m.group(1)}"

    subj_m = re.search(r"\bSubject\s*[:\-]?\s*([A-Za-z]+)", t, re.I)
    if subj_m:
        s_val = subj_m.group(1).strip().title()
        if s_val.lower().startswith("eng"):
            s_val = "English"
        ctx["subject"] = s_val

    if re.search(r"Explanation\s+with\s+Reference\s+to\s+the\s+Context", t, re.I):
        ctx["section_hint"] = "Extract / Reference"
    elif re.search(r"\bGrammar\b", t, re.I):
        ctx["section_hint"] = "Grammar"
        ctx["topic"] = "Grammar"

    # Extract Lesson / Chapter name
    # e.g. "Lesson: 2 (Nelson Mandela: Long Walk to Freedom)" or "Lesson 3. Deep Water"
    lesson_m = re.search(
        r"(?:Lesson|Chapter|Unit)\s*[:.]?\s*\d+\s*[\.\:\-]?\s*(?:\(([^)]+)\)|(.+))$",
        t,
        re.IGNORECASE,
    )
    if lesson_m:
        raw_chap = (lesson_m.group(1) or lesson_m.group(2) or "").strip(" .:-()")
        # Remove trailing footer remnants if any
        raw_chap = strip_attached_footers(raw_chap).strip(" .:-()")
        low_chap = raw_chap.lower()
        if low_chap in CHAPTER_CANONICAL_MAP:
            canon_topic, canon_cls = CHAPTER_CANONICAL_MAP[low_chap]
            ctx["topic"] = canon_topic
            if "class_level" not in ctx:
                ctx["class_level"] = canon_cls
        elif raw_chap:
            # Fuzzy match against canonical map keys
            matched = False
            for k, (canon_topic, canon_cls) in CHAPTER_CANONICAL_MAP.items():
                if k in low_chap or low_chap in k:
                    ctx["topic"] = canon_topic
                    if "class_level" not in ctx:
                        ctx["class_level"] = canon_cls
                    matched = True
                    break
            if not matched:
                ctx["topic"] = raw_chap.title() if raw_chap.islower() else raw_chap

    # Check bare book / subchapter names
    low_t = t.lower().strip(" .:-")
    if low_t in CHAPTER_CANONICAL_MAP:
        canon_topic, canon_cls = CHAPTER_CANONICAL_MAP[low_t]
        ctx["topic"] = canon_topic
        if "class_level" not in ctx:
            ctx["class_level"] = canon_cls
    elif "first flight" in low_t or "footprints without feet" in low_t or "foot prints without feet" in low_t:
        if "class_level" not in ctx:
            ctx["class_level"] = "Class 10"
    elif "flamingo" in low_t or "vistas" in low_t:
        if "class_level" not in ctx:
            ctx["class_level"] = "Class 12"
    elif "beehive" in low_t or "moments" in low_t:
        if "class_level" not in ctx:
            ctx["class_level"] = "Class 9"

    return ctx


def infer_class_from_sources(sources: List[str], existing_topic: str = "") -> str:
    """Infers canonical class_level (e.g. 'Class 10') from source filenames or legacy topic."""
    if existing_topic:
        m = LEGACY_CLASS_TOPIC_RE.match(existing_topic.strip())
        if m:
            return f"Class {m.group(1)}"

    for src in sources:
        if not src:
            continue
        m = FILENAME_CLASS_RE.search(src)
        if m:
            return f"Class {m.group(1)}"
        low = src.lower()
        if low in ("most.docx", "modal paper 1.docx"):
            return "Class 10"
    return ""


def infer_subject_from_context(sources: List[str], existing_subject: str = "", text: str = "") -> str:
    if existing_subject and existing_subject.strip():
        return existing_subject.strip()
    joined = " ".join(sources).lower()
    if "physics" in joined:
        return "Physics"
    if "chem" in joined:
        return "Chemistry"
    if "math" in joined:
        return "Mathematics"
    if "bio" in joined:
        return "Biology"
    if "hist" in joined:
        return "History"
    if "english" in joined:
        return "English"
    # Check literature / writing / grammar signals
    low_text = (text or "").lower()
    for pat, _, _ in CHAPTER_KEYWORD_RULES:
        if re.search(pat, low_text):
            return "English"
    if WRITING_PROMPT_RE.search(low_text) or GRAMMAR_PROMPT_RE.search(low_text):
        return "English"
    if any(k in joined for k in ("most.docx", "modal paper 1", "gas paper 10th", "10th", "12th", "11th", "9th")):
        return "English"
    return ""


def infer_question_metadata(
    cleaned_text: str,
    sources: Optional[List[str]] = None,
    existing_subject: str = "",
    existing_topic: str = "",
    existing_class: str = "",
    context_state: Optional[Dict[str, str]] = None,
    explicit_marks: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Infers structured fields for a single cleaned question:
    class_level, subject, topic, question_type, difficulty, default_marks, needs_review, review_reason.
    """
    srcs = sources or []
    ctx = context_state or {}

    # 1. Inspect explicit topic & content-based chapter rules first
    topic = existing_topic.strip() if existing_topic else ""
    if topic and LEGACY_CLASS_TOPIC_RE.match(topic):
        topic = ""
    topic_cls = ""
    if topic.lower() in CHAPTER_CANONICAL_MAP:
        canon_topic, canon_cls = CHAPTER_CANONICAL_MAP[topic.lower()]
        topic = canon_topic
        topic_cls = canon_cls

    low = cleaned_text.lower()
    inferred_chapter = ""
    inferred_chapter_cls = ""
    for pat, chap_name, chap_cls in CHAPTER_KEYWORD_RULES:
        if re.search(pat, low):
            inferred_chapter = chap_name
            inferred_chapter_cls = chap_cls
            break

    # Self-healing: if text strongly matches a canonical NCERT chapter and existing_topic
    # was either empty or an earlier erroneous canonical chapter, trust the question text!
    if inferred_chapter:
        if not topic or (topic in CANONICAL_LITERATURE_TOPICS and topic != inferred_chapter):
            topic = inferred_chapter
    elif not topic and ctx.get("topic"):
        topic = ctx["topic"]

    # 2. Class level: authoritative NCERT chapter class > explicit class > source filename > context
    class_level = canonicalize_class_label(existing_class)
    if inferred_chapter_cls:
        class_level = inferred_chapter_cls
    elif not class_level:
        class_level = (
            topic_cls
            or infer_class_from_sources(srcs, existing_topic=existing_topic)
            or ctx.get("class_level", "")
        )

    # 3. Subject
    subject = infer_subject_from_context(srcs, existing_subject=existing_subject, text=cleaned_text) or ctx.get("subject", "")

    # 4. Question Type & Topic fallback for Grammar / Writing / Extracts
    question_type = ""
    is_bare_writing_stub = (
        not cleaned_text.endswith("?")
        and len(cleaned_text) < 48
        and not re.match(r"^(what|why|how|when|where|who|which|explain|define|describe|state|draw|give|write|justify|discuss|compare|comment|highlight|narrate)\b", low)
        and not inferred_chapter
        and ctx.get("section_hint") != "Extract / Reference"
        and any("class 10th pdf" in s.lower() for s in srcs)
    )
    is_writing_fragment = (
        not inferred_chapter
        and not cleaned_text.endswith("?")
        and bool(re.search(r"\bin about \d+ words\b", low))
        and not re.match(r"^(what|why|how|explain|define|describe|state|draw|give|justify|discuss|compare|comment|highlight|narrate)\b", low)
    )
    if re.search(r"\b(?:option\s*\(?[a-d]\)|choose the correct|\(a\).*\(b\).*\(c\))\b", low):
        question_type = "MCQ"
    elif GRAMMAR_PROMPT_RE.search(cleaned_text):
        question_type = "Grammar"
        if not topic or topic in CANONICAL_LITERATURE_TOPICS or topic == "Writing & Composition":
            topic = "Grammar"
    elif not inferred_chapter and (WRITING_PROMPT_RE.search(cleaned_text) or re.search(r"\(\d{3}\)\s*$", cleaned_text) or is_bare_writing_stub or is_writing_fragment):
        question_type = "Writing / Composition"
        if not topic or topic in CANONICAL_LITERATURE_TOPICS or topic == "Grammar":
            topic = "Writing & Composition"
    elif ctx.get("section_hint") == "Extract / Reference" or (
        not cleaned_text.endswith("?")
        and len(cleaned_text) >= 85
        and not re.match(r"^(what|why|how|explain|define|describe|state|draw|give|write|justify|discuss|compare|comment|highlight|narrate|you are|imagine|as the|mr\.)\b", low)
    ):
        question_type = "Extract / Reference"
    else:
        # Distinguish Long Answer vs Short Answer
        is_long = (
            len(cleaned_text) >= 130
            or cleaned_text.count("?") >= 2
            or bool(re.search(r"\b(character[\s-]*sketch|justify the title|central idea|summary|in about \d+ words|elaborate|explain in detail|describe.*experience)\b", low))
        )
        question_type = "Long Answer" if is_long else "Short Answer"

    # 5. Difficulty
    if question_type in ("Grammar", "MCQ") or (question_type == "Short Answer" and len(cleaned_text) <= 65 and "?" in cleaned_text):
        difficulty = "Easy"
    elif question_type in ("Long Answer", "Writing / Composition", "Extract / Reference") and (len(cleaned_text) >= 135 or cleaned_text.count("?") >= 2):
        difficulty = "Hard"
    else:
        difficulty = "Medium"

    # 6. Default Marks
    if explicit_marks is not None:
        default_marks = float(explicit_marks)
    elif question_type in ("Grammar", "MCQ"):
        default_marks = 1.0
    elif question_type == "Short Answer":
        default_marks = 2.0
    elif question_type == "Extract / Reference":
        default_marks = 4.0
    elif question_type in ("Long Answer", "Writing / Composition"):
        default_marks = 5.0
    else:
        default_marks = 2.0

    # 7. Needs Review detection
    reasons: List[str] = []
    # Check incomplete/truncated fragment
    if cleaned_text and cleaned_text[0].islower() and not cleaned_text.startswith("why "):
        # Note: some valid rows start lowercase like "why does Horace..." or "but after..." (stanza continuation)
        if not re.match(r"^(what|why|how|when|where|who|which|write|explain|describe|draw|give|the )\b", low):
            reasons.append("Starts lowercase / possible fragment")
    if cleaned_text and not re.search(r"[?.!'\")]$", cleaned_text):
        # Short bare writing topic titles won't end in punctuation — flag those separately below
        if len(cleaned_text) >= 48:
            reasons.append("Missing ending punctuation / possibly truncated")
    if len(cleaned_text) < 28 and "?" not in cleaned_text and question_type != "Grammar":
        reasons.append("Very short prompt / stub")
    elif is_bare_writing_stub and not re.search(r"\(\d{3,4}\)\s*$", cleaned_text):
        reasons.append("Bare writing topic title / stub prompt")
    if "matrimonial" in low and ("accident" in low or "post-martem" in low or "traffic jam" in low):
        reasons.append("Merged unrelated writing prompts")

    for pat, msg in OCR_ARTIFACT_PATTERNS:
        if pat.search(cleaned_text):
            if msg not in reasons:
                reasons.append(msg)

    if not topic:
        reasons.append("Missing Chapter/Topic")

    needs_review = len(reasons) > 0
    review_reason = "; ".join(reasons)

    return {
        "class_level": class_level,
        "subject": subject,
        "topic": topic,
        "question_type": question_type,
        "difficulty": difficulty,
        "default_marks": default_marks,
        "needs_review": needs_review,
        "review_reason": review_reason,
    }


def curate_question_library(
    db,
    dry_run: bool = False,
    create_backup: bool = True,
    backup_dir: str = "backups",
) -> Dict[str, Any]:
    """
    Runs Automated Smart Curation across all existing questions in `db` (SQLite or Postgres):
    1. Creates a JSON backup before modifying anything (when not dry_run and create_backup=True).
    2. Scans rows in ID order, propagating adjacent Lesson/Book/Section markers per source stream.
    3. Removes pure Lesson/Book/Section divider rows.
    4. Strips attached footers, trailing markers, trailing OR, normalizes quotes & OCR spaces.
    5. Splits mid-string 'OR'-joined dual questions cleanly.
    6. Infers Class, Subject, Chapter/Topic, Question Type, Difficulty, Default Marks.
    7. Merges duplicates whose normalized text matches after sanitization.
    8. Flags uncertain/broken rows as needs_review=True with review_reason.
    """
    all_rows = db.get_all_questions_for_backup()
    total_before = len(all_rows)

    backup_path = None
    if not dry_run and create_backup:
        os.makedirs(backup_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"pre_curation_backup_{ts}.json")
        with open(backup_path, "w", encoding="utf-8") as bf:
            json.dump(
                {
                    "app": "QuestionBank Studio",
                    "purpose": "pre_curation_backup",
                    "exported_at": datetime.now(timezone.utc).isoformat(),
                    "total_questions": total_before,
                    "questions": all_rows,
                },
                bf,
                indent=2,
                ensure_ascii=False,
            )

    # Track context per primary source filename
    source_contexts: Dict[str, Dict[str, Any]] = {}

    dividers_to_delete: List[Dict[str, Any]] = []
    processed_records: List[Dict[str, Any]] = []
    split_records: List[Dict[str, Any]] = []
    footers_stripped_count = 0
    markers_stripped_count = 0
    or_stripped_count = 0
    or_split_count = 0

    for row in all_rows:
        qid = row["id"]
        raw_text = row.get("question_text") or ""
        sources = row.get("sources") or []
        primary_src = sources[0] if sources else "__manual__"
        ctx = source_contexts.setdefault(primary_src, {"_consecutive_dividers": 0})
        is_sequential_bank = not any("modal" in s.lower() for s in sources)

        # Step A: strip attached footers first and harvest class/subject from footer
        no_footer = strip_attached_footers(normalize_quotes_and_chars(raw_text))
        if no_footer != normalize_quotes_and_chars(raw_text).strip():
            footers_stripped_count += 1
            footer_ctx = extract_context_from_marker(raw_text)
            for k in ("class_level", "subject"):
                if footer_ctx.get(k):
                    ctx[k] = footer_ctx[k]

        # Step B: Check if this entire row is a pure Lesson/Book/Section divider
        is_div, div_text = is_pure_divider(no_footer)
        if is_div:
            ctx["_consecutive_dividers"] = int(ctx.get("_consecutive_dividers", 0)) + 1
            div_ctx = extract_context_from_marker(div_text or no_footer)
            ctx.update({k: v for k, v in div_ctx.items() if v})
            # If this is a broad section divider (Prose/Poetry/Reading/Writing) or a clustered TOC dump (2+ dividers in a row),
            # clear stale chapter topic so the last heading does not poison subsequent chapters.
            if div_text and re.search(r"\b(prose|poetry|writing|reading|literature)\s+section\b", div_text, re.I):
                ctx.pop("topic", None)
            if ctx["_consecutive_dividers"] >= 2 and not div_ctx.get("section_hint"):
                ctx.pop("topic", None)
            # Note: if switching to a new book/prose section, clear stale extract hint unless specified
            if div_text and re.search(r"\b(prose|book:|footprints|vistas)\b", div_text, re.I) and "context" not in div_text.lower():
                ctx.pop("section_hint", None)
            dividers_to_delete.append({"id": qid, "question_text": raw_text})
            continue

        # Step C: Strip trailing attached Lesson/Book/Context markers and save them for NEXT row
        body_no_marker, trailing_marker = strip_trailing_markers(no_footer)
        next_ctx_updates: Dict[str, str] = {}
        if trailing_marker:
            markers_stripped_count += 1
            next_ctx_updates = extract_context_from_marker(trailing_marker)

        # Check again if stripping trailing marker left empty or divider
        is_div2, _ = is_pure_divider(body_no_marker)
        if not body_no_marker or is_div2:
            ctx["_consecutive_dividers"] = int(ctx.get("_consecutive_dividers", 0)) + 1
            if next_ctx_updates:
                ctx.update({k: v for k, v in next_ctx_updates.items() if v})
            if ctx["_consecutive_dividers"] >= 2:
                ctx.pop("topic", None)
            dividers_to_delete.append({"id": qid, "question_text": raw_text})
            continue

        ctx["_consecutive_dividers"] = 0

        # Step D: Strip trailing OR
        body_no_or = strip_trailing_or(body_no_marker)
        if body_no_or != body_no_marker:
            or_stripped_count += 1

        # Step E: Split mid-string 'OR' dual questions (e.g., "Q1? OR Q2?")
        parts = split_or_questions(body_no_or)
        if len(parts) > 1:
            or_split_count += 1

        last_inferred_topic = ""
        for p_idx, part_raw in enumerate(parts):
            part_no_marks, explicit_marks = extract_trailing_marks(part_raw)
            cleaned = clean_question_text(part_no_marks)
            if not cleaned:
                continue
            norm = normalize_question_text(cleaned)
            if not norm:
                continue

            meta = infer_question_metadata(
                cleaned_text=cleaned,
                sources=sources,
                existing_subject=row.get("subject", ""),
                existing_topic=row.get("topic", ""),
                existing_class=row.get("class_level", ""),
                context_state=ctx,
                explicit_marks=explicit_marks if explicit_marks is not None else row.get("default_marks"),
            )
            if meta.get("topic"):
                last_inferred_topic = meta["topic"]

            rec = {
                "orig_id": qid if p_idx == 0 else None,
                "split_from_id": qid if p_idx > 0 else None,
                "original_text": raw_text,
                "question_text": cleaned,
                "normalized_text": norm,
                "frequency": int(row.get("frequency") or 1),
                "sources": list(sources),
                **meta,
            }
            if p_idx == 0:
                processed_records.append(rec)
            else:
                split_records.append(rec)

        # Keep sequential context synchronized across chapter-ordered banks when a chapter changes
        if is_sequential_bank and last_inferred_topic in CANONICAL_LITERATURE_TOPICS and not next_ctx_updates.get("topic"):
            ctx["topic"] = last_inferred_topic

        # Apply trailing marker context updates AFTER processing the current row (for subsequent rows!)
        if next_ctx_updates:
            ctx.update({k: v for k, v in next_ctx_updates.items() if v})
            if trailing_marker and re.search(r"\b(prose|vistas)\b", trailing_marker, re.I) and "context" not in trailing_marker.lower():
                ctx.pop("section_hint", None)

    # Group all cleaned records (including split parts) by normalized_text to detect duplicates
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for rec in processed_records + split_records:
        grouped.setdefault(rec["normalized_text"], []).append(rec)

    merge_groups: List[Dict[str, Any]] = []
    final_upserts: List[Dict[str, Any]] = []
    ids_to_delete: List[int] = [d["id"] for d in dividers_to_delete]
    repoints: List[Tuple[int, int]] = []  # (old_id, keep_id)

    for norm_text, recs in grouped.items():
        # Choose canonical record: prefer highest frequency, then existing orig_id (lowest id), then cleanest capitalization
        recs_with_id = [r for r in recs if r["orig_id"] is not None]
        if recs_with_id:
            recs_with_id.sort(
                key=lambda r: (
                    -r["frequency"],
                    1 if (r["question_text"] and r["question_text"][0].isupper()) else 0,
                    r["orig_id"],
                )
            )
            winner = dict(recs_with_id[0])
            losers = [r for r in recs if r["orig_id"] != winner["orig_id"]]
        else:
            winner = dict(recs[0])
            losers = recs[1:]

        merged_sources = list(winner["sources"])
        total_freq = winner["frequency"]
        loser_ids: List[int] = []

        for l_rec in losers:
            total_freq += l_rec["frequency"]
            for s in l_rec["sources"]:
                if s and s not in merged_sources:
                    merged_sources.append(s)
            for field in ("class_level", "subject", "topic", "question_type", "difficulty"):
                if not winner.get(field) and l_rec.get(field):
                    winner[field] = l_rec[field]
            if winner.get("default_marks") is None and l_rec.get("default_marks") is not None:
                winner["default_marks"] = l_rec["default_marks"]
            if l_rec["orig_id"] is not None:
                loser_ids.append(l_rec["orig_id"])
                ids_to_delete.append(l_rec["orig_id"])
                if winner["orig_id"] is not None:
                    repoints.append((l_rec["orig_id"], winner["orig_id"]))

        winner["frequency"] = total_freq
        winner["sources"] = merged_sources
        final_upserts.append(winner)

        if losers:
            merge_groups.append(
                {
                    "kept_id": winner["orig_id"],
                    "kept_text": winner["question_text"],
                    "merged_ids": loser_ids,
                    "new_frequency": total_freq,
                }
            )

    needs_review_count = sum(1 for r in final_upserts if r["needs_review"])
    modified_text_count = sum(
        1 for r in final_upserts if r["orig_id"] is not None and r["question_text"] != r["original_text"]
    )

    if not dry_run:
        with db.get_connection() as conn:
            cursor = db._get_cursor(conn)

            # 1. Repoint any exam_questions references before deleting merged rows
            for old_id, keep_id in repoints:
                cursor.execute(
                    db._format_query("UPDATE exam_questions SET question_id = ? WHERE question_id = ?"),
                    (keep_id, old_id),
                )

            # 2. Delete pure dividers and merged duplicate loser rows BEFORE updating normalized_text
            # (Prevents UNIQUE(normalized_text) collisions during update!)
            unique_del_ids = sorted(set(ids_to_delete))
            if unique_del_ids:
                chunk_size = 200
                for i in range(0, len(unique_del_ids), chunk_size):
                    chunk = unique_del_ids[i : i + chunk_size]
                    placeholders = ",".join("?" for _ in chunk)
                    cursor.execute(
                        db._format_query(f"DELETE FROM questions WHERE id IN ({placeholders})"),
                        chunk,
                    )

            # 3. Update existing winner rows & insert new split rows
            for rec in final_upserts:
                if rec["orig_id"] is not None:
                    if db.is_postgres:
                        upd_q = """
                            UPDATE questions
                            SET question_text = %s,
                                normalized_text = %s,
                                class_level = %s,
                                subject = %s,
                                topic = %s,
                                question_type = %s,
                                difficulty = %s,
                                default_marks = %s,
                                needs_review = %s,
                                review_reason = %s,
                                frequency = %s,
                                sources = %s,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s
                        """
                        nr_val = bool(rec["needs_review"])
                    else:
                        upd_q = """
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
                        """
                        nr_val = int(bool(rec["needs_review"]))
                    cursor.execute(
                        upd_q,
                        (
                            rec["question_text"],
                            rec["normalized_text"],
                            rec["class_level"],
                            rec["subject"],
                            rec["topic"],
                            rec["question_type"],
                            rec["difficulty"],
                            rec["default_marks"],
                            nr_val,
                            rec["review_reason"],
                            rec["frequency"],
                            json.dumps(rec["sources"]),
                            rec["orig_id"],
                        ),
                    )
                else:
                    if db.is_postgres:
                        ins_q = """
                            INSERT INTO questions
                                (question_text, normalized_text, class_level, subject, topic, question_type,
                                 difficulty, default_marks, needs_review, review_reason, frequency, sources)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """
                        nr_val = bool(rec["needs_review"])
                    else:
                        ins_q = """
                            INSERT INTO questions
                                (question_text, normalized_text, class_level, subject, topic, question_type,
                                 difficulty, default_marks, needs_review, review_reason, frequency, sources)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """
                        nr_val = int(bool(rec["needs_review"]))
                    cursor.execute(
                        ins_q,
                        (
                            rec["question_text"],
                            rec["normalized_text"],
                            rec["class_level"],
                            rec["subject"],
                            rec["topic"],
                            rec["question_type"],
                            rec["difficulty"],
                            rec["default_marks"],
                            nr_val,
                            rec["review_reason"],
                            rec["frequency"],
                            json.dumps(rec["sources"]),
                        ),
                    )

            conn.commit()
            db.invalidate_metadata_cache()

    # Build summary stats
    class_counts: Dict[str, int] = {}
    type_counts: Dict[str, int] = {}
    for r in final_upserts:
        c_key = r["class_level"] or "(Unclassified)"
        t_key = r["question_type"] or "(Unspecified)"
        class_counts[c_key] = class_counts.get(c_key, 0) + 1
        type_counts[t_key] = type_counts.get(t_key, 0) + 1

    return {
        "dry_run": dry_run,
        "backup_path": backup_path,
        "total_before": total_before,
        "total_after": len(final_upserts),
        "dividers_removed": len(dividers_to_delete),
        "duplicates_merged": sum(len(g["merged_ids"]) for g in merge_groups) + (len(split_records) - sum(1 for r in final_upserts if r["orig_id"] is None)),
        "merged_groups_count": len(merge_groups),
        "questions_cleaned": modified_text_count,
        "footers_stripped": footers_stripped_count,
        "markers_stripped": markers_stripped_count,
        "trailing_or_stripped": or_stripped_count,
        "dual_or_split": or_split_count,
        "needs_review_count": needs_review_count,
        "class_breakdown": class_counts,
        "type_breakdown": type_counts,
        "sample_dividers_removed": dividers_to_delete[:15],
        "sample_merges": merge_groups[:15],
        "sample_needs_review": [
            {"id": r["orig_id"], "question_text": r["question_text"], "reason": r["review_reason"]}
            for r in final_upserts
            if r["needs_review"]
        ][:20],
    }


def main():
    parser = argparse.ArgumentParser(description="Smart Question Library Curation Tool (SQLite & PostgreSQL)")
    parser.add_argument("--db", default=None, help="Database path or PostgreSQL URL (defaults to DATABASE_URL or questions.db)")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run preview)")
    parser.add_argument("--no-backup", action="store_true", help="Skip creating JSON backup file before applying")
    args = parser.parse_args()

    from backend.database import Database
    db = Database(args.db)
    report = curate_question_library(db, dry_run=not args.apply, create_backup=not args.no_backup)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
