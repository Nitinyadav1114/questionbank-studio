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
