"""Django forms built at runtime from `schema.STEPS`.

Field construction, upload validation and the signature decoding are reused from
the Employee Information Form: the three forms share one question vocabulary, so
`build_field` already knows how to turn one of these dicts into the right widget.
"""
from django import forms
from django.utils import timezone

from apps.core.form_utils import AriaInvalidMixin
from apps.employee_form.forms import (
    _decode_drawn_signature,
    _validate_upload,
    build_field,
)

from . import schema

# Dates recording something already done. A future value is a typo, and this
# record goes into the recruitment file.
NOT_FUTURE_DATE_KEYS = frozenset({'date_of_assessment'})


class StepForm(AriaInvalidMixin, forms.Form):
    """The questions of a single section.

    `already_uploaded` lists the file-question keys that already have a stored
    upload, so a signature does not have to be redrawn when the assessor comes
    back to a section they have already saved.
    """

    def __init__(self, *args, step_key=None, already_uploaded=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.step_key = step_key
        self.step = schema.get_step(step_key)
        self.already_uploaded = set(already_uploaded)
        self.questions = schema.numbered_questions(step_key)
        self.rules = schema.conditional_rules(step_key)

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

            if question['type'] == schema.SIGNATURE:
                self._clean_signature(cleaned, question)
                continue

            if question['type'] in schema.FILE_TYPES:
                try:
                    if cleaned[key]:
                        cleaned[key] = _validate_upload(cleaned[key])
                except forms.ValidationError as exc:
                    self.add_error(key, exc)
                continue

            if question['type'] == schema.DATE:
                value = cleaned[key]
                if value and key in NOT_FUTURE_DATE_KEYS and value > timezone.localdate():
                    self.add_error(key, 'This date cannot be in the future.')
                continue

            if question['type'] == schema.TEXT:
                cleaned[key] = (cleaned[key] or '').strip()

        self._apply_conditional_rules(cleaned)
        return cleaned

    def _clean_signature(self, cleaned, question):
        """Resolve an uploaded or drawn signature into one validated upload.

        An upload wins if both are present: picking a file after drawing is the
        assessor changing their mind. Mirrors the candidate form's own handling.
        """
        key = question['key']
        upload = cleaned.get(key)

        if not upload:
            drawn = (self.data.get(question['drawn_key']) or '').strip()
            if drawn:
                try:
                    upload = _decode_drawn_signature(drawn)
                except forms.ValidationError as exc:
                    self.add_error(key, exc)
                    return

        if upload:
            try:
                cleaned[key] = _validate_upload(upload)
            except forms.ValidationError as exc:
                self.add_error(key, exc)
            return

        cleaned[key] = None
        if question['required'] and key not in self.already_uploaded:
            self.add_error(
                key, 'Please sign in the box, or upload an image of your signature.'
            )

    def _apply_conditional_rules(self, cleaned):
        """"Yes (describe below)" has to actually come with the description.

        A recorded risk with no detail cannot be acted on by anyone downstream,
        and "unable to verify" is already a separate answer for the case where
        there is nothing to say.
        """
        for rule in self.rules:
            if not self._rule_is_active(cleaned, rule):
                continue
            for key in rule['keys']:
                if key not in self.fields or self.errors.get(key):
                    # `add_error` drops the key from cleaned_data, so a field
                    # that already failed its own validation must not also be
                    # told it is missing.
                    continue
                if cleaned.get(key) in (None, '', []):
                    self.add_error(key, self._rule_message(rule))

    def _rule_is_active(self, cleaned, rule) -> bool:
        answer = cleaned.get(rule['trigger'])
        if isinstance(answer, (list, tuple)):      # multi-select trigger
            return any(value in rule['when'] for value in answer)
        return answer in rule['when']

    def _rule_message(self, rule) -> str:
        question = schema.QUESTIONS_BY_KEY.get(rule['trigger'], {})
        label = question.get('label', 'that answer')
        return f'Required by your answer to "{label}".'

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
