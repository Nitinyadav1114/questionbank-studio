from pydantic import BaseModel, Field, field_validator
from typing import List, Optional


def _empty_str_to_none(v):
    if isinstance(v, str) and not v.strip():
        return None
    return v


class QuestionResponse(BaseModel):
    id: int
    question_text: str
    class_level: str = ""
    subject: str = ""
    topic: str = ""
    question_type: str = ""
    difficulty: str = ""
    default_marks: Optional[float] = None
    needs_review: bool = False
    review_reason: str = ""
    frequency: int = 1
    sources: List[str] = []
    created_at: str
    updated_at: str


class QuestionCreate(BaseModel):
    question_text: str = Field(..., min_length=1, max_length=50000, description="Text of the question")
    class_level: Optional[str] = Field(default="", max_length=100)
    subject: Optional[str] = Field(default="", max_length=200)
    topic: Optional[str] = Field(default="", max_length=200)
    question_type: Optional[str] = Field(default="", max_length=100)
    difficulty: Optional[str] = Field(default="", max_length=50)
    default_marks: Optional[float] = Field(default=None, ge=0.0, le=1000.0)
    needs_review: Optional[bool] = Field(default=False)
    review_reason: Optional[str] = Field(default="", max_length=500)
    source: Optional[str] = Field(default="Manual Entry", max_length=200)

    _clean_marks = field_validator("default_marks", mode="before")(_empty_str_to_none)


class QuestionUpdate(BaseModel):
    question_text: Optional[str] = Field(default=None, max_length=50000)
    class_level: Optional[str] = Field(default=None, max_length=100)
    subject: Optional[str] = Field(default=None, max_length=200)
    topic: Optional[str] = Field(default=None, max_length=200)
    question_type: Optional[str] = Field(default=None, max_length=100)
    difficulty: Optional[str] = Field(default=None, max_length=50)
    default_marks: Optional[float] = Field(default=None, ge=0.0, le=1000.0)
    clear_default_marks: Optional[bool] = Field(default=False)
    needs_review: Optional[bool] = Field(default=None)
    review_reason: Optional[str] = Field(default=None, max_length=500)

    _clean_marks = field_validator("default_marks", mode="before")(_empty_str_to_none)


class BulkDeleteRequest(BaseModel):
    question_ids: List[int] = Field(..., min_length=1, description="List of question IDs to delete")


class BulkUpdateQuestionsRequest(BaseModel):
    question_ids: List[int] = Field(..., min_length=1, description="List of question IDs to update")
    class_level: Optional[str] = Field(default=None, max_length=100)
    subject: Optional[str] = Field(default=None, max_length=200)
    topic: Optional[str] = Field(default=None, max_length=200)
    question_type: Optional[str] = Field(default=None, max_length=100)
    difficulty: Optional[str] = Field(default=None, max_length=50)
    default_marks: Optional[float] = Field(default=None, ge=0.0, le=1000.0)
    needs_review: Optional[bool] = Field(default=None)
    review_reason: Optional[str] = Field(default=None, max_length=500)

    _clean_marks = field_validator("default_marks", mode="before")(_empty_str_to_none)


class MergeQuestionsRequest(BaseModel):
    target_id: int = Field(..., description="Primary question ID to keep")
    source_ids: List[int] = Field(..., min_length=1, description="Duplicate question IDs to merge into target_id")
    merged_text: Optional[str] = Field(default=None, max_length=50000, description="Optional edited final text for merged question")


class AutoPickRequest(BaseModel):
    class_level: Optional[str] = Field(default="", max_length=100)
    subject: Optional[str] = Field(default="", max_length=200)
    topics: Optional[List[str]] = Field(default=None)
    question_type: Optional[str] = Field(default="", max_length=100)
    difficulty: Optional[str] = Field(default="", max_length=50)
    count: Optional[int] = Field(default=None, ge=1, le=200)
    target_marks: Optional[float] = Field(default=None, ge=1.0, le=2000.0)
    prefer_most_repeated: bool = True
    spread_topics: bool = True
    exclude_needs_review: bool = True
    exclude_ids: Optional[List[int]] = Field(default=None)

    _clean_nums = field_validator("count", "target_marks", mode="before")(_empty_str_to_none)


class PreviewImportItem(BaseModel):
    question_text: str = Field(default="", max_length=50000)
    class_level: Optional[str] = Field(default="", max_length=100)
    subject: Optional[str] = Field(default="", max_length=200)
    topic: Optional[str] = Field(default="", max_length=200)
    question_type: Optional[str] = Field(default="", max_length=100)
    difficulty: Optional[str] = Field(default="", max_length=50)
    default_marks: Optional[float] = Field(default=None, ge=0.0, le=1000.0)
    needs_review: Optional[bool] = Field(default=False)
    review_reason: Optional[str] = Field(default="", max_length=500)
    source_filename: Optional[str] = Field(default="Uploaded File", max_length=300)
    include: bool = True

    _clean_marks = field_validator("default_marks", mode="before")(_empty_str_to_none)


class ConfirmImportRequest(BaseModel):
    items: List[PreviewImportItem] = Field(..., min_length=1)


class ExportItemInput(BaseModel):
    item_type: str = Field(default="question", description="'question' or 'section'")
    question_id: Optional[int] = Field(default=None)
    question_text: Optional[str] = Field(default="", max_length=50000)
    section_title: Optional[str] = Field(default="", max_length=300)
    marks: Optional[float] = Field(default=None, ge=0.0, le=1000.0)

    _clean_marks = field_validator("marks", mode="before")(_empty_str_to_none)


class PaperHeaderConfig(BaseModel):
    institute_name: Optional[str] = Field(default="The Squire's Way", max_length=250)
    exam_title: Optional[str] = Field(default="", max_length=300)
    class_subject: Optional[str] = Field(default="", max_length=250)
    time_allowed: Optional[str] = Field(default="", max_length=100)
    max_marks: Optional[float] = Field(default=None, ge=0.0, le=10000.0)
    instructions: Optional[str] = Field(default="", max_length=5000)
    show_header: bool = True

    _clean_max_marks = field_validator("max_marks", mode="before")(_empty_str_to_none)


class ExportRequest(BaseModel):
    question_ids: List[int] = Field(default_factory=list, description="Ordered list of question IDs to export")
    items: Optional[List[ExportItemInput]] = Field(default=None, description="Optional ordered items with section dividers and per-question marks")
    title: Optional[str] = Field(default="", max_length=300, description="Optional title or header for the document")
    format: Optional[str] = Field(default="docx", description="File format: 'docx' (Word) or 'pdf'")
    use_template: Optional[bool] = Field(default=False, description="Whether to use the Default_page printout template (A4, 0.5in margins, page border)")
    paper_header: Optional[PaperHeaderConfig] = Field(default=None)
    show_marks: bool = True


class UploadSummary(BaseModel):
    filename: str
    extracted: int
    new_added: int
    duplicates_merged: int


class UploadStatsResponse(BaseModel):
    total_files: int
    total_extracted: int
    total_new: int
    total_merged: int
    file_summaries: List[UploadSummary]


class UserResponse(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    is_active: bool = True
    created_at: str
    updated_at: str


class UserLogin(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)


class TokenResponse(BaseModel):
    token: str
    user: UserResponse


class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=150)
    password: str = Field(..., min_length=4, max_length=200)
    role: Optional[str] = Field(default="teacher", description="'admin' or 'teacher'")


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=4, max_length=200)


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=4, max_length=200)


# ==========================================
# Digital Exams & Evaluation Studio Models
# ==========================================

class ExamQuestionInput(BaseModel):
    question_id: Optional[int] = Field(default=None, description="Optional original question ID")
    question_text: str = Field(..., min_length=1, description="Question text prompt")
    marks: float = Field(default=1.0, ge=0.0, description="Marks allocated to this question")
    question_order: Optional[int] = Field(default=1, ge=1, description="Sequential order in exam")
    section_title: Optional[str] = Field(default="", max_length=200, description="Optional section label")


class ExamCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=300, description="Exam title")
    subject: Optional[str] = Field(default="", max_length=200, description="Subject area")
    class_level: Optional[str] = Field(default="", max_length=100, description="Optional class level")
    institute_name: Optional[str] = Field(default="The Squire's Way", max_length=200)
    duration_minutes: int = Field(default=60, ge=1, le=1440, description="Duration in minutes")
    deadline: str = Field(..., description="ISO 8601 or datetime string for exam deadline")
    instructions: Optional[str] = Field(default="", max_length=10000, description="Instructions for students")
    total_marks: Optional[float] = Field(default=None, ge=0.0, description="Total marks (auto-calculated if omitted)")
    questions: List[ExamQuestionInput] = Field(default_factory=list, description="Questions included in this exam")

    _clean_total = field_validator("total_marks", mode="before")(_empty_str_to_none)


class ExamDeadlineUpdateRequest(BaseModel):
    deadline: str = Field(..., description="New ISO 8601 or datetime deadline")
    reopen_if_closed: bool = Field(default=False, description="Re-open closed exam if extending deadline")
    duration_minutes: Optional[int] = Field(default=None, ge=1, le=1440)

    _clean_dur = field_validator("duration_minutes", mode="before")(_empty_str_to_none)


class StudentAnswerInput(BaseModel):
    question_id: int = Field(..., description="Exam question ID")
    typed_answer: Optional[str] = Field(default="", description="Student's typed response")
    image_data: Optional[str] = Field(default="", description="Base64 canvas compressed handwritten answer sheet")


class StudentSubmissionRequest(BaseModel):
    student_name: Optional[str] = Field(default=None, max_length=150)
    full_name: Optional[str] = Field(default=None, max_length=150)
    roll_number: str = Field(..., min_length=1, max_length=100, description="Unique roll number or student ID")
    section: Optional[str] = Field(default="", max_length=50, description="Class section")
    time_taken_seconds: int = Field(default=0, ge=0, description="Time spent in seconds")
    answers: List[StudentAnswerInput] = Field(default_factory=list, description="List of question answers")

    def get_student_name(self) -> str:
        name = (self.student_name or self.full_name or "").strip()
        if not name:
            raise ValueError("Student name or full name is required.")
        return name


class QuestionGradeInput(BaseModel):
    question_id: Optional[int] = Field(default=None, description="Exam question ID")
    exam_question_id: Optional[int] = Field(default=None, description="Alias for question ID")
    marks_awarded: Optional[float] = Field(default=None, ge=0.0)
    awarded_marks: Optional[float] = Field(default=None, ge=0.0)
    feedback: Optional[str] = Field(default="", description="Question level teacher comment")
    teacher_feedback: Optional[str] = Field(default="", description="Alias for feedback")

    def get_question_id(self) -> int:
        qid = self.question_id if self.question_id is not None else self.exam_question_id
        if qid is None:
            raise ValueError("question_id or exam_question_id must be provided.")
        return qid

    def get_marks(self) -> float:
        if self.marks_awarded is not None:
            return float(self.marks_awarded)
        if self.awarded_marks is not None:
            return float(self.awarded_marks)
        return 0.0

    def get_feedback(self) -> str:
        return self.feedback or self.teacher_feedback or ""


class GradeSubmissionRequest(BaseModel):
    grades: Optional[List[QuestionGradeInput]] = None
    answers: Optional[List[QuestionGradeInput]] = None
    overall_feedback: Optional[str] = Field(default="", description="Overall feedback for student")
    is_published: Optional[bool] = Field(default=True, description="Whether to publish grade immediately")

    def get_grades_list(self) -> List[QuestionGradeInput]:
        return self.grades if self.grades is not None else (self.answers or [])


class EmergencySubmissionPayload(BaseModel):
    exam_code: str = Field(..., description="Exam code identifier")
    student_name: str = Field(..., min_length=1, max_length=150)
    roll_number: str = Field(..., min_length=1, max_length=100)
    section: Optional[str] = Field(default="", max_length=50)
    time_taken_seconds: int = Field(default=0, ge=0)
    client_timestamp: str = Field(..., description="ISO 8601 timestamp when client generated the offline package")
    answers: List[StudentAnswerInput] = Field(default_factory=list)
    integrity_hash: str = Field(..., min_length=16, description="SHA-256 signature of the payload")
