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


class LLMClientError(ResumeScreeningError):
    """Raised when LLM API call fails."""
    
    def __init__(self, message: str, response: str = None):
        self.response = response
        super().__init__(message)


class InvalidFileTypeError(ResumeScreeningError):
    """Raised when an unsupported file type is uploaded."""
    
    def __init__(self, file_type: str, supported_types: list = None):
        self.file_type = file_type
        self.supported_types = supported_types or ['pdf', 'doc', 'docx']
        message = f"Unsupported file type: {file_type}. Supported: {', '.join(self.supported_types)}"
        super().__init__(message)


class FileTooLargeError(ResumeScreeningError):
    """Raised when uploaded file exceeds size limit."""
    
    def __init__(self, size: int, max_size: int):
        self.size = size
        self.max_size = max_size
        message = f"File size {size / (1024*1024):.2f}MB exceeds limit of {max_size / (1024*1024):.2f}MB"
        super().__init__(message)


class InvalidFileContentError(ResumeScreeningError):
    """Raised when file content doesn't match its extension (magic byte validation)."""
    
    def __init__(self, expected_type: str, actual_signature: str = None):
        self.expected_type = expected_type
        self.actual_signature = actual_signature
        message = f"File content does not match {expected_type} format"
        super().__init__(message)


class JobNotActiveError(ResumeScreeningError):
    """Raised when trying to add resume to non-active job."""
    
    def __init__(self, job_id: int, job_status: str):
        self.job_id = job_id
        self.job_status = job_status
        message = f"Cannot add resume to job {job_id}: Job status is {job_status}"
        super().__init__(message)


class MissingJobDescriptionError(ResumeScreeningError):
    """Raised when job description is missing for screening."""
    
    def __init__(self, job_id: int):
        self.job_id = job_id
        message = f"Job {job_id} has no description for AI screening"
        super().__init__(message)
