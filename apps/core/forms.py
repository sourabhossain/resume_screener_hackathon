import os

from django import forms
from .models import Job, Resume


class FileValidationMixin:
    """
    Mixin for file upload validation (PDF, DOCX).
    Validates file extension, size, and magic bytes.
    """
    
    ALLOWED_EXTENSIONS = ['pdf', 'docx']
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
    MAGIC_BYTES = {
        'pdf': b'%PDF',
        'docx': b'PK\x03\x04',
    }
    
    def validate_resume_file(self, file):
        """Validate file type, size, and content (magic byte check)."""
        if not file:
            return file
        
        # Check file size
        if file.size > self.MAX_FILE_SIZE:
            raise forms.ValidationError('File size must be under 5MB.')
        
        # Check extension using os.path.splitext to handle multi-dot filenames safely
        _, raw_ext = os.path.splitext(file.name)
        ext = raw_ext.lstrip('.').lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            raise forms.ValidationError('Invalid file type. Allowed: PDF or DOCX only.')
        
        # Check magic bytes
        file.seek(0)
        header = file.read(8)
        file.seek(0)
        
        expected_magic = self.MAGIC_BYTES.get(ext)
        if expected_magic and not header.startswith(expected_magic):
            raise forms.ValidationError(
                f'File content does not match {ext.upper()} format. Please upload a valid file.'
            )
        
        return file


class FileSaveMixin:
    """Mixin to handle file metadata on save."""
    
    def save_with_file_metadata(self, commit=True):
        """Save instance with file_name and file_type populated."""
        instance = super().save(commit=False)
        file = self.cleaned_data.get('file')
        if file:
            instance.file_name = file.name
            _, raw_ext = os.path.splitext(file.name)
            instance.file_type = raw_ext.lstrip('.').lower()
        if commit:
            instance.save()
        return instance


class JobForm(forms.ModelForm):
    """Form for creating and editing job descriptions."""

    class Meta:
        model = Job
        fields = [
            'title', 'description', 'status',
            'employment_type', 'location_type', 'location',
            'posted_date', 'closing_date',
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. Senior Python Developer'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-input',
                'placeholder': 'Enter job requirements, responsibilities, and qualifications...',
                'rows': 8
            }),
            'status': forms.Select(attrs={'class': 'form-input'}),
            'employment_type': forms.Select(attrs={'class': 'form-input'}),
            'location_type': forms.Select(attrs={'class': 'form-input'}),
            'location': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. Dhaka, Bangladesh'
            }),
            'posted_date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'closing_date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
        }
        labels = {
            'title': 'Job Title',
            'description': 'Job Description',
            'status': 'Status',
            'employment_type': 'Employment Type',
            'location_type': 'Location Type',
            'location': 'Location',
            'posted_date': 'Posted Date',
            'closing_date': 'Application Deadline',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['posted_date'].required = False
        self.fields['closing_date'].required = False
        self.fields['employment_type'].required = False
        self.fields['location_type'].required = False
        self.fields['location'].required = False
        self.fields['employment_type'].empty_label = 'Select type…'
        self.fields['location_type'].empty_label = 'Select type…'

    def clean(self):
        data = super().clean()
        posted = data.get('posted_date')
        closing = data.get('closing_date')
        if posted and closing and closing < posted:
            self.add_error('closing_date', 'Application deadline cannot be before the posted date.')
        return data


class ResumeForm(FileValidationMixin, FileSaveMixin, forms.ModelForm):
    """Form for creating and editing resumes - only name and file required, AI handles the rest."""

    class Meta:
        model = Resume
        fields = ['candidate_name', 'email', 'phone', 'file']
        widgets = {
            'candidate_name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Enter candidate full name'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-input',
                'placeholder': 'candidate@example.com'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': '+880 1XXX-XXXXXX'
            }),
            'file': forms.FileInput(attrs={
                'class': 'form-input-file',
                'accept': '.pdf,.docx'
            }),
        }
        labels = {
            'candidate_name': 'Candidate Name',
            'email': 'Email Address',
            'phone': 'Phone Number',
            'file': 'Resume File',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = False
        self.fields['phone'].required = False
    
    def clean_file(self):
        """Validate uploaded file using mixin."""
        return self.validate_resume_file(self.cleaned_data.get('file'))
    
    def save(self, commit=True):
        """Save with file metadata using mixin."""
        return self.save_with_file_metadata(commit)


class ResumeEditForm(FileValidationMixin, FileSaveMixin, forms.ModelForm):
    """Form for editing resumes - includes AI-generated fields that can be manually adjusted."""

    class Meta:
        model = Resume
        fields = ['candidate_name', 'email', 'phone', 'file',
                  'experience_score', 'education_score', 'skills_score',
                  'certification_score', 'achievement_score', 'final_score']
        widgets = {
            'candidate_name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Enter candidate full name'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-input',
                'placeholder': 'candidate@example.com'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': '+880 1XXX-XXXXXX'
            }),
            'file': forms.FileInput(attrs={
                'class': 'form-input-file',
                'accept': '.pdf,.docx'
            }),
            'experience_score': forms.NumberInput(attrs={
                'class': 'form-input',
                'step': '0.1', 'min': '0', 'max': '100',
                'placeholder': '0-100'
            }),
            'education_score': forms.NumberInput(attrs={
                'class': 'form-input',
                'step': '0.1', 'min': '0', 'max': '100',
                'placeholder': '0-100'
            }),
            'skills_score': forms.NumberInput(attrs={
                'class': 'form-input',
                'step': '0.1', 'min': '0', 'max': '100',
                'placeholder': '0-100'
            }),
            'certification_score': forms.NumberInput(attrs={
                'class': 'form-input',
                'step': '0.1', 'min': '0', 'max': '100',
                'placeholder': '0-100'
            }),
            'achievement_score': forms.NumberInput(attrs={
                'class': 'form-input',
                'step': '0.1', 'min': '0', 'max': '100',
                'placeholder': '0-100'
            }),
            'final_score': forms.NumberInput(attrs={
                'class': 'form-input',
                'step': '0.1', 'min': '0', 'max': '100',
                'placeholder': '0-100'
            }),
        }
        labels = {
            'candidate_name': 'Candidate Name',
            'email': 'Email Address',
            'phone': 'Phone Number',
            'file': 'Resume File',
            'experience_score': 'Experience Score',
            'education_score': 'Education Score',
            'skills_score': 'Skills Score',
            'certification_score': 'Certification Score',
            'achievement_score': 'Achievement Score',
            'final_score': 'Final Score',
        }
    
    def clean_file(self):
        """Validate uploaded file using mixin."""
        return self.validate_resume_file(self.cleaned_data.get('file'))
    
    def save(self, commit=True):
        """Save with file metadata using mixin."""
        return self.save_with_file_metadata(commit)
