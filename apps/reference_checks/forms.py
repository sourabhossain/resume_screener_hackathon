"""Django forms built at runtime from `schema.FORMS`.

One class serves every verification form; the `kind` decides which schema it
reads. Field construction is shared with the Employee Information Form.
"""
from django import forms
from django.utils import timezone

from apps.core.form_logic import ConditionalFormMixin, is_visible
from apps.core.form_utils import AriaInvalidMixin, clean_phone_text
from apps.employee_form.forms import build_field

from . import schema

NOT_FUTURE_DATE_KEYS = frozenset({'employment_start_date', 'employment_end_date'})
DECLARATION_ERROR = 'Please tick the declaration to submit this form.'


class StepForm(ConditionalFormMixin, AriaInvalidMixin, forms.Form):
    """The questions of a single section of one verification form.

    `fixed` holds the read-only Section A facts; whatever is posted for those
    keys is ignored and the fixed value stored instead.
    """

    def __init__(self, *args, kind=None, step_key=None, fixed=None, context=None,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.initial = dict(self.initial or {})
        self.kind = kind
        self.step_key = step_key
        self.step = schema.get_step(kind, step_key)
        self.fixed = dict(fixed or {})
        self.logic_context = context or {}
        self.questions = []

        for question in schema.questions(kind, step_key):
            if question.get('readonly') and not self.fixed.get(question['key']):
                # Nothing on file to show, so the respondent has to type it.
                question = {**question, 'readonly': False}
            self.fields[question['key']] = build_field(question)
            if question.get('readonly'):
                self.fields[question['key']].required = False
                self.initial[question['key']] = self.fixed[question['key']]
            self.questions.append(question)

    def clean(self):
        cleaned = super().clean()
        for question in self.questions:
            key = question['key']
            if question.get('readonly'):
                cleaned[key] = self.fixed[key]
                self.errors.pop(key, None)
                continue
            if key not in cleaned:
                continue
            value = cleaned[key]
            if question['type'] == schema.PHONE:
                try:
                    cleaned[key] = clean_phone_text(value, required=question['required'])
                except forms.ValidationError as exc:
                    self.add_error(key, exc)
            elif question['type'] == schema.TEXT:
                cleaned[key] = (value or '').strip()
            elif question['type'] == schema.DATE:
                if value and key in NOT_FUTURE_DATE_KEYS and value > timezone.localdate():
                    self.add_error(key, 'This date cannot be in the future.')

        start, end = cleaned.get('employment_start_date'), cleaned.get('employment_end_date')
        if start and end and end < start:
            self.add_error('employment_end_date',
                           'The end date cannot be before the start date.')

        self.apply_logic(cleaned)
        self._require_declaration(cleaned)
        return cleaned

    def _require_declaration(self, cleaned):
        answers = self.logic_answers(cleaned)
        for question in self.questions:
            if question['type'] != schema.BOOLEAN or not question['required']:
                continue
            if is_visible(question, answers) and cleaned.get(question['key']) != 'yes':
                self.add_error(question['key'], DECLARATION_ERROR)

    def field_rows(self):
        """Bound fields with their layout hints, in schema order."""
        return [
            {
                'question': question,
                'field': self[question['key']],
                'half': schema.is_half_width(question),
                'label': question.get('statement') or question['label'],
            }
            for question in self.questions
        ]

    def storable_answers(self):
        """Cleaned answers, JSON-serialisable for the answers field."""
        out = {}
        for question in self.questions:
            key = question['key']
            if key not in self.cleaned_data:
                continue
            value = self.cleaned_data[key]
            if question['type'] == schema.DATE and value:
                value = value.isoformat()
            out[key] = value
        return out
