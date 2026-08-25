"""Django forms built at runtime from `schema.STEPS`.

One class handles every step: the questions for the step are turned into form
fields, so there is no per-step form class to keep in sync with the schema.
"""
import os
from decimal import Decimal

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

# Gated by the "I have a Master's" tick box. Untick and these are hidden in the
# browser and cleared here, so the stored answers can never say "no Master's"
# while carrying a university name -- the same reasoning as the address mirror.
MASTERS_GATED_KEYS = (
    'masters_institution', 'masters_degree_name', 'masters_major',
    'masters_completion_date', 'masters_certificate',
)

# An employer block is all-or-nothing: naming an employer commits you to the rest
# of it. No block is required outright, so a fresher submits them all blank —
# but a half-filled employer would go to a background-check agency with no way to
# reach them, which is worse than no entry at all.
EMPLOYER_REQUIRED_ONCE_NAMED = (
    'hr_contact', 'hr_email', 'position', 'start_date', 'end_date',
    'contact_permission',
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


class YesNoBooleanField(forms.BooleanField):
    """A tick box that stores the PDF's 'yes' / 'no' rather than True / False.

    Keeps the stored answer identical to what the old radio produced, so the
    recruiter view, CSV export and any existing submission all still read it the
    same way.
    """

    def clean(self, value):
        return 'yes' if super().clean(value) else 'no'


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


def _number_field(question, field_class, *, step, inputmode,
                  min_value=None, max_value=None, **extra):
    """A numeric field whose bounds are enforced twice.

    Django re-checks them on POST, and the same min/max/step go onto the input so
    the browser rejects a bad value before the round trip -- which is also what
    stops free text being typed into a field that only ever holds a number.
    """
    low = min_value if min_value is not None else question.get('min_value')
    high = max_value if max_value is not None else question.get('max_value')

    attrs = {'class': 'form-input', 'inputmode': inputmode, 'step': step}
    if low is not None:
        attrs['min'] = low
    if high is not None:
        attrs['max'] = high

    return field_class(
        label=question['label'],
        required=question['required'],
        help_text=question['help'],
        min_value=low,
        max_value=high,
        widget=forms.NumberInput(attrs=attrs),
        **extra,
    )


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
    if qtype == schema.BOOLEAN:
        # required is forced off: a tick box that must be ticked would mean
        # "everyone's addresses are the same", not "answer the question".
        return YesNoBooleanField(
            label=question['label'], required=False, help_text=question['help'],
        )
    if qtype == schema.YEAR:
        # A passing year is always in the past. The ceiling is read per request
        # rather than at import, so it stays right after a New Year without a
        # restart -- the same reasoning as NOT_FUTURE_DATE_KEYS.
        return _number_field(
            question, forms.IntegerField, step='1', inputmode='numeric',
            min_value=schema.EARLIEST_PASSING_YEAR,
            max_value=timezone.localdate().year,
        )
    if qtype == schema.INTEGER:
        return _number_field(
            question, forms.IntegerField, step='1', inputmode='numeric',
        )
    if qtype == schema.DECIMAL:
        decimals = question['decimals']
        return _number_field(
            question, forms.DecimalField, inputmode='decimal',
            step=str(Decimal(1).scaleb(-decimals)) if decimals else '1',
            decimal_places=decimals, max_digits=12,
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

        for question in schema.numbered_wizard_questions(step_key, self._branch_answers()):
            field = build_field(question)
            if question['type'] in schema.FILE_TYPES and question['key'] in self.already_uploaded:
                # Already on file -- keep the input available for replacement
                # but stop requiring a new attachment.
                field.required = False
            self.fields[question['key']] = field
            self.questions.append(question)

    def _branch_answers(self) -> dict:
        """Answers that decide which questions this step actually asks.

        Section D renders its role section on the same page, so the field set
        depends on the department. On POST that has to come from `data` -- the
        candidate may have just changed it -- and on GET from what was saved.
        """
        answers = dict(self.initial or {})
        if self.is_bound:
            for key in schema.INLINE_BRANCHES:
                posted = self.data.get(key)
                if posted:
                    answers[key] = posted
        return answers

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

        self._validate_employer_block(cleaned)
        self._mirror_permanent_address(cleaned)
        self._apply_masters_gate(cleaned)
        return cleaned

    def _apply_masters_gate(self, cleaned):
        """Drop any Master's detail when the candidate says they have no Master's."""
        if 'has_masters' not in self.fields:
            return
        if cleaned.get('has_masters') == 'yes':
            return
        for key in MASTERS_GATED_KEYS:
            if key in self.fields:
                cleaned[key] = None if key in schema.FILE_QUESTION_KEYS else ''
                self.errors.pop(key, None)

    def gated_off_file_keys(self):
        """File questions whose answer was gated away, for the view to unlink.

        Clearing the text answers is not enough: an upload made before the tick
        box was cleared would otherwise stay attached to a Master's the candidate
        now says they do not have.
        """
        if 'has_masters' not in self.fields:
            return []
        if (self.cleaned_data or {}).get('has_masters') == 'yes':
            return []
        return [k for k in MASTERS_GATED_KEYS if k in schema.FILE_QUESTION_KEYS]

    def _mirror_permanent_address(self, cleaned):
        """When "same as present" is ticked, derive the permanent address here.

        The tick box copies the field in the browser too, but that is a
        convenience: this is the authoritative copy. Trusting the posted value
        would let a tampered or JS-disabled submission store "Yes" alongside two
        different addresses -- exactly the contradiction the tick box replaces.
        """
        if 'address_same' not in self.fields or 'permanent_address' not in self.fields:
            return
        if cleaned.get('address_same') != 'yes':
            return
        present = (cleaned.get('present_address') or '').strip()
        if present:
            cleaned['permanent_address'] = present
            # Clear any "this field is required" raised while it was mirrored.
            self.errors.pop('permanent_address', None)

    def _validate_employer_block(self, cleaned):
        """Naming an employer makes the rest of that employer required."""
        for index in range(1, 5):
            name_key = f'employer_{index}_name'
            if name_key not in self.fields:
                continue
            if not (cleaned.get(name_key) or '').strip():
                continue
            for suffix in EMPLOYER_REQUIRED_ONCE_NAMED:
                key = f'employer_{index}_{suffix}'
                if key in self.fields and not cleaned.get(key):
                    self.add_error(
                        key,
                        'Required once you name this employer. Clear the employer '
                        'name to skip this section.',
                    )

    def field_groups(self):
        """Bound fields arranged into the step's titled blocks.

        Django templates cannot look a form field up by a loop variable, so the
        pairing happens here rather than via a template filter. Grouped by
        `schema.STEP_GROUPS` so a 23-question step renders as a few short blocks.
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
            elif question['type'] == schema.DECIMAL and value is not None:
                # `answers` is a JSONField and Decimal is not serialisable; float
                # keeps the answer a number for the recruiter view and exports.
                value = float(value)
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
