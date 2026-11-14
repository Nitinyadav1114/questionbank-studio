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
    question_text: str = Field(..., min_length=1, description="Text of the question")
    subject: Optional[str] = ""
    topic: Optional[str] = ""
    source: Optional[str] = "Manual Entry"

class QuestionUpdate(BaseModel):
    question_text: Optional[str] = None
    subject: Optional[str] = None
    topic: Optional[str] = None

class BulkDeleteRequest(BaseModel):
    question_ids: List[int] = Field(..., min_length=1, description="List of question IDs to delete")

class ExportRequest(BaseModel):
    question_ids: List[int] = Field(..., min_length=1, description="Ordered list of question IDs to export")
    title: Optional[str] = Field(default="", description="Optional title or header for the document")
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
