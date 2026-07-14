import os

from django import forms
from .form_utils import AriaInvalidMixin, clean_label_text, clean_person_text, clean_phone_text
from .models import Job, Resume

class FileValidationMixin:
    """
    Mixin for file upload validation (PDF, DOCX).
    Validates file extension, size, and magic bytes.
    """
    
    ALLOWED_EXTENSIONS = ['pdf', 'docx']
    MAX_FILE_SIZE = 5 * 1024 * 1024
    MAGIC_BYTES = {
        'pdf': b'%PDF',
        'docx': b'PK\x03\x04',
    }
    
    def validate_resume_file(self, file):
        """Validate file type, size, and content (magic byte check)."""
        if not file:
            return file
        
        if file.size > self.MAX_FILE_SIZE:
            raise forms.ValidationError('File size must be under 5MB.')
        
        _, raw_ext = os.path.splitext(file.name)
        ext = raw_ext.lstrip('.').lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            raise forms.ValidationError('Invalid file type. Allowed: PDF or DOCX only.')
        
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

class JobForm(AriaInvalidMixin, forms.ModelForm):
    """Form for creating and editing job descriptions."""

    required_skills_text = forms.CharField(
        required=False, label='Required skills',
        help_text='Comma-separated must-have skills the AI screens against (e.g. Python, Django, MySQL).',
        widget=forms.Textarea(attrs={'class': 'form-input', 'rows': 2,
                                     'placeholder': 'Python, Django, REST APIs, MySQL'}),
    )
    required_education_text = forms.CharField(
        required=False, label='Required education',
        help_text='Comma-separated (e.g. Bachelor, Computer Science).',
        widget=forms.TextInput(attrs={'class': 'form-input',
                                      'placeholder': 'Bachelor, Computer Science'}),
    )

    class Meta:
        model = Job
        fields = [
            'title', 'description', 'status',
            'employment_type', 'location_type', 'location',
            'posted_date', 'closing_date', 'required_experience',
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
            'required_experience': forms.NumberInput(attrs={'class': 'form-input', 'min': 0,
                                                            'step': '0.5', 'placeholder': 'e.g. 5'}),
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
            'required_experience': 'Required experience (years)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['title'].required = True
        self.fields['title'].error_messages['required'] = 'Please enter a job title.'
        self.fields['description'].required = True
        self.fields['description'].error_messages['required'] = 'Please enter a job description.'
        self.fields['posted_date'].required = False
        self.fields['closing_date'].required = False
        self.fields['employment_type'].required = False
        self.fields['location_type'].required = False
        self.fields['location'].required = False
        self.fields['required_experience'].required = False
        self.fields['employment_type'].choices = [('', 'Select employment type…')] + list(Job.EMPLOYMENT_TYPE_CHOICES)
        self.fields['location_type'].choices = [('', 'Select location type…')] + list(Job.LOCATION_TYPE_CHOICES)
        if self.instance and self.instance.pk:
            self.fields['required_skills_text'].initial = ', '.join(self.instance.required_skills or [])
            self.fields['required_education_text'].initial = ', '.join(self.instance.required_education or [])

    @staticmethod
    def _split_csv(text):
        return [s.strip() for s in (text or '').split(',') if s.strip()]

    def clean(self):
        data = super().clean()
        posted = data.get('posted_date')
        closing = data.get('closing_date')
        if posted and closing and closing < posted:
            self.add_error('closing_date', 'Application deadline cannot be before the posted date.')
        return data

    def clean_title(self):
        return clean_label_text(self.cleaned_data.get('title'), required=True)

    def clean_location(self):
        return clean_label_text(self.cleaned_data.get('location'))

    def save(self, commit=True):
        job = super().save(commit=False)
        job.required_skills = self._split_csv(self.cleaned_data.get('required_skills_text'))
        job.required_education = self._split_csv(self.cleaned_data.get('required_education_text'))
        if commit:
            job.save()
        return job

class ResumeForm(AriaInvalidMixin, FileValidationMixin, FileSaveMixin, forms.ModelForm):
    """Form for creating and editing resumes - only name and file required, AI handles the rest."""

    class Meta:
        model = Resume
        fields = ['candidate_name', 'email', 'phone', 'file']
        widgets = {
            'candidate_name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Enter candidate full name',
                'autocomplete': 'name',
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-input',
                'placeholder': 'candidate@example.com',
                'autocomplete': 'email',
                'inputmode': 'email',
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': '+880 1XXX-XXXXXX',
                'type': 'tel',
                'autocomplete': 'tel',
                'inputmode': 'tel',
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

    def __init__(self, *args, require_contact=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = False
        self.fields['phone'].required = False
        self.fields['file'].required = True
        if require_contact:
            self.fields['email'].required = True
            self.fields['phone'].required = True

    def clean_file(self):
        """Validate uploaded file using mixin."""
        return self.validate_resume_file(self.cleaned_data.get('file'))

    def clean_candidate_name(self):
        return clean_person_text(self.cleaned_data.get('candidate_name'), required=True)

    def clean(self):
        data = super().clean()
        phone_required = self.fields['phone'].required
        try:
            data['phone'] = clean_phone_text(data.get('phone'), required=phone_required)
        except forms.ValidationError as exc:
            self.add_error('phone', exc)
        return data

    def save(self, commit=True):
        """Save with file metadata using mixin."""
        return self.save_with_file_metadata(commit)

class ResumeEditForm(AriaInvalidMixin, FileValidationMixin, FileSaveMixin, forms.ModelForm):
    """Form for editing resumes - includes AI-generated fields that can be manually adjusted."""

    SCORE_FIELDS = {'experience_score', 'education_score', 'skills_score',
                    'certification_score', 'achievement_score', 'final_score'}

    reason = forms.CharField(
        required=False, label='Reason for score change',
        help_text='Required when you change a score. Recorded in the audit trail (not stored on the résumé).',
        widget=forms.Textarea(attrs={'class': 'form-input', 'rows': 2,
                                     'placeholder': 'Why are you overriding the AI score?'}),
    )

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

    def clean(self):
        cleaned = super().clean()
        score_changed = any(f in self.changed_data for f in self.SCORE_FIELDS)
        if score_changed and not (cleaned.get('reason') or '').strip():
            self.add_error('reason', 'A reason is required when you change a score.')
        return cleaned

    def clean_candidate_name(self):
        return clean_person_text(self.cleaned_data.get('candidate_name'), required=True)

    def clean_phone(self):
        return clean_phone_text(self.cleaned_data.get('phone'))

    def save(self, commit=True):
        """Save with file metadata using mixin."""
        return self.save_with_file_metadata(commit)
