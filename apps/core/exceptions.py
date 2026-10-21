"""
Custom exceptions for the Resume Screening System.
Provides granular error handling for different failure scenarios.
"""


class ResumeScreeningError(Exception):
    """Base exception for all resume screening errors."""
    pass


class DocumentExtractionError(ResumeScreeningError):
    """Raised when text extraction from a document fails."""

    def __init__(self, message: str, file_path: str = None):
        self.file_path = file_path
        super().__init__(message)


class AIScreeningError(ResumeScreeningError):
    """Raised when AI screening fails."""

    def __init__(self, message: str, stage: str = None):
        self.stage = stage
        super().__init__(message)


class MissingJobDescriptionError(ResumeScreeningError):
    """Raised when job description is missing for screening."""

    def __init__(self, job_id: int):
        self.job_id = job_id
        message = f"Job {job_id} has no description for AI screening"
        super().__init__(message)
