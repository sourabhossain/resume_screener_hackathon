"""Django forms built at runtime from `schema.FORMS`.

One class serves all three verification forms; the `kind` decides which schema
it reads. Field construction is reused from the Employee Information Form -- the
whole family shares one question vocabulary.
"""
from django import forms

from apps.core.form_utils import AriaInvalidMixin, clean_phone_text
from apps.employee_form.forms import build_field

from . import schema


class StepForm(AriaInvalidMixin, forms.Form):
    """The questions of a single section of one verification form."""

    def __init__(self, *args, kind=None, step_key=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.kind = kind
        self.step_key = step_key
        self.step = schema.get_step(kind, step_key)
        self.questions = schema.questions(kind, step_key)
        self.rules = schema.conditional_rules(kind, step_key)

        for question in self.questions:
            self.fields[question['key']] = build_field(question)

    def clean(self):
        cleaned = super().clean()
        for question in self.questions:
            key = question['key']
            if key not in cleaned:
                continue
            if question['type'] == schema.PHONE:
                try:
                    cleaned[key] = clean_phone_text(
                        cleaned[key], required=question['required'])
                except forms.ValidationError as exc:
                    self.add_error(key, exc)
            elif question['type'] == schema.TEXT:
                cleaned[key] = (cleaned[key] or '').strip()

        self._apply_conditional_rules(cleaned)
        return cleaned

    def _apply_conditional_rules(self, cleaned):
        """"If Yes, please provide details" has to actually come with them.

        A reported concern with no detail cannot be acted on, and every one of
        these questions already offers "Not known" for the case where the
        respondent has nothing to say.
        """
        for rule in self.rules:
            answer = cleaned.get(rule['trigger'])
            if answer not in rule['when']:
                continue
            for key in rule['keys']:
                if key not in self.fields or self.errors.get(key):
                    # add_error drops the key from cleaned_data, so a field that
                    # already failed must not also be told it is missing.
                    continue
                if cleaned.get(key) in (None, '', []):
                    label = schema.questions_by_key(self.kind).get(
                        rule['trigger'], {}).get('label', 'that answer')
                    self.add_error(key, f'Required by your answer to "{label}".')

    def field_rows(self):
        """Bound fields with their layout hints, in schema order."""
        return [
            {
                'question': question,
                'field': self[question['key']],
                'half': schema.is_half_width(question),
                'label': question['label'],
            }
            for question in self.questions
        ]

    def storable_answers(self):
        """Cleaned answers, JSON-serialisable for the answers field."""
        return {
            question['key']: self.cleaned_data[question['key']]
            for question in self.questions
            if question['key'] in self.cleaned_data
        }
