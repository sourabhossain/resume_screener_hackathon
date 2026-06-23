"""Shared form validation helpers and toast-based error surfacing."""
import unicodedata

from django import forms
from django.contrib import messages

_PERSON_TEXT_EXTRA = frozenset(" -.'")
_LABEL_TEXT_EXTRA = frozenset(" -.'&,()/")
_UNICODE_MARK_CATEGORIES = frozenset({'Mn', 'Mc', 'Me', 'Zs'})
_PHONE_EXTRA = frozenset("+-() ")


def form_errors_to_messages(request, form) -> None:
    """Convert form validation errors to Django messages (shown as toasts)."""
    for field_name, error_list in form.errors.items():
        if field_name == '__all__':
            for err in error_list:
                messages.error(request, str(err))
        else:
            label = (
                form.fields[field_name].label
                if field_name in form.fields and form.fields[field_name].label
                else field_name.replace('_', ' ').title()
            )
            for err in error_list:
                messages.error(request, f'{label}: {err}')


class AriaInvalidMixin:
    """Mark invalid fields for assistive tech after validation — no visual styling."""

    def is_valid(self):
        valid = super().is_valid()
        if not valid:
            for name in self.fields:
                if self.errors.get(name):
                    self.fields[name].widget.attrs['aria-invalid'] = 'true'
        return valid


def _validate_text(
    value,
    *,
    required=False,
    extra_chars,
    require_letter=False,
    invalid_message,
):
    if value is None:
        value = ''
    value = value.strip()
    if not value:
        if required:
            raise forms.ValidationError('This field is required.')
        return ''

    has_letter = False
    for ch in value:
        cat = unicodedata.category(ch)
        if cat.startswith('L'):
            has_letter = True
            continue
        if cat == 'Nd' or cat in _UNICODE_MARK_CATEGORIES:
            continue
        if ch in extra_chars:
            continue
        raise forms.ValidationError(invalid_message)

    if require_letter and not has_letter:
        raise forms.ValidationError('Must include at least one letter.')

    return value


def clean_person_text(value, *, required=False):
    """Names: Unicode letters, digits, spaces, hyphens, periods, apostrophes."""
    return _validate_text(
        value,
        required=required,
        extra_chars=_PERSON_TEXT_EXTRA,
        require_letter=True,
        invalid_message=(
            'Contains invalid characters. '
            'Use letters, numbers, spaces, hyphens, periods, or apostrophes only.'
        ),
    )


def clean_label_text(value, *, required=False):
    """Titles, departments, locations: person rules + common punctuation."""
    return _validate_text(
        value,
        required=required,
        extra_chars=_LABEL_TEXT_EXTRA,
        require_letter=True,
        invalid_message=(
            'Contains invalid characters. '
            'Use letters, numbers, spaces, and common punctuation only.'
        ),
    )


def clean_phone_text(value, *, required=False):
    """Phone numbers: digits plus +, spaces, hyphens, parentheses."""
    if value is None:
        value = ''
    value = value.strip()
    if not value:
        if required:
            raise forms.ValidationError('This field is required.')
        return ''

    digit_count = 0
    for ch in value:
        if ch.isdigit():
            digit_count += 1
            continue
        if ch in _PHONE_EXTRA:
            continue
        raise forms.ValidationError(
            'Contains invalid characters. Use numbers, spaces, +, -, and parentheses only.'
        )

    if digit_count < 6:
        raise forms.ValidationError('Enter a valid phone number.')

    return value
