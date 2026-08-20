"""Django forms built at runtime from `schema.STEPS`.

One class handles every step: the questions for the step are turned into form
fields, so there is no per-step form class to keep in sync with the schema.
"""
import os

from django import forms
from django.utils import timezone

from apps.core.form_utils import (
    AriaInvalidMixin,
    clean_person_text,
    clean_phone_text,
)

from . import schema
from .models import EmployeeForm

# Candidate documents are ID scans and certificates, so images are allowed here
# in addition to the PDF/DOCX the resume upload accepts.
ALLOWED_EXTENSIONS = ['pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png', 'webp']
MAX_FILE_SIZE = schema.MAX_UPLOAD_MB * 1024 * 1024

# Leading bytes per format. Checked so a renamed executable cannot be stored as
# a "certificate" -- the extension alone is attacker-controlled.
MAGIC_BYTES = {
    'pdf': [b'%PDF'],
    'doc': [b'\xd0\xcf\x11\xe0'],
    'docx': [b'PK\x03\x04'],
    'jpg': [b'\xff\xd8\xff'],
    'jpeg': [b'\xff\xd8\xff'],
    'png': [b'\x89PNG\r\n\x1a\n'],
}

# WEBP needs more than a prefix: "RIFF" alone also matches AVI and WAV, so the
# format tag at offset 8 has to be checked too.
HEADER_BYTES = 12


def _header_matches(ext: str, header: bytes) -> bool:
    if ext == 'webp':
        return header[:4] == b'RIFF' and header[8:12] == b'WEBP'
    expected = MAGIC_BYTES.get(ext)
    if not expected:
        return True
    return any(header.startswith(magic) for magic in expected)

# Questions whose free text is a name or a label, so the shared validators from
# core apply. Everything else (addresses, ID numbers, narrative answers) is left
# as plain text: NID numbers and addresses legitimately contain characters the
# name validator rejects.
PERSON_TEXT_KEYS = frozenset({'candidate_full_name', 'typed_signature'})

# Dates that record something that has already happened. A future value is a
# typo, and this data is handed to a background-check agency, so it is rejected
# rather than stored. `earliest_joining_date` is deliberately absent — that one
# is supposed to be in the future.
NOT_FUTURE_DATE_KEYS = frozenset({
    'date_of_birth',
    'masters_completion_date',
    'bachelors_completion_date',
    'declaration_date',
    *(f'employer_{i}_start_date' for i in range(1, 5)),
    *(f'employer_{i}_end_date' for i in range(1, 5)),
})

# (start, end) pairs that must be in order.
DATE_RANGE_PAIRS = tuple(
    (f'employer_{i}_start_date', f'employer_{i}_end_date') for i in range(1, 5)
)


def _validate_upload(upload):
    """Size, extension and magic-byte checks for one uploaded document."""
    if not upload:
        return upload

    if upload.size > MAX_FILE_SIZE:
        raise forms.ValidationError(f'File size must be under {schema.MAX_UPLOAD_MB}MB.')

    _, raw_ext = os.path.splitext(upload.name)
    ext = raw_ext.lstrip('.').lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise forms.ValidationError(
            'Invalid file type. Allowed: PDF, DOC, DOCX, JPG, PNG or WEBP.'
        )

    upload.seek(0)
    header = upload.read(HEADER_BYTES)
    upload.seek(0)
    if not _header_matches(ext, header):
        raise forms.ValidationError(
            f'File content does not match {ext.upper()} format. Please upload a valid file.'
        )
    return upload


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """A FileField that cleans a list of uploads instead of a single one."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultipleFileInput())
        self.max_files = kwargs.pop('max_files', schema.MAX_FILES_PER_QUESTION)
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if not data:
            return super().clean(data, initial)
        uploads = data if isinstance(data, (list, tuple)) else [data]
        if len(uploads) > self.max_files:
            raise forms.ValidationError(
                f'Upload at most {self.max_files} files.'
            )
        return [super(MultipleFileField, self).clean(u, initial) for u in uploads]


def build_field(question):
    """Turn one schema question into a Django form field.

    Text-like widgets carry the shared `form-input` class so these fields look
    like every other form in the app; radio/checkbox lists are styled by the
    template instead, since they render as a list of inputs.
    """
    qtype = question['type']
    common = {
        'label': question['label'],
        'required': question['required'],
        'help_text': question['help'],
    }
    styled = {'class': 'form-input'}

    if qtype == schema.TEXTAREA:
        return forms.CharField(
            **common, max_length=4000,
            widget=forms.Textarea(attrs={**styled, 'rows': 3}),
        )
    if qtype == schema.EMAIL:
        return forms.EmailField(
            **common, max_length=254, widget=forms.EmailInput(attrs=styled),
        )
    if qtype == schema.PHONE:
        return forms.CharField(
            **common, max_length=32, widget=forms.TextInput(attrs=styled),
        )
    if qtype == schema.DATE:
        return forms.DateField(
            **common, widget=forms.DateInput(attrs={**styled, 'type': 'date'}),
        )
    if qtype == schema.RADIO:
        return forms.ChoiceField(
            **common, choices=question['choices'], widget=forms.RadioSelect,
        )
    if qtype == schema.SELECT:
        return forms.ChoiceField(
            **common, choices=[('', 'Choose')] + list(question['choices']),
            widget=forms.Select(attrs=styled),
        )
    if qtype == schema.CHECKBOX:
        return forms.MultipleChoiceField(
            **common, choices=question['choices'],
            widget=forms.CheckboxSelectMultiple,
        )
    if qtype == schema.FILE:
        return forms.FileField(**common)
    if qtype == schema.FILES:
        return MultipleFileField(**common, max_files=question['max_files'])
    return forms.CharField(
        **common, max_length=500, widget=forms.TextInput(attrs=styled),
    )


class StepForm(AriaInvalidMixin, forms.Form):
    """The questions of a single step.

    `already_uploaded` lists the file-question keys that already have a stored
    upload, so a required upload does not have to be re-attached when the
    candidate revisits the step via Back.
    """

    def __init__(self, *args, step_key=None, already_uploaded=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.step_key = step_key
        self.step = schema.get_step(step_key)
        self.already_uploaded = set(already_uploaded)
        self.questions = []

        for question in schema.numbered_questions(step_key, kwargs.get('initial') or {}):
            field = build_field(question)
            if question['type'] in schema.FILE_TYPES and question['key'] in self.already_uploaded:
                # Already on file -- keep the input available for replacement
                # but stop requiring a new attachment.
                field.required = False
            self.fields[question['key']] = field
            self.questions.append(question)

    def clean(self):
        cleaned = super().clean()
        for question in self.questions:
            key = question['key']
            if key not in cleaned:
                continue
            value = cleaned[key]

            if question['type'] in schema.FILE_TYPES:
                try:
                    if question['type'] == schema.FILES:
                        cleaned[key] = [_validate_upload(u) for u in (value or [])]
                    elif value:
                        cleaned[key] = _validate_upload(value)
                except forms.ValidationError as exc:
                    self.add_error(key, exc)
                continue

            if question['type'] == schema.PHONE:
                try:
                    cleaned[key] = clean_phone_text(value, required=question['required'])
                except forms.ValidationError as exc:
                    self.add_error(key, exc)
                continue

            if question['type'] == schema.DATE:
                if value and key in NOT_FUTURE_DATE_KEYS and value > timezone.localdate():
                    self.add_error(key, 'This date cannot be in the future.')
                continue

            if question['type'] == schema.TEXT:
                try:
                    if key in PERSON_TEXT_KEYS:
                        cleaned[key] = clean_person_text(value, required=question['required'])
                    else:
                        cleaned[key] = (value or '').strip()
                except forms.ValidationError as exc:
                    self.add_error(key, exc)

        # An employment that ends before it starts is bad data going to a
        # background-check agency, so it is caught here rather than stored.
        for start_key, end_key in DATE_RANGE_PAIRS:
            start = cleaned.get(start_key)
            end = cleaned.get(end_key)
            if start and end and end < start:
                self.add_error(end_key, 'The end date cannot be before the start date.')

        return cleaned

    def question_fields(self):
        """(question, bound field) pairs in schema order.

        Django templates cannot look a form field up by a loop variable, so the
        pairing happens here instead of via a template filter.
        """
        return [
            {'question': question, 'field': self[question['key']]}
            for question in self.questions
        ]

    def field_groups(self):
        """Bound fields arranged into the step's titled blocks.

        Mirrors `question_fields` but preserves `schema.STEP_GROUPS`, so a step
        with 23 questions renders as a few short sections instead of one wall.
        """
        return [
            {
                'title': block['title'],
                'fields': [
                    {
                        'question': question,
                        'field': self[question['key']],
                        'half': schema.is_half_width(question),
                        'label': schema.wizard_label(question),
                    }
                    for question in block['questions']
                ],
            }
            for block in schema.question_groups(self.step_key, self.initial or {})
        ]

    def storable_answers(self):
        """Cleaned non-file answers, JSON-serialisable for the answers field."""
        out = {}
        for question in self.questions:
            key = question['key']
            if question['type'] in schema.FILE_TYPES or key not in self.cleaned_data:
                continue
            value = self.cleaned_data[key]
            if question['type'] == schema.DATE and value:
                value = value.isoformat()
            out[key] = value
        return out

    def uploads(self):
        """(question_key, [files]) for every file question that got new uploads."""
        out = []
        for question in self.questions:
            key = question['key']
            if question['type'] not in schema.FILE_TYPES:
                continue
            value = self.cleaned_data.get(key)
            if not value:
                continue
            out.append((key, value if isinstance(value, list) else [value]))
        return out


class OtpForm(AriaInvalidMixin, forms.Form):
    """The one-time code emailed alongside the form link."""

    code = forms.CharField(
        label='Verification code',
        max_length=EmployeeForm.OTP_DIGITS,
        widget=forms.TextInput(attrs={
            'inputmode': 'numeric',
            'autocomplete': 'one-time-code',
            'placeholder': '0' * EmployeeForm.OTP_DIGITS,
        }),
    )

    def clean_code(self):
        code = (self.cleaned_data['code'] or '').strip()
        if not code.isdigit():
            raise forms.ValidationError(
                f'Enter the {EmployeeForm.OTP_DIGITS}-digit code from your email.'
            )
        return code
