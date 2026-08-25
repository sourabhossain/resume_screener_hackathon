"""Django forms built at runtime from `schema.STEPS`.

One class handles every section. Field construction and upload validation are
reused from the Employee Information Form rather than reimplemented: the two
forms share the same question vocabulary, so `build_field` already knows how to
turn one of these dicts into the right widget -- including the numeric bounds and
the magic-byte upload checks.
"""
from django import forms
from django.utils import timezone

from apps.core.form_utils import AriaInvalidMixin, clean_phone_text
from apps.employee_form.forms import _validate_upload, build_field

from . import schema

# Dates that record something already done. A future value is a typo, and this
# record is handed to a background-check agency, so it is rejected rather than
# stored. `confirmed_joining_date` is deliberately absent -- that one is meant to
# be in the future.
NOT_FUTURE_DATE_KEYS = frozenset({
    'verification_start_date',
    'agency_report_date',
    'candidate_date_of_birth',
    'police_verification_date',
    'masters_completion_date',
    'bachelors_completion_date',
    'section_e_completion_date',
    'offer_letter_issue_date',
    'offer_acceptance_date',
    'actual_joining_date',
    'final_signoff_date',
    *(f'employer_{i}_claimed_start_date' for i in range(1, schema.EMPLOYER_COUNT + 1)),
    *(f'employer_{i}_claimed_end_date' for i in range(1, schema.EMPLOYER_COUNT + 1)),
    *(f'employer_{i}_confirmed_start_date' for i in range(1, schema.EMPLOYER_COUNT + 1)),
    *(f'employer_{i}_confirmed_end_date' for i in range(1, schema.EMPLOYER_COUNT + 1)),
})

# (start, end) pairs on the same section that must be in order.
DATE_RANGE_PAIRS = (
    *((f'employer_{i}_claimed_start_date', f'employer_{i}_claimed_end_date')
      for i in range(1, schema.EMPLOYER_COUNT + 1)),
    *((f'employer_{i}_confirmed_start_date', f'employer_{i}_confirmed_end_date')
      for i in range(1, schema.EMPLOYER_COUNT + 1)),
    ('offer_letter_issue_date', 'offer_acceptance_date'),
)


class StepForm(AriaInvalidMixin, forms.Form):
    """The questions of a single section.

    `already_uploaded` lists the file-question keys that already have a stored
    upload, so a required upload does not have to be re-attached when HR comes
    back to a section they have already saved.
    """

    def __init__(self, *args, step_key=None, already_uploaded=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.step_key = step_key
        self.step = schema.get_step(step_key)
        self.already_uploaded = set(already_uploaded)
        self.questions = schema.numbered_questions(step_key)

        for question in self.questions:
            field = build_field(question)
            if (question['type'] in schema.FILE_TYPES
                    and question['key'] in self.already_uploaded):
                field.required = False
            self.fields[question['key']] = field

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
                cleaned[key] = (value or '').strip()

        for start_key, end_key in DATE_RANGE_PAIRS:
            start = cleaned.get(start_key)
            end = cleaned.get(end_key)
            if start and end and end < start:
                self.add_error(end_key, 'This date cannot be before the start date.')

        self._validate_employer_blocks(cleaned)
        return cleaned

    def _validate_employer_blocks(self, cleaned):
        """Naming an employer makes the rest of that employer required.

        The PDF marks Employer 1-4 required outright, which no candidate with
        fewer than four jobs could satisfy. Employer names are prefilled from the
        candidate's own form, so a job they declared still ends up required of
        HR -- without blocking a case where there is nothing to verify.
        """
        for index in range(1, schema.EMPLOYER_COUNT + 1):
            name_key = f'employer_{index}_name'
            if name_key not in self.fields:
                continue
            if not (cleaned.get(name_key) or '').strip():
                continue
            for suffix in schema.EMPLOYER_REQUIRED_ONCE_NAMED:
                key = f'employer_{index}_{suffix}'
                if key in self.fields and not cleaned.get(key):
                    self.add_error(
                        key,
                        'Required once this employer is named. Clear the employer '
                        'name to skip this block.',
                    )

    def field_groups(self):
        """Bound fields arranged into the section's titled blocks."""
        by_key = {q['key']: q for q in self.questions}
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
                    if question['key'] in by_key
                ],
            }
            for block in schema.question_groups(self.step_key)
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
