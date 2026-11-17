from pydantic import BaseModel, Field
from typing import List, Optional

class QuestionResponse(BaseModel):
    id: int
    question_text: str
    subject: str = ""
    topic: str = ""
    frequency: int = 1
    sources: List[str] = []
    created_at: str
    updated_at: str

class QuestionCreate(BaseModel):
    question_text: str = Field(..., min_length=1, max_length=50000, description="Text of the question")
    subject: Optional[str] = Field(default="", max_length=200)
    topic: Optional[str] = Field(default="", max_length=200)
    source: Optional[str] = Field(default="Manual Entry", max_length=200)

class QuestionUpdate(BaseModel):
    question_text: Optional[str] = Field(default=None, max_length=50000)
    subject: Optional[str] = Field(default=None, max_length=200)
    topic: Optional[str] = Field(default=None, max_length=200)

class BulkDeleteRequest(BaseModel):
    question_ids: List[int] = Field(..., min_length=1, description="List of question IDs to delete")

class ExportRequest(BaseModel):
    question_ids: List[int] = Field(..., min_length=1, description="Ordered list of question IDs to export")
    title: Optional[str] = Field(default="", max_length=300, description="Optional title or header for the document")
    format: Optional[str] = Field(default="docx", description="File format: 'docx' (Word) or 'pdf'")
    use_template: Optional[bool] = Field(default=False, description="Whether to use the Default_page printout template (A4, 0.5in margins, page border)")

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


class ExamCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=300, description="Exam title")
    subject: Optional[str] = Field(default="", max_length=200, description="Subject area")
    duration_minutes: int = Field(default=60, ge=1, le=1440, description="Duration in minutes")
    deadline: str = Field(..., description="ISO 8601 or datetime string for exam deadline")
    instructions: Optional[str] = Field(default="", max_length=10000, description="Instructions for students")
    total_marks: Optional[float] = Field(default=None, ge=0.0, description="Total marks (auto-calculated if omitted)")
    questions: List[ExamQuestionInput] = Field(default_factory=list, description="Questions included in this exam")


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
