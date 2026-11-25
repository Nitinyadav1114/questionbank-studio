import io
import os
import xml.sax.saxutils as saxutils
from copy import deepcopy
from typing import List, Dict, Any, Optional

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

from backend.services.dedup import clean_question_text

DEFAULT_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "templates",
    "default_template.docx"
)


def _format_marks_str(marks: Optional[float]) -> str:
    if marks is None:
        return ""
    val = float(marks)
    if val.is_integer():
        return str(int(val))
    return f"{val:.1f}".rstrip("0").rstrip(".")


def _compute_total_marks(questions: List[Dict[str, Any]]) -> float:
    total = 0.0
    for q in questions:
        if q.get("item_type") == "section":
            continue
        m = q.get("marks")
        if m is not None:
            total += float(m)
    return round(total, 2)


def _resolve_max_marks(hdr: Dict[str, Any], show_hdr: bool, computed_max: float) -> Optional[float]:
    if show_hdr and hdr.get("max_marks") not in (None, ""):
        try:
            val = float(hdr["max_marks"])
            if val > 0:
                return val
        except (TypeError, ValueError):
            pass
    return computed_max if computed_max > 0 else None


def _set_docx_bottom_border(paragraph, color_hex: str = "1F2937", sz: str = "8"):
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), sz)
    bottom.set(qn("w:space"), "4")
    bottom.set(qn("w:color"), color_hex)
    pBdr.append(bottom)
    pPr.append(pBdr)


def generate_word_document(
    questions: List[Dict[str, Any]],
    title: Optional[str] = None,
    use_template: bool = False,
    paper_header: Optional[Dict[str, Any]] = None,
    show_marks: bool = True,
) -> io.BytesIO:
    """
    Generates an editable Word document (.docx) containing an optional School Paper Header,
    section dividers, and numbered questions with optional [marks].
    If use_template is True, opens default_template.docx to preserve:
    - The diagonal 'The Squire's Way' watermark
    - The double-line page border
    - A4 page dimensions
    - 0.5-inch margins
    Uses Word's native 'List Number' style so users can press Enter and continue the list.
    """
    font_name = "Calibri"

    if use_template and os.path.exists(DEFAULT_TEMPLATE_PATH):
        try:
            doc = Document(DEFAULT_TEMPLATE_PATH)
            font_name = "Times New Roman"

            try:
                _ = doc.styles["List Number"]
            except KeyError:
                fresh_doc = Document()
                list_style_elm = fresh_doc.styles["List Number"]._element
                doc.styles._element.append(deepcopy(list_style_elm))

            while doc.paragraphs and not doc.paragraphs[0].text.strip():
                p = doc.paragraphs[0]
                p._element.getparent().remove(p._element)

        except Exception as e:
            print(f"Warning: Failed to load template {DEFAULT_TEMPLATE_PATH}: {e}")
            doc = Document()
            for s in doc.sections:
                s.top_margin = Inches(1.0)
                s.bottom_margin = Inches(1.0)
                s.left_margin = Inches(1.0)
                s.right_margin = Inches(1.0)
    else:
        doc = Document()
        for s in doc.sections:
            s.top_margin = Inches(1.0)
            s.bottom_margin = Inches(1.0)
            s.left_margin = Inches(1.0)
            s.right_margin = Inches(1.0)

    hdr = paper_header or {}
    show_hdr = bool(hdr.get("show_header", True)) if paper_header else False
    inst_name = (hdr.get("institute_name") or "The Squire's Way").strip() if show_hdr else ""
    exam_title = (hdr.get("exam_title") or title or "").strip()
    class_subject = (hdr.get("class_subject") or "").strip() if show_hdr else ""
    time_allowed = (hdr.get("time_allowed") or "").strip() if show_hdr else ""
    instructions = (hdr.get("instructions") or "").strip() if show_hdr else ""
    computed_max = _compute_total_marks(questions)
    max_marks_val = _resolve_max_marks(hdr, show_hdr, computed_max)

    if show_hdr and (inst_name or exam_title or class_subject or time_allowed or max_marks_val or instructions):
        if inst_name:
            inst_p = doc.add_paragraph()
            inst_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            inst_p.paragraph_format.space_before = Pt(0)
            inst_p.paragraph_format.space_after = Pt(2)
            r_inst = inst_p.add_run(inst_name)
            r_inst.font.name = font_name
            r_inst.font.size = Pt(16 if use_template else 17)
            r_inst.font.bold = True
            r_inst.font.color.rgb = RGBColor(17, 24, 39)

        if exam_title:
            title_p = doc.add_paragraph()
            title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            title_p.paragraph_format.space_before = Pt(0)
            title_p.paragraph_format.space_after = Pt(4)
            r_title = title_p.add_run(exam_title)
            r_title.font.name = font_name
            r_title.font.size = Pt(13 if use_template else 14)
            r_title.font.bold = True
            r_title.font.color.rgb = RGBColor(31, 41, 55)

        meta_parts = []
        if class_subject:
            meta_parts.append(class_subject)
        if time_allowed:
            meta_parts.append(f"Time: {time_allowed}")
        if max_marks_val is not None and max_marks_val > 0:
            meta_parts.append(f"Max. Marks: {_format_marks_str(max_marks_val)}")

        if meta_parts:
            meta_p = doc.add_paragraph()
            meta_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            meta_p.paragraph_format.space_before = Pt(2)
            meta_p.paragraph_format.space_after = Pt(6)
            r_meta = meta_p.add_run("   |   ".join(meta_parts))
            r_meta.font.name = font_name
            r_meta.font.size = Pt(10.5)
            r_meta.font.bold = True
            r_meta.font.color.rgb = RGBColor(55, 65, 81)
            if not instructions:
                _set_docx_bottom_border(meta_p)
        elif exam_title or inst_name:
            # Put subtle border under last header line if no instructions
            if not instructions:
                _set_docx_bottom_border(title_p if exam_title else inst_p)

        if instructions:
            inst_box = doc.add_paragraph()
            inst_box.paragraph_format.space_before = Pt(2)
            inst_box.paragraph_format.space_after = Pt(10)
            r_lbl = inst_box.add_run("General Instructions: ")
            r_lbl.font.name = font_name
            r_lbl.font.size = Pt(10)
            r_lbl.font.bold = True
            r_lbl.font.italic = True
            r_lbl.font.color.rgb = RGBColor(55, 65, 81)

            r_body = inst_box.add_run(instructions)
            r_body.font.name = font_name
            r_body.font.size = Pt(10)
            r_body.font.italic = True
            r_body.font.color.rgb = RGBColor(75, 85, 99)
            _set_docx_bottom_border(inst_box)
        else:
            spacer_p = doc.add_paragraph()
            spacer_p.paragraph_format.space_before = Pt(0)
            spacer_p.paragraph_format.space_after = Pt(4)

    elif title and title.strip():
        title_para = doc.add_paragraph()
        title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title_para.paragraph_format.space_after = Pt(14 if use_template else 18)
        title_run = title_para.add_run(title.strip())
        title_run.font.name = font_name
        title_run.font.size = Pt(15 if use_template else 16)
        title_run.font.bold = True
        title_run.font.color.rgb = RGBColor(17, 24, 39)

    for q in questions:
        if q.get("item_type") == "section":
            sec_title = (q.get("section_title") or q.get("question_text") or "").strip()
            if not sec_title:
                continue
            sec_p = doc.add_paragraph()
            sec_p.paragraph_format.space_before = Pt(10)
            sec_p.paragraph_format.space_after = Pt(4)
            sec_p.paragraph_format.keep_with_next = True
            sec_run = sec_p.add_run(sec_title)
            sec_run.font.name = font_name
            sec_run.font.size = Pt(11.5 if use_template else 12)
            sec_run.font.bold = True
            sec_run.font.color.rgb = RGBColor(17, 24, 39)
            continue

        raw_text = (q.get("question_text") or "").strip()
        q_text = clean_question_text(raw_text) or raw_text
        if not q_text:
            continue

        para = doc.add_paragraph(style="List Number")
        para.paragraph_format.space_before = Pt(0)
        para.paragraph_format.space_after = Pt(6 if use_template else 8)
        para.paragraph_format.line_spacing = 1.15

        text_run = para.add_run(q_text)
        text_run.font.name = font_name
        text_run.font.size = Pt(11 if use_template else 12)
        text_run.font.bold = False
        text_run.font.color.rgb = RGBColor(31, 41, 55)

        q_marks = q.get("marks")
        if show_marks and q_marks is not None and float(q_marks) > 0:
            marks_run = para.add_run(f"   [{_format_marks_str(q_marks)}]")
            marks_run.font.name = font_name
            marks_run.font.size = Pt(10.5 if use_template else 11)
            marks_run.font.bold = True
            marks_run.font.color.rgb = RGBColor(55, 65, 81)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer


def _draw_template_decorations(canvas, doc):
    """
    Draws the template's exact visual elements on the PDF:
    1. Diagonal watermark: 'The Squire's Way' in Times-BoldItalic
    2. Double-line page border matching the thickThinSmallGap Word style
    """
    canvas.saveState()

    # 1. Diagonal Watermark "The Squire's Way" across page center
    canvas.saveState()
    canvas.translate(doc.pagesize[0] / 2.0, doc.pagesize[1] / 2.0)
    canvas.rotate(45)
    canvas.setFillColor(colors.HexColor("#747070"), alpha=0.22)
    canvas.setFont("Times-BoldItalic", 54)
    canvas.drawCentredString(0, 0, "The Squire's Way")
    canvas.restoreState()

    # 2. Double-line Page Border
    canvas.setStrokeColor(colors.HexColor("#1f2937"))
    canvas.setLineWidth(1.4)
    m = 24
    canvas.rect(m, m, doc.pagesize[0] - 2 * m, doc.pagesize[1] - 2 * m)

    canvas.setLineWidth(0.6)
    m2 = m + 3.5
    canvas.rect(m2, m2, doc.pagesize[0] - 2 * m2, doc.pagesize[1] - 2 * m2)

    canvas.restoreState()


def generate_pdf_document(
    questions: List[Dict[str, Any]],
    title: Optional[str] = None,
    use_template: bool = False,
    paper_header: Optional[Dict[str, Any]] = None,
    show_marks: bool = True,
) -> io.BytesIO:
    """
    Generates a clean PDF document (.pdf) containing an optional School Paper Header,
    section dividers, and numbered questions with optional [marks].
    """
    buffer = io.BytesIO()

    page_size = A4 if use_template else letter
    margin = 36 if use_template else 72
    font_family = "Times-Roman" if use_template else "Helvetica"
    font_bold = "Times-Bold" if use_template else "Helvetica-Bold"
    font_italic = "Times-Italic" if use_template else "Helvetica-Oblique"

    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
    )

    styles = getSampleStyleSheet()

    inst_style = ParagraphStyle(
        "InstHeader",
        parent=styles["Heading1"],
        fontName=font_bold,
        fontSize=16 if use_template else 17,
        leading=20,
        alignment=1,
        textColor=colors.HexColor("#111827"),
        spaceAfter=2,
    )

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontName=font_bold,
        fontSize=13 if (paper_header and paper_header.get("show_header", True)) else (15 if use_template else 16),
        leading=17,
        alignment=1,
        textColor=colors.HexColor("#111827"),
        spaceAfter=6 if paper_header else (14 if use_template else 18),
    )

    meta_style = ParagraphStyle(
        "MetaStrip",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=10,
        leading=14,
        alignment=1,
        textColor=colors.HexColor("#374151"),
        spaceAfter=4,
    )

    inst_notes_style = ParagraphStyle(
        "InstructionsNote",
        parent=styles["Normal"],
        fontName=font_italic,
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor("#4b5563"),
        spaceAfter=6,
    )

    section_style = ParagraphStyle(
        "SectionDivider",
        parent=styles["Heading2"],
        fontName=font_bold,
        fontSize=11.5,
        leading=15,
        textColor=colors.HexColor("#111827"),
        spaceBefore=10,
        spaceAfter=4,
    )

    q_style = ParagraphStyle(
        "QuestionItem",
        parent=styles["Normal"],
        fontName=font_family,
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#1f2937"),
        spaceAfter=5 if use_template else 7,
    )

    story = []

    hdr = paper_header or {}
    show_hdr = bool(hdr.get("show_header", True)) if paper_header else False
    inst_name = (hdr.get("institute_name") or "The Squire's Way").strip() if show_hdr else ""
    exam_title = (hdr.get("exam_title") or title or "").strip()
    class_subject = (hdr.get("class_subject") or "").strip() if show_hdr else ""
    time_allowed = (hdr.get("time_allowed") or "").strip() if show_hdr else ""
    instructions = (hdr.get("instructions") or "").strip() if show_hdr else ""
    computed_max = _compute_total_marks(questions)
    max_marks_val = _resolve_max_marks(hdr, show_hdr, computed_max)

    if show_hdr and (inst_name or exam_title or class_subject or time_allowed or max_marks_val or instructions):
        if inst_name:
            story.append(Paragraph(saxutils.escape(inst_name), inst_style))
        if exam_title:
            story.append(Paragraph(saxutils.escape(exam_title), title_style))

        meta_parts = []
        if class_subject:
            meta_parts.append(saxutils.escape(class_subject))
        if time_allowed:
            meta_parts.append(f"Time: {saxutils.escape(time_allowed)}")
        if max_marks_val is not None and max_marks_val > 0:
            meta_parts.append(f"Max. Marks: {_format_marks_str(max_marks_val)}")
        if meta_parts:
            story.append(Paragraph(" &nbsp;|&nbsp; ".join(meta_parts), meta_style))

        if instructions:
            story.append(Paragraph(f"<b>General Instructions:</b> {saxutils.escape(instructions)}", inst_notes_style))

        story.append(HRFlowable(width="100%", thickness=1.0, color=colors.HexColor("#1f2937"), spaceBefore=2, spaceAfter=10))
    elif title and title.strip():
        story.append(Paragraph(saxutils.escape(title.strip()), title_style))
        story.append(Spacer(1, 8))

    q_num = 0
    for q in questions:
        if q.get("item_type") == "section":
            sec_title = (q.get("section_title") or q.get("question_text") or "").strip()
            if sec_title:
                story.append(Paragraph(saxutils.escape(sec_title), section_style))
            continue

        raw_text = (q.get("question_text") or "").strip()
        cleaned_text = clean_question_text(raw_text) or raw_text
        if not cleaned_text:
            continue
        q_num += 1
        safe_text = saxutils.escape(cleaned_text)

        q_marks = q.get("marks")
        marks_suffix = ""
        if show_marks and q_marks is not None and float(q_marks) > 0:
            marks_suffix = f" &nbsp; <b>[{_format_marks_str(q_marks)}]</b>"

        story.append(Paragraph(f"<b>{q_num}.</b> &nbsp; {safe_text}{marks_suffix}", q_style))
        story.append(Spacer(1, 3))

    if use_template:
        doc.build(story, onFirstPage=_draw_template_decorations, onLaterPages=_draw_template_decorations)
    else:
        doc.build(story)

    buffer.seek(0)
    return buffer
