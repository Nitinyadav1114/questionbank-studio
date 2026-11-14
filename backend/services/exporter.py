import io
import os
import xml.sax.saxutils as saxutils
from copy import deepcopy
from typing import List, Dict, Any, Optional

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

from backend.services.dedup import clean_question_text

DEFAULT_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "templates",
    "default_template.docx"
)

def generate_word_document(
    questions: List[Dict[str, Any]],
    title: Optional[str] = None,
    use_template: bool = False
) -> io.BytesIO:
    """
    Generates an editable Word document (.docx) containing the selected questions.
    If use_template is True, opens Default_page.docx to preserve:
    - The diagonal 'The Squire's Way' watermark
    - The double-line page border
    - A4 page dimensions
    - 0.5-inch margins
    Uses Word's native 'List Number' style so users can press Enter and continue the list.
    """
    font_name = "Calibri"

    if use_template and os.path.exists(DEFAULT_TEMPLATE_PATH):
        try:
            # Load template directly so all header VML watermark relationships and page borders are preserved
            doc = Document(DEFAULT_TEMPLATE_PATH)
            font_name = "Times New Roman"

            # Ensure 'List Number' style exists in doc.styles
            try:
                _ = doc.styles['List Number']
            except KeyError:
                fresh_doc = Document()
                list_style_elm = fresh_doc.styles['List Number']._element
                doc.styles._element.append(deepcopy(list_style_elm))

            # Remove empty placeholder paragraphs if present in template
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
        # Standard 1-inch margins for Normal mode
        doc = Document()
        for s in doc.sections:
            s.top_margin = Inches(1.0)
            s.bottom_margin = Inches(1.0)
            s.left_margin = Inches(1.0)
            s.right_margin = Inches(1.0)

    # Optional Title/Header
    if title and title.strip():
        title_para = doc.add_paragraph()
        title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title_para.paragraph_format.space_after = Pt(14 if use_template else 18)
        title_run = title_para.add_run(title.strip())
        title_run.font.name = font_name
        title_run.font.size = Pt(15 if use_template else 16)
        title_run.font.bold = True
        title_run.font.color.rgb = RGBColor(17, 24, 39)

    # Render each question using Word's native 'List Number' style
    for q in questions:
        raw_text = q.get("question_text", "").strip()
        q_text = clean_question_text(raw_text) or raw_text

        para = doc.add_paragraph(style="List Number")
        para.paragraph_format.space_before = Pt(0)
        para.paragraph_format.space_after = Pt(6 if use_template else 8)
        para.paragraph_format.line_spacing = 1.15

        # Question text run
        text_run = para.add_run(q_text)
        text_run.font.name = font_name
        text_run.font.size = Pt(11 if use_template else 12)
        text_run.font.bold = False
        text_run.font.color.rgb = RGBColor(31, 41, 55)

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
    canvas.setFillColor(colors.HexColor('#747070'), alpha=0.22)
    canvas.setFont('Times-BoldItalic', 54)
    canvas.drawCentredString(0, 0, "The Squire's Way")
    canvas.restoreState()

    # 2. Double-line Page Border
    canvas.setStrokeColor(colors.HexColor('#1f2937'))
    # Outer thicker border line
    canvas.setLineWidth(1.4)
    m = 24  # 24pt offset from page edge
    canvas.rect(m, m, doc.pagesize[0] - 2 * m, doc.pagesize[1] - 2 * m)

    # Inner thinner border line
    canvas.setLineWidth(0.6)
    m2 = m + 3.5
    canvas.rect(m2, m2, doc.pagesize[0] - 2 * m2, doc.pagesize[1] - 2 * m2)

    canvas.restoreState()

def generate_pdf_document(
    questions: List[Dict[str, Any]],
    title: Optional[str] = None,
    use_template: bool = False
) -> io.BytesIO:
    """
    Generates a clean PDF document (.pdf) containing the questions cleanly numbered.
    If use_template is True:
    - Uses A4 page size
    - Uses 0.5-inch (36pt) margins
    - Draws 'The Squire's Way' diagonal watermark and double-line page border
    - Uses Times-Roman typography
    """
    buffer = io.BytesIO()

    page_size = A4 if use_template else letter
    margin = 36 if use_template else 72  # 0.5 inch vs 1.0 inch
    font_family = 'Times-Roman' if use_template else 'Helvetica'
    font_bold = 'Times-Bold' if use_template else 'Helvetica-Bold'

    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName=font_bold,
        fontSize=15 if use_template else 16,
        leading=19,
        alignment=1, # Center
        textColor=colors.HexColor('#111827'),
        spaceAfter=14 if use_template else 18
    )

    q_style = ParagraphStyle(
        'QuestionItem',
        parent=styles['Normal'],
        fontName=font_family,
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#1f2937'),
        spaceAfter=5 if use_template else 7
    )

    story = []

    if title and title.strip():
        story.append(Paragraph(saxutils.escape(title.strip()), title_style))
        story.append(Spacer(1, 8))

    for idx, q in enumerate(questions, start=1):
        raw_text = q.get("question_text", "").strip()
        cleaned_text = clean_question_text(raw_text) or raw_text
        safe_text = saxutils.escape(cleaned_text)

        story.append(Paragraph(f"<b>{idx}.</b> &nbsp; {safe_text}", q_style))
        story.append(Spacer(1, 3))

    if use_template:
        doc.build(story, onFirstPage=_draw_template_decorations, onLaterPages=_draw_template_decorations)
    else:
        doc.build(story)

    buffer.seek(0)
    return buffer
