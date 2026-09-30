"""Django form built at runtime from `schema.STEPS`, one class for every section."""
from django import forms
from django.utils import timezone

from apps.core.form_logic import ConditionalFormMixin
from apps.core.form_utils import AriaInvalidMixin
from apps.employee_form.forms import _validate_upload, build_field

from . import schema

_EMPLOYERS = range(1, schema.EMPLOYER_MAX + 1)

# Dates of things already done; `confirmed_joining_date` may be in the future.
NOT_FUTURE_DATE_KEYS = frozenset({
    'verification_start_date',
    'agency_report_date',
    'candidate_date_of_birth',
    'police_verification_date',
    'verification_completion_date',
    'offer_letter_issue_date',
    'offer_acceptance_date',
    'actual_joining_date',
    'final_signoff_date',
    *(f'employer_{i}_{s}' for i in _EMPLOYERS
      for s in ('claimed_start_date', 'claimed_end_date',
                'confirmed_start_date', 'confirmed_end_date')),
})

DATE_RANGE_PAIRS = (
    *((f'employer_{i}_claimed_start_date', f'employer_{i}_claimed_end_date')
      for i in _EMPLOYERS),
    *((f'employer_{i}_confirmed_start_date', f'employer_{i}_confirmed_end_date')
      for i in _EMPLOYERS),
    ('offer_letter_issue_date', 'offer_acceptance_date'),
)

# Pairs whose two dates sit in different sections, so one side is read from
# the answers already saved (the form's context).
CROSS_SECTION_DATE_PAIRS = (
    ('verification_start_date', 'verification_completion_date',
     'The completion date cannot be before the verification start date.',
     'The start date cannot be after the verification completion date.'),
)


def _as_date(value):
    import datetime
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


class StepForm(ConditionalFormMixin, AriaInvalidMixin, forms.Form):
    """The questions of one section; `context` = stored answers of the other sections."""

    def __init__(self, *args, step_key=None, already_uploaded=(), context=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.logic_context = context or {}
        self.step_key = step_key
        self.step = schema.get_step(step_key)
        self.already_uploaded = set(already_uploaded)
        self.questions = schema.questions(step_key)

        initial = dict(self.initial or {})
        for question in self.questions:
            key = question['key']
            field = build_field(question)
            if question['type'] in schema.FILE_TYPES and key in self.already_uploaded:
                field.required = False
            if question['type'] == schema.BOOLEAN:
                # Stored as 'yes' / 'no'; the tick box template reads truthiness.
                initial[key] = initial.get(key) in ('yes', True)
            self.fields[key] = field
        self.initial = initial

    def logic_answers(self, cleaned):
        answers = super().logic_answers(cleaned)
        for question in self.questions:
            if question['type'] == schema.BOOLEAN and isinstance(answers.get(question['key']), bool):
                answers[question['key']] = 'yes' if answers[question['key']] else 'no'
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
                    if value:
                        cleaned[key] = _validate_upload(value, question.get('formats'))
                except forms.ValidationError as exc:
                    self.add_error(key, exc)
                continue

            if question['type'] == schema.DATE:
                if value and key in NOT_FUTURE_DATE_KEYS and value > timezone.localdate():
                    self.add_error(key, 'This date cannot be in the future.')
                continue

            if question['type'] in (schema.TEXT, schema.TEXTAREA):
                cleaned[key] = (value or '').strip()

        self.apply_logic(cleaned)

        for start_key, end_key in DATE_RANGE_PAIRS:
            start = cleaned.get(start_key)
            end = cleaned.get(end_key)
            if start and end and end < start and not self.errors.get(end_key):
                self.add_error(end_key, 'This date cannot be before the start date.')

        for start_key, end_key, end_message, start_message in CROSS_SECTION_DATE_PAIRS:
            on_page = start_key in self.fields, end_key in self.fields
            if not any(on_page):
                continue
            start = cleaned.get(start_key) if on_page[0] else _as_date(self.logic_context.get(start_key))
            end = cleaned.get(end_key) if on_page[1] else _as_date(self.logic_context.get(end_key))
            if start and end and end < start:
                key, message = (end_key, end_message) if on_page[1] else (start_key, start_message)
                if not self.errors.get(key):
                    self.add_error(key, message)
        return cleaned

    def field_groups(self):
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
            for block in schema.question_groups(self.step_key)
        ]

    def storable_answers(self):
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
